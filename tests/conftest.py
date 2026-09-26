"""Shared fixtures: the reference plant, the illustrative weather table, and small banks."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from locus.model import load_model  # noqa: E402
from locus.simulate import RandomBank  # noqa: E402
from locus.weather import (daily_persistence, daily_probabilities,  # noqa: E402
                           load_weather_table)

CONFIG = ROOT / "config"
START = date(2027, 1, 4)


@pytest.fixture(scope="session")
def model():
    return load_model(CONFIG / "reference_plant.yaml", CONFIG / "rules_taiwan.yaml")


@pytest.fixture(scope="session")
def table():
    return load_weather_table(ROOT / "tests" / "fixtures" / "weather_synthetic.yaml")


@pytest.fixture(scope="session")
def cwa_table():
    """The weather table the app ships, built from CWA CODiS records."""
    paths = sorted(CONFIG.glob("weather_*.yaml"))
    assert len(paths) == 1, f"expected exactly one weather table in config/, found {paths}"
    return load_weather_table(paths[0])


@pytest.fixture(scope="session")
def station(table):
    return next(iter(table["stations"]))


@pytest.fixture(scope="session")
def make_bank(model, table, station):
    """Factory: a prepared bank for (n_iter, seed, horizon, spells)."""
    cache = {}

    def make(n_iter=300, seed=5, horizon=1410, spells=True, mdl=None):
        key = (n_iter, seed, horizon, spells, id(mdl))
        if key not in cache:
            bank = RandomBank(mdl or model, n_iter, seed, horizon=horizon)
            daily = daily_probabilities(table, station, START, horizon)
            persist = daily_persistence(table, station, START, horizon) if spells else None
            bank.prepare_weather(daily, persist)
            cache[key] = bank
        return cache[key]

    return make


def row_cum(bank, kind):
    """Plain (n_iter, horizon) cumulative workable-day counts, without row offsets."""
    N, H = bank.n_iter, bank.horizon
    flat = bank.weather_arrays(kind).astype(np.int64)
    return flat.reshape(N, H) - (np.arange(N, dtype=np.int64) * (H + 1))[:, None]
