"""
Duration distributions sampled by inverse CDF.

Why inverse CDF instead of rng.triangular(...)?
    Every scenario (baseline, "break this link", "start piling later") must see
    the SAME underlying randomness, so that differences between scenarios come
    from the logic change and not from sampling noise. This is the classic
    variance-reduction technique called Common Random Numbers (CRN).
    We draw one uniform U ~ Uniform(0, 1) per node per iteration once, and map it
    through each distribution's inverse CDF: x = F^-1(U).
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
from scipy.special import ndtri  # inverse of the standard normal CDF

# z-score of the 90th percentile of the standard normal distribution
_Z90 = 1.2815515655446004

SUPPORTED = ("triangular", "lognormal", "fixed")


class DistributionError(ValueError):
    """Raised when a distribution specification is invalid."""


def validate(spec: Mapping[str, Any], where: str) -> None:
    """Check a distribution spec early, with a message that points to the source."""
    if not isinstance(spec, Mapping) or "dist" not in spec:
        raise DistributionError(f"{where}: distribution must be a mapping with a 'dist' key")
    kind = spec["dist"]
    if kind not in SUPPORTED:
        raise DistributionError(f"{where}: unsupported dist '{kind}', expected one of {SUPPORTED}")
    if kind == "triangular":
        for key in ("min", "mode", "max"):
            if key not in spec:
                raise DistributionError(f"{where}: triangular needs '{key}'")
        a, m, b = float(spec["min"]), float(spec["mode"]), float(spec["max"])
        if not (a <= m <= b) or a == b:
            raise DistributionError(f"{where}: triangular needs min <= mode <= max and min < max")
        if a < 0:
            raise DistributionError(f"{where}: durations cannot be negative")
    elif kind == "lognormal":
        for key in ("median", "p90"):
            if key not in spec:
                raise DistributionError(f"{where}: lognormal needs '{key}'")
        med, p90 = float(spec["median"]), float(spec["p90"])
        if med <= 0 or p90 <= med:
            raise DistributionError(f"{where}: lognormal needs 0 < median < p90")
    elif kind == "fixed":
        if "value" not in spec or float(spec["value"]) < 0:
            raise DistributionError(f"{where}: fixed needs a non-negative 'value'")


def sample(spec: Mapping[str, Any], u: np.ndarray) -> np.ndarray:
    """
    Map uniforms u in (0, 1) to samples of the distribution.

    Triangular(a, m, b), with c = (m - a) / (b - a):
        x = a + sqrt(u (b - a)(m - a))            if u < c
        x = b - sqrt((1 - u)(b - a)(b - m))       otherwise

    Lognormal parameterised by median and P90 (easier to elicit from people
    than mu and sigma):
        median = exp(mu)                  -> mu = ln(median)
        P90    = exp(mu + 1.2816 sigma)   -> sigma = (ln(P90) - mu) / 1.2816
        x = exp(mu + sigma * Phi^-1(u))
    The lognormal has a long right tail, which fits review and inspection
    waiting times: most finish near the median, a few drag on much longer.
    """
    kind = spec["dist"]
    if kind == "fixed":
        return np.full(u.shape, float(spec["value"]))

    if kind == "triangular":
        a, m, b = float(spec["min"]), float(spec["mode"]), float(spec["max"])
        c = (m - a) / (b - a)
        left = a + np.sqrt(u * (b - a) * (m - a))
        right = b - np.sqrt((1.0 - u) * (b - a) * (b - m))
        return np.where(u < c, left, right)

    if kind == "lognormal":
        mu = math.log(float(spec["median"]))
        sigma = (math.log(float(spec["p90"])) - mu) / _Z90
        # Clip u away from 0 and 1 so ndtri never returns +/- infinity
        u_safe = np.clip(u, 1e-9, 1.0 - 1e-9)
        return np.exp(mu + sigma * ndtri(u_safe))

    raise DistributionError(f"Unsupported dist '{kind}'")


def typical_value(spec: Mapping[str, Any]) -> float:
    """
    Single-point value used for the deterministic 'P6-style' plan:
    the mode of a triangular, the median of a lognormal, or the fixed value.
    """
    kind = spec["dist"]
    if kind == "triangular":
        return float(spec["mode"])
    if kind == "lognormal":
        return float(spec["median"])
    if kind == "fixed":
        return float(spec["value"])
    raise DistributionError(f"Unsupported dist '{kind}'")
