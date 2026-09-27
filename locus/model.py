"""
Network model: nodes (activities, external inputs, reviews) and typed links.

The model is deliberately data-driven. Everything project-specific lives in YAML:
    plant file  -> physical logic, activities, assets          (L0, L1, L3, L4)
    rule pack   -> which reviews apply in a jurisdiction         (L2)
    weather     -> site climate                                  (L3)
The code only knows how to assemble, validate and simulate a network.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import distributions as dist

logger = logging.getLogger(__name__)

LINK_TYPES = ("physical", "means", "regulatory", "contractual", "resource", "logistics")
HARD_LINK_TYPES = ("physical", "regulatory")
RELATIONS = ("FS", "SS")
WEATHER_KINDS = ("none", "rain", "wind")
CONDITIONS = ("weather", "productivity", "supply", "regulatory", "milestone", "design", "handover")
# Conditions an external input can carry (it has no duration, so no weather or productivity).
EXTERNAL_CONDITIONS = ("supply", "design", "handover", "regulatory")
SHORT_NAME_MAX = 30   # chart axes use short names; longer labels squeeze the bars
RISK_EFFECTS = ("factor", "days")
RISK_SELECTORS = ("ids", "groups", "conditions", "kinds", "weather")
SOURCE_LABEL_MAX = 40   # a delay source label is a chart row
_SELECTOR_ATTR = {"ids": "id", "groups": "group", "conditions": "condition", "kinds": "kind",
                  "weather": "weather"}


class ModelError(ValueError):
    """Raised when the plant file or rule pack is inconsistent."""


@dataclass
class Node:
    id: str
    name: str
    group: str
    kind: str                      # "activity" | "external"
    condition: str                 # see CONDITIONS
    short_name: str = ""           # chart label, unique, at most SHORT_NAME_MAX characters
    weather: str = "none"
    duration: dict | None = None   # activities
    planned_day: float = 0.0       # externals
    delay: dict | None = None      # externals
    earliest_day: float = 0.0      # own start constraint (e.g. a planned submission day)
    site_start: bool = False       # shifted by the late-start experiment (activity start or external arrival)
    source_grade: str = "C"
    source_note: str = ""
    rule_id: str | None = None     # set when a rule template created the node
    adjustable: bool = False       # offered under "Delays to test" (a fixed delay the user sets)


@dataclass
class Link:
    idx: int
    src: str
    dst: str
    rel: str
    lag: float
    type: str
    why: str = ""
    relax: dict | None = None      # alternative logic, `proposal` and `cost` for "which links can we break"
    origin: str = "plant"          # "plant" or "rule:<id>"

    @property
    def label(self) -> str:
        return f"{self.src} -> {self.dst}"


@dataclass
class Risk:
    """
    A common risk (risk driver): one event that, when it occurs in a simulated
    future, changes MANY items at once, so their delays move together.

    probability : chance that it occurs in a given future
    effect      : "factor" multiplies activity durations (working days for
                  weather-sensitive work); "days" adds days to activity
                  durations or to external arrivals
    impact      : distribution of the factor or the days, when it occurs
    applies_to  : selectors; an item is affected when it matches EVERY given
                  selector (a selector matches when the item's value is in its list)
    targets     : ids of the affected items, resolved by Model.compile()
    """
    id: str
    name: str
    short_name: str
    probability: float
    effect: str
    impact: dict
    applies_to: dict
    source_grade: str = "C"
    source_note: str = ""
    targets: list[str] = field(default_factory=list)


@dataclass
class DelaySource:
    """
    One source of delay for the "where does the delay come from" split
    (analysis.source_gap), for example design, equipment or permits.

    applies_to uses the same selectors as a common risk; an item belongs to the
    FIRST source it matches, and a source without selectors takes every item
    left. Model.compile() checks that every item belongs to a source.
    """
    key: str
    label: str
    what: str
    applies_to: dict
    action: str = ""
    members: list[str] = field(default_factory=list)


@dataclass
class RegisterRow:
    rule_id: str
    rule_name: str
    status: str
    legal_basis: str
    asset_id: str
    asset_name: str
    gate_nodes: list[str]
    process_grade: str
    duration_grade: str
    note: str


@dataclass
class Model:
    meta: dict
    nodes: dict[str, Node]
    links: list[Link]
    milestone: str
    register: list[RegisterRow] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    delay_sources: list[DelaySource] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)   # display order of the groups (plant file `groups`)
    timeline: list[dict] = field(default_factory=list)  # plain-language phases: {label, groups} (plant file `timeline`)
    jurisdiction: str = ""
    # Filled by compile()
    order: list[str] = field(default_factory=list)
    index: dict[str, int] = field(default_factory=dict)
    incoming: dict[str, list[int]] = field(default_factory=dict)
    outgoing: dict[str, list[int]] = field(default_factory=dict)

    # ------------------------------------------------------------------ build
    def add_node(self, node: Node) -> None:
        if node.id in self.nodes:
            raise ModelError(f"Duplicate node id '{node.id}'")
        self.nodes[node.id] = node

    def add_link(self, src: str, dst: str, rel: str, lag: float, type_: str,
                 why: str = "", relax: dict | None = None, origin: str = "plant") -> Link:
        link = Link(idx=len(self.links), src=src, dst=dst, rel=rel, lag=float(lag),
                    type=type_, why=why, relax=relax, origin=origin)
        self.links.append(link)
        return link

    # --------------------------------------------------------------- validate
    def compile(self) -> "Model":
        """Validate the network and compute a topological order (Kahn's algorithm)."""
        if self.milestone not in self.nodes:
            raise ModelError(f"Milestone '{self.milestone}' is not a node")

        if self.groups:
            unlisted = sorted({n.group for n in self.nodes.values()} - set(self.groups))
            if unlisted:
                raise ModelError(f"Group(s) {', '.join(repr(g) for g in unlisted)} are used by items but not "
                                 "listed under `groups` in the plant file")

        for i, phase in enumerate(self.timeline):
            label, groups = phase.get("label"), phase.get("groups")
            if not label or len(str(label)) > SOURCE_LABEL_MAX:
                raise ModelError(f"timeline entry {i + 1}: label is required, at most {SOURCE_LABEL_MAX} characters")
            if not isinstance(groups, list) or not groups:
                raise ModelError(f"timeline '{label}': groups must be a non-empty list")
            unknown = [g for g in groups if g not in self.groups]
            if unknown:
                raise ModelError(f"timeline '{label}': group(s) {unknown} are not listed under `groups`")

        seen_short: dict[str, str] = {}
        for nid, node in self.nodes.items():
            if not node.short_name:
                raise ModelError(f"{node.kind} {nid}: 'short_name' is required")
            if len(node.short_name) > SHORT_NAME_MAX:
                raise ModelError(f"{node.kind} {nid}: short_name '{node.short_name}' has "
                                 f"{len(node.short_name)} characters, at most {SHORT_NAME_MAX} allowed")
            if node.short_name in seen_short:
                raise ModelError(f"{node.kind} {nid}: short_name '{node.short_name}' is already "
                                 f"used by '{seen_short[node.short_name]}'")
            seen_short[node.short_name] = nid

        for link in self.links:
            where = f"link {link.label}"
            if link.src not in self.nodes:
                raise ModelError(f"{where}: unknown predecessor '{link.src}'")
            if link.dst not in self.nodes:
                raise ModelError(f"{where}: unknown successor '{link.dst}'")
            if link.rel not in RELATIONS:
                raise ModelError(f"{where}: relation must be one of {RELATIONS}")
            if link.type not in LINK_TYPES:
                raise ModelError(f"{where}: type must be one of {LINK_TYPES}")
            if self.nodes[link.dst].kind == "external":
                raise ModelError(f"{where}: external inputs cannot have predecessors")
            if link.relax is not None:
                if link.type in HARD_LINK_TYPES:
                    raise ModelError(f"{where}: a {link.type} link cannot be relaxed")
                for key in ("proposal", "cost"):
                    if not str(link.relax.get(key, "")).strip():
                        raise ModelError(f"{where}: relax needs a '{key}' "
                                         "(the change as said on site, and what breaking the link costs)")
                relax_pred = link.relax.get("pred", link.src)
                if relax_pred not in self.nodes:
                    raise ModelError(f"{where}: relax predecessor '{relax_pred}' is unknown")
                if link.relax.get("rel", link.rel) not in RELATIONS:
                    raise ModelError(f"{where}: relax relation must be one of {RELATIONS}")

        incoming = {nid: [] for nid in self.nodes}
        outgoing = {nid: [] for nid in self.nodes}
        for link in self.links:
            incoming[link.dst].append(link.idx)
            outgoing[link.src].append(link.idx)

        # A relaxed link may point from a different predecessor. Include those
        # alternative edges in the ordering so any scenario stays acyclic.
        extra_edges = [(l.relax["pred"], l.dst) for l in self.links
                       if l.relax is not None and "pred" in l.relax]

        indegree = {nid: 0 for nid in self.nodes}
        adjacency: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for link in self.links:
            adjacency[link.src].append(link.dst)
            indegree[link.dst] += 1
        for src, dst in extra_edges:
            adjacency[src].append(dst)
            indegree[dst] += 1

        queue = deque(sorted(nid for nid, deg in indegree.items() if deg == 0))
        order: list[str] = []
        while queue:
            nid = queue.popleft()
            order.append(nid)
            for succ in adjacency[nid]:
                indegree[succ] -= 1
                if indegree[succ] == 0:
                    queue.append(succ)
        if len(order) != len(self.nodes):
            stuck = sorted(nid for nid, deg in indegree.items() if deg > 0)
            raise ModelError(f"The network has a loop involving: {', '.join(stuck[:8])}")

        self.order = order
        self.index = {nid: i for i, nid in enumerate(order)}
        self.incoming = incoming
        self.outgoing = outgoing
        self._resolve_risks()
        self._resolve_sources()

        # Nodes that cannot reach the milestone do not affect it; report them.
        upstream = self.upstream_of(self.milestone)
        orphans = sorted(set(self.nodes) - upstream)
        if orphans:
            logger.warning("Nodes that do not feed the milestone: %s", ", ".join(orphans))
        return self

    def _resolve_risks(self) -> None:
        """Validate every common risk and list the items it affects (after the rule pack ran)."""
        seen_ids: set[str] = set()
        seen_short: set[str] = set()
        for risk in self.risks:
            where = f"risk {risk.id}"
            if risk.id in seen_ids:
                raise ModelError(f"Duplicate risk id '{risk.id}'")
            seen_ids.add(risk.id)
            if not risk.short_name or len(risk.short_name) > SHORT_NAME_MAX:
                raise ModelError(f"{where}: short_name is required, at most {SHORT_NAME_MAX} characters")
            if risk.short_name in seen_short:
                raise ModelError(f"{where}: short_name '{risk.short_name}' is already used by another risk")
            seen_short.add(risk.short_name)
            if not 0 < risk.probability <= 1:
                raise ModelError(f"{where}: probability must be in (0, 1]")
            if risk.effect not in RISK_EFFECTS:
                raise ModelError(f"{where}: effect must be one of {RISK_EFFECTS}")
            dist.validate(risk.impact, f"{where} impact")
            if risk.effect == "factor" and not _dist_always_positive(risk.impact):
                raise ModelError(f"{where}: a duration factor must be greater than 0")

            sel = risk.applies_to or {}
            if not sel:
                raise ModelError(f"{where}: applies_to needs at least one selector {RISK_SELECTORS}")
            self._check_selectors(where, sel)
            targets = [nid for nid in self.order
                       if nid != self.milestone and self._matches(nid, sel)]
            if not targets:
                raise ModelError(f"{where}: applies_to matches no item")
            externals = [nid for nid in targets if self.nodes[nid].kind == "external"]
            if risk.effect == "factor" and externals:
                raise ModelError(f"{where}: a factor multiplies activity durations and cannot apply to "
                                 f"external inputs ({', '.join(externals)}); use effect: days")
            risk.targets = targets

    def _check_selectors(self, where: str, sel: dict) -> None:
        for key, values in sel.items():
            if key not in RISK_SELECTORS:
                raise ModelError(f"{where}: unknown selector '{key}', expected one of {RISK_SELECTORS}")
            if not isinstance(values, list) or not values:
                raise ModelError(f"{where}: selector '{key}' must be a non-empty list")
        unknown = [nid for nid in sel.get("ids", []) if nid not in self.nodes]
        if unknown:
            raise ModelError(f"{where}: unknown item id(s) {', '.join(unknown)}")

    def _matches(self, nid: str, sel: dict) -> bool:
        """True when the item matches EVERY selector (its value is in the selector's list)."""
        node = self.nodes[nid]
        return all(getattr(node, _SELECTOR_ATTR[k]) in v for k, v in sel.items())

    def _resolve_sources(self) -> None:
        """Assign every item to the first delay source it matches (plant file `delay_sources`)."""
        if not self.delay_sources:
            return
        seen: set[str] = set()
        for src in self.delay_sources:
            where = f"delay source {src.key}"
            if src.key in seen:
                raise ModelError(f"Duplicate delay source '{src.key}'")
            seen.add(src.key)
            if not src.label or len(src.label) > SOURCE_LABEL_MAX:
                raise ModelError(f"{where}: label is required, at most {SOURCE_LABEL_MAX} characters")
            if not src.what.strip():
                raise ModelError(f"{where}: 'what' (one sentence for the reader) is required")
            self._check_selectors(where, src.applies_to or {})
            src.members = []
        for nid in self.order:
            src = next((s for s in self.delay_sources if self._matches(nid, s.applies_to or {})), None)
            if src is None:
                node = self.nodes[nid]
                raise ModelError(f"{node.kind} {nid} (group '{node.group}', condition '{node.condition}') "
                                 "belongs to no delay source; add a source without selectors last")
            src.members.append(nid)

    def source_of(self, nid: str) -> str | None:
        """Key of the delay source an item belongs to, or None when the plant defines none."""
        return next((s.key for s in self.delay_sources if nid in s.members), None)

    def upstream_of(self, target: str) -> set[str]:
        """All nodes with a path to `target` (including target)."""
        seen = {target}
        stack = [target]
        while stack:
            nid = stack.pop()
            for li in self.incoming.get(nid, []):
                src = self.links[li].src
                if src not in seen:
                    seen.add(src)
                    stack.append(src)
        return seen

    def relaxable_links(self) -> list[Link]:
        return [l for l in self.links if l.relax is not None]


# ---------------------------------------------------------------------- loading
def _read_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ModelError(f"File not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ModelError(f"Could not parse YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelError(f"{path} must contain a mapping at the top level")
    return data


def _dist_always_positive(spec: dict) -> bool:
    """True when every value the (validated) distribution can take is > 0."""
    kind = spec["dist"]
    if kind == "triangular":
        return float(spec["min"]) > 0
    if kind == "fixed":
        return float(spec["value"]) > 0
    return kind == "lognormal"


def _risk_from_raw(raw: dict) -> Risk:
    rid = raw.get("id")
    if not rid:
        raise ModelError(f"Risk without id: {raw}")
    for key in ("probability", "effect", "impact", "applies_to"):
        if key not in raw:
            raise ModelError(f"risk {rid}: '{key}' is required")
    source = raw.get("source", {}) or {}
    try:
        probability = float(raw["probability"])
    except (TypeError, ValueError) as exc:
        raise ModelError(f"risk {rid}: probability must be a number") from exc
    return Risk(id=rid, name=raw.get("name", rid), short_name=str(raw.get("short_name", "")),
                probability=probability, effect=str(raw["effect"]),
                impact=dict(raw["impact"] or {}), applies_to=dict(raw["applies_to"] or {}),
                source_grade=str(source.get("grade", "C")), source_note=source.get("note", ""))


def _node_from_activity(raw: dict) -> Node:
    nid = raw.get("id")
    if not nid:
        raise ModelError(f"Activity without id: {raw}")
    dist.validate(raw.get("duration"), f"activity {nid}")
    weather = raw.get("weather", "none")
    if weather not in WEATHER_KINDS:
        raise ModelError(f"activity {nid}: weather must be one of {WEATHER_KINDS}")
    condition = raw.get("condition", "productivity")
    if condition not in CONDITIONS:
        raise ModelError(f"activity {nid}: condition must be one of {CONDITIONS}")
    source = raw.get("source", {}) or {}
    return Node(
        id=nid, name=raw.get("name", nid), group=raw.get("group", "Other"),
        kind="activity", short_name=str(raw.get("short_name", "")),
        condition=condition, weather=weather,
        duration=dict(raw["duration"]),
        earliest_day=float(raw.get("earliest_day", 0)),
        site_start=bool(raw.get("site_start", False)),
        source_grade=str(source.get("grade", "C")), source_note=source.get("note", ""),
        adjustable=bool(raw.get("adjustable", False)),
    )


def _node_from_external(raw: dict) -> Node:
    nid = raw.get("id")
    if not nid:
        raise ModelError(f"External input without id: {raw}")
    if "planned_day" not in raw:
        raise ModelError(f"external {nid}: 'planned_day' is required")
    dist.validate(raw.get("delay"), f"external {nid}")
    condition = raw.get("condition", "supply")
    if condition not in EXTERNAL_CONDITIONS:
        raise ModelError(f"external {nid}: condition must be one of {EXTERNAL_CONDITIONS}")
    source = raw.get("source", {}) or {}
    return Node(
        id=nid, name=raw.get("name", nid), group=raw.get("group", "External inputs"),
        kind="external", short_name=str(raw.get("short_name", "")), condition=condition,
        planned_day=float(raw["planned_day"]), delay=dict(raw["delay"]),
        source_grade=str(source.get("grade", "C")), source_note=source.get("note", ""),
        adjustable=bool(raw.get("adjustable", False)), site_start=bool(raw.get("site_start", False)),
    )


def _source_from_raw(raw: dict) -> DelaySource:
    key = raw.get("key")
    if not key:
        raise ModelError(f"Delay source without key: {raw}")
    return DelaySource(key=str(key), label=str(raw.get("label", "")), what=str(raw.get("what", "")),
                       applies_to=dict(raw.get("applies_to") or {}), action=str(raw.get("action", "")))


def load_model(plant_path: str | Path, rules_path: str | Path | None, with_risks: bool = True) -> Model:
    """
    Read the plant file, apply the rule pack, validate, and return a compiled Model.
    with_risks=False leaves out the plant's common risks (independent durations).
    """
    from . import rules as rules_mod  # local import avoids a circular dependency

    plant = _read_yaml(Path(plant_path))
    meta = plant.get("meta", {}) or {}
    milestone = meta.get("milestone")
    if not milestone:
        raise ModelError("meta.milestone is required in the plant file")

    model = Model(meta=meta, nodes={}, links=[], milestone=milestone,
                  groups=[str(g) for g in plant.get("groups", []) or []],
                  timeline=[dict(t) for t in plant.get("timeline", []) or []])

    for raw in plant.get("externals", []) or []:
        model.add_node(_node_from_external(raw))
    for raw in plant.get("activities", []) or []:
        model.add_node(_node_from_activity(raw))
    for raw in plant.get("links", []) or []:
        try:
            model.add_link(raw["from"], raw["to"], raw.get("rel", "FS"), raw.get("lag", 0),
                           raw.get("type", "physical"), raw.get("why", ""), raw.get("relax"))
        except KeyError as exc:
            raise ModelError(f"Link is missing field {exc}: {raw}") from exc

    if rules_path is not None:
        pack = _read_yaml(Path(rules_path))
        rules_mod.apply_rule_pack(model, plant.get("assets", []) or [], pack)

    if with_risks:
        model.risks = [_risk_from_raw(raw) for raw in plant.get("risks", []) or []]
    model.delay_sources = [_source_from_raw(raw) for raw in plant.get("delay_sources", []) or []]
    return model.compile()
