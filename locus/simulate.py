"""
Monte Carlo engine.

For each of N iterations (all vectorised across iterations with NumPy):
    1. Forward pass in topological order.
         start(n)  = max( own earliest day,
                          finish(pred) + lag   for FS links,
                          start(pred)  + lag   for SS links )
         finish(n) = start + duration                  (calendar-day work)
                   = day on which the W-th workable day ends   (weather work)
       The link that produced the max is recorded as the node's DRIVER.
    2. Driving path: follow drivers back from the milestone. A node's
       Criticality Index (CI) = share of iterations in which it is on that path.
       Unlike CPM "total float = 0", CI reflects that the critical path moves
       from one iteration to the next.
    3. Backward pass against a target date gives, per iteration, the latest
       finish (LF) each node can have without pushing the milestone past target.

Common Random Numbers: a RandomBank holds every uniform draw, so all scenarios
(baseline, relaxed links, later site start) differ only by their logic.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Collection
from dataclasses import dataclass, field

import numpy as np

from . import distributions as dist
from .model import Model

logger = logging.getLogger(__name__)

DEFAULT_HORIZON = 3650  # days of weather when no horizon is given; about 10 years
# required_horizon(): pessimistic quantile for every input, safety factor for
# worse-than-average weather, and rounding step (days).
HORIZON_QUANTILE = 0.999
HORIZON_MARGIN = 1.25
HORIZON_STEP = 30


@dataclass(frozen=True)
class Scenario:
    """Logic changes applied on top of the baseline network."""
    relaxed: frozenset = frozenset()   # link indices whose `relax` alternative is used
    site_start_shift: int = 0          # days added to every site_start item (activity start, external arrival)
    # (first_day, n_days): every weather-sensitive activity loses all of these
    # days, on top of the simulated weather (a forced stoppage for stress tests).
    stoppage: tuple[int, int] | None = None
    disabled_risks: frozenset = frozenset()   # ids of common risks switched off
    # True: weather is not applied to the schedule (every day is workable); the
    # forced stoppage above still applies. The random numbers are the same, so
    # the difference to a weather run is the weather alone.
    ignore_weather: bool = False
    # Fixed delays the user tests, as sorted (node id, days) pairs: added to an
    # external input's arrival or to an activity's duration in every iteration.
    # The single-number plan never carries them (it shows the planned dates).
    extra_days: tuple[tuple[str, float], ...] = ()
    label: str = "Baseline"

    @property
    def extra(self) -> dict[str, float]:
        """The tested delays as {node id: days}, leaving out zeros."""
        return {nid: float(d) for nid, d in self.extra_days if d}


def delays(mapping: dict[str, float]) -> tuple[tuple[str, float], ...]:
    """{node id: days} -> the hashable form Scenario.extra_days expects (sorted, zeros dropped)."""
    return tuple(sorted((nid, float(d)) for nid, d in mapping.items() if d))


@dataclass
class EffectiveEdge:
    link_idx: int
    src: str
    dst: str
    rel: str
    lag: float


def node_stream(parent: np.random.SeedSequence, node_id: str) -> np.random.SeedSequence:
    """
    The random stream of one node: a child of the node stream keyed by a
    32-bit checksum (CRC-32) of the node id. Keyed children are independent
    of each other and do not depend on which other nodes exist.
    """
    key = zlib.crc32(node_id.encode("utf-8"))
    return np.random.SeedSequence(parent.entropy, spawn_key=parent.spawn_key + (key,))


class RandomBank:
    """
    All randomness for one (model, n_iter, seed) combination.

    u_node[node_id] : one uniform per iteration for that node's duration/delay,
                      from the node's own stream (keyed by its id, see below)
    u_risk[risk_id] : (occurs, impact) uniforms per iteration for each common risk
    weather         : one uniform per iteration per calendar day, per kind.
                      A day is workable for rain-sensitive work when u_rain >= p_rain(day).

    The seed is split into independent streams (nodes, rain, wind), and weather
    uniforms are drawn day by day. Day d therefore gets the same draws whatever
    the horizon is: the horizon only decides how far ahead the draws are kept,
    never what they are, so changing it cannot change any result.

    Weather uniforms are not stored. prepare_weather() redraws them from their
    stream and keeps only the cumulative count of workable days (int32), which
    is all the simulation needs: 4 bytes per iteration-day and weather kind.
    """

    WEATHER_KINDS = ("rain", "wind")
    _DAY_BLOCK = 64   # days drawn and counted at a time, bounds the temporary memory

    def __init__(self, model: Model, n_iter: int, seed: int, horizon: int = DEFAULT_HORIZON):
        if n_iter < 50:
            raise ValueError("Use at least 50 iterations for stable percentiles")
        if horizon < 365:
            raise ValueError("Horizon must cover at least one year")
        keys: dict[int, str] = {}
        for nid in model.nodes:
            other = keys.setdefault(zlib.crc32(nid.encode("utf-8")), nid)
            if other != nid:
                raise ValueError(f"Node ids '{other}' and '{nid}' share a random stream; rename one of them")
        self.n_iter = int(n_iter)
        self.seed = int(seed)
        self.horizon = int(horizon)
        # Child streams are keyed by position, so adding the risk stream last
        # leaves the node and weather draws exactly as they were.
        node_seq, *weather_seqs, risk_seq = np.random.SeedSequence(self.seed).spawn(
            2 + len(self.WEATHER_KINDS))
        # Every node draws from its own stream, keyed by its id: adding, removing
        # or renaming one node never changes the draws of any other node.
        self.u_node = {nid: np.random.default_rng(node_stream(node_seq, nid)).random(self.n_iter)
                       for nid in sorted(model.nodes)}
        rng = np.random.default_rng(risk_seq)
        self.u_risk = {r.id: (rng.random(self.n_iter), rng.random(self.n_iter))
                       for r in sorted(model.risks, key=lambda r: r.id)}
        self._weather_seq = dict(zip(self.WEATHER_KINDS, weather_seqs))
        self._prepared: dict[str, np.ndarray] = {}

    @property
    def nbytes(self) -> int:
        """Memory held by the bank's arrays, in bytes."""
        return (sum(u.nbytes for u in self.u_node.values())
                + sum(a.nbytes + b.nbytes for a, b in self.u_risk.values())
                + sum(a.nbytes for a in self._prepared.values()))

    def prepare_weather(self, daily_p: dict[str, np.ndarray],
                        persistence: dict[str, np.ndarray] | None = None) -> None:
        """
        Per weather kind, build a flattened, row-offset cumulative count of
        workable days that allows ONE searchsorted call for all iterations:
            flat[r * H + d] = workable days in [0, d] of iteration r  +  r * (H + 1)
        The offset r * (H + 1) exceeds any count of an earlier row, so the rows
        stay strictly separated and the whole array is sorted.

        Which days are lost:
            persistence is None : day d is lost when u[d] < p[d] (independent days)
            persistence[kind]   : two-state Markov chain (see locus.weather), with
                                  p11[d] = persistence[kind][d] and p01 chosen so the
                                  long-run lost share stays p[d]:
                                      day 0 lost  when u[0] < p[0]
                                      day d lost  when u[d] < (p11[d] if day d-1 lost else p01[d])
        Both read the same uniforms u, so switching spells on or off is a clean
        common-random-numbers comparison.
        """
        H, N = self.horizon, self.n_iter
        # int32 halves the memory of int64; fall back when the offsets would not fit.
        dtype = np.int32 if N * (H + 1) < np.iinfo(np.int32).max else np.int64
        for kind in self.WEATHER_KINDS:
            p = np.asarray(daily_p[kind][:H], dtype=np.float32)
            if p.shape[0] < H:
                raise ValueError(f"Daily {kind} probabilities cover {p.shape[0]} days, need {H}")
            chain = persistence is not None
            if chain:
                p11 = np.asarray(persistence[kind][:H], dtype=np.float64)
                if p11.shape[0] < H:
                    raise ValueError(f"Daily {kind} persistence covers {p11.shape[0]} days, need {H}")
                pd_ = p.astype(np.float64)
                p01 = (pd_ * (1.0 - p11) / (1.0 - pd_)).astype(np.float32)
                p11 = p11.astype(np.float32)
                if np.any(p01 > 1) or np.any(p11 < 0) or np.any(p11 >= 1):
                    raise ValueError(f"{kind}: persistence gives transition probabilities outside [0, 1]")
                prev = None                                          # state of day d-1
            rng = np.random.default_rng(self._weather_seq[kind])
            cum = np.empty((N, H), dtype=dtype)
            carry = np.zeros(N, dtype=dtype)
            for d0 in range(0, H, self._DAY_BLOCK):
                d1 = min(d0 + self._DAY_BLOCK, H)
                u = rng.random((d1 - d0, N), dtype=np.float32)     # day-major draw order
                if not chain:
                    lost = u < p[d0:d1, None]
                else:
                    lost = np.empty(u.shape, dtype=bool)
                    for k in range(d1 - d0):
                        d = d0 + k
                        thr = p[0] if prev is None else np.where(prev, p11[d], p01[d])
                        lost[k] = prev = u[k] < thr
                block = np.cumsum(~lost.T, axis=1, dtype=dtype)     # (N, days in block)
                block += carry[:, None]
                cum[:, d0:d1] = block
                carry = block[:, -1]
            cum += (np.arange(N, dtype=dtype) * dtype(H + 1))[:, None]
            self._prepared[kind] = cum.ravel()                      # a view, no copy
        self._daily_p = daily_p
        self.spells = persistence is not None

    def lost_days(self, kind: str, days: int | None = None) -> np.ndarray:
        """Boolean (n_iter, days) matrix: True where the day is lost for `kind` work."""
        flat = self.weather_arrays(kind)
        H, N = self.horizon, self.n_iter
        D = H if days is None else max(0, min(int(days), H))
        cum = flat.reshape(N, H)[:, :D].astype(np.int64) - (np.arange(N, dtype=np.int64) * (H + 1))[:, None]
        return np.diff(cum, axis=1, prepend=0) == 0

    def weather_arrays(self, kind: str) -> np.ndarray:
        if kind not in self._prepared:
            raise RuntimeError("Call prepare_weather() before simulating weather-sensitive work")
        return self._prepared[kind]


