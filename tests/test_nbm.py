"""Unit tests for the pure helpers in weather_markets.nbm.

Network/DB ingest is covered by the smoke + backfill runs (mocking Herbie would
test the mock, not the code) — these tests pin only the pure logic: the K->F
conversion, the projected-grid nearest-neighbour, the Gaussian pseudo-member
encoding (which MUST reconstruct NBM's calibrated mean+std under the harness's
mean/stdev pooling), and the QMD percentile-string parser.
"""
import statistics

import numpy as np
import pytest

from weather_markets.nbm import (
    kelvin_to_fahrenheit,
    nearest_yx,
    gaussian_pseudo_members,
    parse_percentile_level,
)


def test_kelvin_to_fahrenheit_freezing():
    assert kelvin_to_fahrenheit(273.15) == pytest.approx(32.0)


def test_kelvin_to_fahrenheit_warm():
    assert kelvin_to_fahrenheit(300.0) == pytest.approx(80.33, abs=0.01)


def test_gaussian_pseudo_members_reconstructs_mean_and_std():
    """{mu-σ, mu, mu+σ} has sample mean == mu and sample stdev == σ exactly,
    which is what the harness's mean_std() pooling reads back."""
    members = gaussian_pseudo_members(85.0, 2.0)
    by_id = dict(members)
    assert set(by_id) == {0, 1, 2}
    assert by_id[0] == pytest.approx(85.0)  # mean lives at member_id 0
    vals = [v for _id, v in members]
    assert statistics.mean(vals) == pytest.approx(85.0)
    assert statistics.stdev(vals) == pytest.approx(2.0)


def test_gaussian_pseudo_members_zero_sigma():
    members = gaussian_pseudo_members(70.0, 0.0)
    assert len(members) == 3
    assert {mid for mid, _ in members} == {0, 1, 2}
    assert all(v == pytest.approx(70.0) for _id, v in members)


def test_parse_percentile_level_extracts_integer():
    assert parse_percentile_level(":TMAX:2 m above ground:12-24 hour max fcst:50% level:") == 50
    assert parse_percentile_level(":TMAX:2 m above ground:12-24 hour max fcst:5% level:") == 5
    assert parse_percentile_level(":TMAX:2 m above ground:12-24 hour max fcst:100% level:") == 100


def test_parse_percentile_level_none_when_absent():
    # plain mean field (no percentile)
    assert parse_percentile_level(":TMAX:2 m above ground:12-24 hour max fcst:") is None
    # probability-threshold field is NOT a percentile level
    assert parse_percentile_level(":APTMP:2 m above ground:24 hour fcst:prob >305:") is None


def test_nearest_yx_picks_closest_cell():
    # 3x3 synthetic lat/lon grid (already -180..180)
    lat2d = np.array([[40.0, 40.0, 40.0],
                      [41.0, 41.0, 41.0],
                      [42.0, 42.0, 42.0]])
    lon2d = np.array([[-89.0, -88.0, -87.0],
                      [-89.0, -88.0, -87.0],
                      [-89.0, -88.0, -87.0]])
    # KORD-ish (41.99, -87.93) -> nearest is row 2 (lat 42), col 0 (lon -89)? no:
    # lon -87.93 closest to -88 (col 1); lat 41.99 closest to 42 (row 2)
    yi, xi = nearest_yx(lat2d, lon2d, 41.99, -87.93)
    assert (yi, xi) == (2, 1)


def test_nearest_yx_normalizes_0_360_longitude():
    lat2d = np.array([[40.0, 41.0]])
    lon2d = np.array([[271.0, 272.07]])  # 0-360 form of -89.0, -87.93
    yi, xi = nearest_yx(lat2d, lon2d, 41.0, -87.93)
    assert (yi, xi) == (0, 1)