@dataclass
class SimResult:
    model: Model
    scenario: Scenario
    start: np.ndarray            # (n_nodes, N) day offsets
    finish: np.ndarray           # (n_nodes, N)
    driver: np.ndarray           # (n_nodes, N) link index that set the start, -1 if none
    edges: dict[int, EffectiveEdge]
    overflow_count: int = 0
    _path: tuple | None = field(default=None, repr=False)

    @property
    def n_iter(self) -> int:
        return self.start.shape[1]

    def node_finish(self, nid: str) -> np.ndarray:
        return self.finish[self.model.index[nid]]

    def milestone_finish(self) -> np.ndarray:
        return self.node_finish(self.model.milestone)

    # ------------------------------------------------------------ driving path
    def driving_path(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns (node_on_path[n_nodes, N], link_on_path[n_links, N]) booleans,
        tracing drivers back from the milestone in every iteration at once.
        """
        if self._path is not None:
            return self._path
        m = self.model
        n_nodes, N = self.start.shape
        n_links = len(m.links)
        node_on = np.zeros((n_nodes, N), dtype=bool)
        link_on = np.zeros((n_links, N), dtype=bool)
        src_of_link = np.array([m.index[self.edges[li].src] for li in range(n_links)], dtype=np.int64)

        rows = np.arange(N)
        cur = np.full(N, m.index[m.milestone], dtype=np.int64)
        active = np.ones(N, dtype=bool)
        for _ in range(n_nodes):                      # a path can't be longer than the node count
            node_on[cur[active], rows[active]] = True
            d = self.driver[cur, rows]
            active &= d >= 0
            if not active.any():
                break
            link_on[d[active], rows[active]] = True
            cur = np.where(active, src_of_link[np.where(d >= 0, d, 0)], cur)
        self._path = (node_on, link_on)
        return self._path

    # ----------------------------------------------------------- backward pass
    def latest_finish(self, target_day: float) -> np.ndarray:
        """
        Latest finish per node per iteration that still lets the milestone meet
        target_day, holding every other node at its simulated duration.
            FS link n -> s : LF(n) <= LS(s) - lag
            SS link n -> s : LS(n) <= LS(s) - lag  ->  LF(n) <= LS(s) - lag + dur(n)
            LS(s) = LF(s) - dur(s)
        Nodes that do not feed the milestone keep LF = +inf.
        """
        m = self.model
        dur = self.finish - self.start
        LF = np.full(self.start.shape, np.inf)
        LF[m.index[m.milestone]] = float(target_day)
        out_eff: dict[str, list[EffectiveEdge]] = {nid: [] for nid in m.nodes}
        for e in self.edges.values():
            out_eff[e.src].append(e)
        for nid in reversed(m.order):
            i = m.index[nid]
            for e in out_eff[nid]:
                j = m.index[e.dst]
                ls_succ = LF[j] - dur[j]
                cand = ls_succ - e.lag if e.rel == "FS" else ls_succ - e.lag + dur[i]
                LF[i] = np.minimum(LF[i], cand)
        return LF


# ------------------------------------------------------------------ helpers
def effective_edges(model: Model, scenario: Scenario) -> dict[int, EffectiveEdge]:
    """Apply relaxations: a relaxed link may change relation, lag and even predecessor."""
    edges = {}
    for link in model.links:
        if link.idx in scenario.relaxed and link.relax is not None:
            r = link.relax
            edges[link.idx] = EffectiveEdge(link.idx, r.get("pred", link.src), link.dst,
                                            r.get("rel", link.rel), float(r.get("lag", link.lag)))
        else:
            edges[link.idx] = EffectiveEdge(link.idx, link.src, link.dst, link.rel, link.lag)
    return edges


def _lookup(r: np.ndarray, s: np.ndarray, w: np.ndarray, flat: np.ndarray,
            horizon: int) -> tuple[np.ndarray, np.ndarray]:
    """
    For iteration rows r starting on day s (0 <= s < horizon) with w > 0 workable
    days of work: (finish day, past-horizon mask). One searchsorted for all rows.
    """
    # Offset count just before the start day: flat value of day s-1, or the
    # bare row offset when work starts on day 0.
    before = np.where(s > 0, flat[r * horizon + np.maximum(s - 1, 0)], r * (horizon + 1))
    # Same dtype as `flat`, otherwise searchsorted would copy the whole bank.
    target = (before + w).astype(flat.dtype)
    pos = np.searchsorted(flat, target, side="left")
    t = pos - r * horizon                                       # day index within the row
    past = t >= horizon                                         # not enough workable days left
    return np.where(past, 0, t + 1).astype(float), past


def _count_to(flat: np.ndarray, r: np.ndarray, d: np.ndarray, horizon: int) -> np.ndarray:
    """Workable days in [0, d] of row r (0 for d < 0)."""
    val = flat[r * horizon + np.maximum(d, 0)].astype(np.int64) - r * (horizon + 1)
    return np.where(d >= 0, val, 0)


def _calendar_finish(start: np.ndarray, work: np.ndarray,
                     stoppage: tuple[int, int] | None = None) -> np.ndarray:
    """
    Finish when every day is workable: start + work, except that work crossing a
    forced stoppage (days a .. b-1) loses those days:
        done before the window = max(a - start, 0);  finish = b + (work - done)
    """
    s = np.asarray(start, dtype=float)
    w = np.asarray(work, dtype=float)
    finish = s + w
    if stoppage is None:
        return finish
    a, n = int(stoppage[0]), int(stoppage[1])
    if a < 0 or n < 1:
        raise ValueError("Stoppage must start on day 0 or later and last at least one day")
    b = a + n
    hit = (w > 0) & (s < b) & (finish > a)
    done = np.maximum(a - s, 0.0)
    return np.where(hit, b + (w - done), finish)


def _weather_finish(start: np.ndarray, work: np.ndarray, flat: np.ndarray, horizon: int,
                    stoppage: tuple[int, int] | None = None) -> tuple[np.ndarray, int]:
    """
    Finish day for `work` workable days starting on day `start`, per iteration.
    finish = 1 + first day t >= start where workable_days(start..t) >= work.
    `flat` is the row-offset cumulative count built by RandomBank.prepare_weather.

    stoppage = (a, n) forces days a .. a+n-1 to be lost. Work that finishes
    before day a or starts on or after day b = a+n is unaffected. Otherwise the
    work done before the window is k = workable_days(max(start, a) .. a-1)
    (zero when it starts inside the window), and the remaining w - k workable
    days resume on day b, where the simulated weather takes over again.

    Returns (finish, number of iterations that ran past the horizon).
    """
    N = start.shape[0]
    rows = np.arange(N, dtype=np.int64)
    s = start.astype(np.int64)
    w = work.astype(np.int64)
    finish = s.astype(float)                                   # zero work -> finish = start

    todo = w > 0
    inside = (s >= 0) & (s < horizon)
    calc = todo & inside
    over = todo & ~inside                                       # starts beyond the horizon
    if calc.any():
        idx = np.flatnonzero(calc)
        f, past = _lookup(rows[idx], s[idx], w[idx], flat, horizon)
        finish[idx] = f
        over[idx[past]] = True

        if stoppage is not None:
            a, n = int(stoppage[0]), int(stoppage[1])
            b = a + n
            if a < 0 or n < 1 or b > horizon:
                raise ValueError(f"Stoppage days {a}..{b - 1} must lie inside the horizon (0..{horizon - 1})")
            hit = calc & ~over & (s < b) & (finish > a)         # last work day on or after a
            if hit.any():
                h = np.flatnonzero(hit)
                r, sh = rows[h], s[h]
                done = np.where(sh < a, _count_to(flat, r, np.full_like(sh, a - 1), horizon)
                                - _count_to(flat, r, sh - 1, horizon), 0)
                f2, past2 = _lookup(r, np.full_like(sh, b), w[h] - done, flat, horizon)
                finish[h] = f2
                over[h[past2]] = True
    overflow = int(over.sum())
    if overflow:
        # Fallback beyond the horizon: nominal 25% weather loss. required_horizon()
        # sizes the horizon so this should not happen; it is reported if it does.
        finish[over] = s[over] + np.ceil(w[over] / 0.75)
    return finish, overflow


# ------------------------------------------------------------ common risks
def risk_effects(model: Model, bank: RandomBank, disabled: frozenset = frozenset()
                 ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """
    Per affected item, the duration factor and the added days in every iteration.

    A risk occurs in an iteration when u_occurs < probability; its size is then
    impact^-1(u_impact), shared by every item it applies to. That sharing is
    what makes their delays move together. Several risks on one item multiply
    (factors) or add (days):
        work    = duration sample * product of factors + sum of days
        arrival = planned day + delay sample + sum of days
    """
    factor: dict[str, np.ndarray] = {}
    extra: dict[str, np.ndarray] = {}
    for risk in model.risks:
        if risk.id in disabled:
            continue
        if risk.id not in bank.u_risk:
            raise ValueError(f"The random bank has no draws for risk '{risk.id}'; build it from this model")
        u_occ, u_imp = bank.u_risk[risk.id]
        occurs = u_occ < risk.probability
        size = dist.sample(risk.impact, u_imp)
        if risk.effect == "factor":
            mult = np.where(occurs, size, 1.0)
            for nid in risk.targets:
                factor[nid] = factor[nid] * mult if nid in factor else mult
        else:
            add = np.where(occurs, size, 0.0)
            for nid in risk.targets:
                extra[nid] = extra[nid] + add if nid in extra else add
    return factor, extra


# --------------------------------------------------------------- simulation
def simulate(model: Model, bank: RandomBank, scenario: Scenario = Scenario()) -> SimResult:
    """Run the vectorised Monte Carlo forward pass for one scenario."""
    N = bank.n_iter
    n_nodes = len(model.order)
    start = np.zeros((n_nodes, N))
    finish = np.zeros((n_nodes, N))
    driver = np.full((n_nodes, N), -1, dtype=np.int64)
    edges = effective_edges(model, scenario)
    incoming_eff: dict[str, list[EffectiveEdge]] = {nid: [] for nid in model.nodes}
    for e in edges.values():
        incoming_eff[e.dst].append(e)

    factor, extra = risk_effects(model, bank, scenario.disabled_risks)
    tested = scenario.extra
    overflow_total = 0
    for nid in model.order:
        node = model.nodes[nid]
        i = model.index[nid]
        u = bank.u_node[nid]

        if node.kind == "external":
            delay = dist.sample(node.delay, u) + tested.get(nid, 0.0)
            if nid in extra:
                delay = delay + extra[nid]
            arrival = node.planned_day + np.rint(delay) + (scenario.site_start_shift if node.site_start else 0)
            start[i] = arrival
            finish[i] = arrival
            continue

        own = node.earliest_day + (scenario.site_start_shift if node.site_start else 0)
        best = np.full(N, float(own))
        drv = np.full(N, -1, dtype=np.int64)
        for e in incoming_eff[nid]:
            j = model.index[e.src]
            cand = (finish[j] if e.rel == "FS" else start[j]) + e.lag
            # Prefer a link over the node's own earliest day on ties, so the
            # driving path stays connected when the logic is exactly binding.
            better = (cand > best) | ((cand == best) & (drv < 0))
            best = np.where(better, cand, best)
            drv = np.where(better, e.link_idx, drv)
        start[i] = best
        driver[i] = drv

        work = dist.sample(node.duration, u)
        if nid in factor:
            work = work * factor[nid]
        if nid in extra:
            work = work + extra[nid]
        work = work + tested.get(nid, 0.0)
        work = np.maximum(np.rint(work), 0)
        if node.weather == "none":
            finish[i] = best + work
        elif scenario.ignore_weather:
            finish[i] = _calendar_finish(best, work, scenario.stoppage)
        else:
            flat = bank.weather_arrays(node.weather)
            finish[i], ov = _weather_finish(best, work, flat, bank.horizon, scenario.stoppage)
            overflow_total += ov

    if overflow_total:
        logger.warning("%d weather calculations ran past the %d-day horizon",
                       overflow_total, bank.horizon)
    return SimResult(model, scenario, start, finish, driver, edges, overflow_total)


def _point_pass(model: Model, daily_p: dict[str, np.ndarray], scenario: Scenario,
                duration_of, delay_of, risk_size=None, mean_nodes: Collection[str] = frozenset(),
                extra_for: Collection[str] = frozenset()) -> dict[str, tuple[float, float]]:
    """
    One forward pass with single-number durations and delays, weather handled
    as an AVERAGE loss: work on day d progresses by (1 - p(d)), so W working
    days finish when the cumulative expected progress reaches W.
    duration_of(spec) and delay_of(spec) turn a distribution into one number;
    nodes in `mean_nodes` use the expected value instead. The scenario's tested
    delays (extra_days) are added only to nodes in `extra_for`.
    risk_size(risk) gives each common risk's factor or days as if it occurred;
    None leaves the risks out (the single-number plan does not carry them).
    """
    tested = {nid: d for nid, d in scenario.extra.items() if nid in extra_for}
    progress = {k: np.cumsum(1.0 - np.asarray(v, dtype=float)) for k, v in daily_p.items()}
    factor: dict[str, float] = {}
    extra: dict[str, float] = {}
    if risk_size is not None:
        for risk in model.risks:
            if risk.id in scenario.disabled_risks:
                continue
            size = float(risk_size(risk))
            for nid in risk.targets:
                if risk.effect == "factor":
                    factor[nid] = factor.get(nid, 1.0) * size
                else:
                    extra[nid] = extra.get(nid, 0.0) + size
    edges = effective_edges(model, scenario)
    incoming_eff: dict[str, list[EffectiveEdge]] = {nid: [] for nid in model.nodes}
    for e in edges.values():
        incoming_eff[e.dst].append(e)

    times: dict[str, tuple[float, float]] = {}
    for nid in model.order:
        node = model.nodes[nid]
        if node.kind == "external":
            delay = dist.mean_value(node.delay) if nid in mean_nodes else delay_of(node.delay)
            arrival = (node.planned_day + round(delay + extra.get(nid, 0.0) + tested.get(nid, 0.0))
                       + (scenario.site_start_shift if node.site_start else 0))
            times[nid] = (arrival, arrival)
            continue
        s = node.earliest_day + (scenario.site_start_shift if node.site_start else 0)
        for e in incoming_eff[nid]:
            ps, pf = times[e.src]
            s = max(s, (pf if e.rel == "FS" else ps) + e.lag)
        work = dist.mean_value(node.duration) if nid in mean_nodes else duration_of(node.duration)
        w = max(round(work * factor.get(nid, 1.0) + extra.get(nid, 0.0) + tested.get(nid, 0.0)), 0)
        if node.weather == "none" or w == 0 or scenario.ignore_weather:
            f = s + w
        else:
            prog = progress[node.weather]
            si = int(s)
            base = prog[si - 1] if 0 < si <= len(prog) else 0.0
            t = int(np.searchsorted(prog, base + w - 1e-9, side="left")) if si < len(prog) else len(prog)
            f = (t + 1) if t < len(prog) else s + w / 0.75
        times[nid] = (float(s), float(f))
    return times


def deterministic_plan(model: Model, daily_p: dict[str, np.ndarray],
                       scenario: Scenario = Scenario()) -> dict[str, tuple[float, float]]:
    """
    A single-number, P6-style plan: most-likely durations, deliveries on their
    planned day, and weather handled as an average loss (like a weather calendar).
    This is the plan most schedules report; the simulation shows how often it holds.
    """
    return _point_pass(model, daily_p, scenario, dist.typical_value, lambda spec: 0.0)


def point_plan(model: Model, daily_p: dict[str, np.ndarray], scenario: Scenario = Scenario(),
               mean_nodes: Collection[str] = frozenset()) -> float:
    """
    Milestone finish day of one single-number pass (weather as an average loss,
    common risks left out). Nodes in `mean_nodes` are REALISED on average: an
    external input arrives on its planned day plus its expected delay plus any
    tested delay, an activity takes its expected duration plus any tested
    delay. Every other node keeps the plan's number: most-likely duration
    (mode or median), arrival on the planned day.

    point_plan(model, daily_p, s) equals the deterministic plan. Growing
    `mean_nodes` one group at a time shows how much of the gap to the
    simulation each group of optimistic assumptions explains (analysis.plan_gap).
    """
    unknown = set(mean_nodes) - set(model.nodes)
    if unknown:
        raise ValueError(f"Unknown node ids: {sorted(unknown)}")
    times = _point_pass(model, daily_p, scenario, dist.typical_value, lambda spec: 0.0,
                        mean_nodes=frozenset(mean_nodes), extra_for=frozenset(mean_nodes))
    return times[model.milestone][1]


def required_horizon(model: Model, daily_p: dict[str, np.ndarray], extra_days: int = 0,
                     quantile: float = HORIZON_QUANTILE, margin: float = HORIZON_MARGIN,
                     step: int = HORIZON_STEP, tested: tuple[tuple[str, float], ...] = ()) -> int:
    """
    Days of weather the simulation must cover, sized from the model instead of
    a fixed ten years (the weather bank's memory grows with the horizon).

    A pessimistic point pass puts EVERY duration and delivery delay at its
    `quantile` at once, lets every common risk occur at its `quantile` size
    (a risk that could only shorten work is left out), delays site start by
    `extra_days` (the late-start experiment), adds the `tested` delays
    (Scenario.extra_days), and takes the later of the
    baseline and all-links-relaxed logic. The latest finish of any node, times `margin` for weather worse
    than the monthly average, rounded up to `step` days, is the horizon.
    `daily_p` must be long enough to hold that pessimistic plan.

    Only weather-sensitive work reads the weather bank, and it sits well before
    the milestone (civil and erection work), so taking the latest finish of ANY
    node is deliberately generous: for the reference plant weather work ends by
    about day 720 even in the worst of 5,000 iterations, against a horizon of
    about 1,590 days (without the late-start experiment). If a run does go past it, the overflow is counted and
    shown on the Assumptions page.
    """
    if not 0.5 <= quantile < 1:
        raise ValueError("quantile must be in [0.5, 1)")
    if margin < 1:
        raise ValueError("margin must be at least 1")
    at_q = lambda spec: float(dist.sample(spec, np.array([quantile]))[0])
    worst_risk = lambda r: max(at_q(r.impact), 1.0 if r.effect == "factor" else 0.0)
    relax_all = frozenset(l.idx for l in model.relaxable_links())
    latest = 0.0
    for relaxed in (frozenset(), relax_all):
        times = _point_pass(model, daily_p,
                            Scenario(relaxed=relaxed, site_start_shift=int(extra_days), extra_days=tested),
                            at_q, at_q, worst_risk, extra_for=frozenset(model.nodes))
        latest = max(latest, max(f for _, f in times.values()))
    days = int(np.ceil(latest * margin / step) * step)
    return max(365, days)
