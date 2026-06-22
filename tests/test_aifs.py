"""Unit tests for the pure logic in weather_markets.aifs.

The Herbie/DB integration is validated by a live smoke run during backfill;
here we pin the two correctness-critical pure helpers: Kelvin->Fahrenheit row
construction (with the right model string / member ids / columns) and the
longitude-convention normalization (AIFS is -180..180, but the helper must also
handle a 0..360 grid so a station's negative longitude never lands in the wrong
hemisphere).
"""
from datetime import datetime, timezone

import numpy as np
import xarray as xr

from weather_markets.aifs import build_rows, lon_for_grid, _extract_member_temps_k


RUN = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc)
VALID = datetime(2026, 6, 18, 18, 0, tzinfo=timezone.utc)


def test_build_rows_converts_kelvin_to_fahrenheit():
    # 294.261111 K == 70.0 F exactly
    rows = build_rows(RUN, VALID, "KORD", "aifs", [(0, 294.26111111)])
    assert len(rows) == 1
    assert rows[0]["tmax_f"] == _approx(70.0)
    assert rows[0]["temperature_f"] == _approx(70.0)


def test_build_rows_sets_both_temperature_and_tmax():
    # AIFS has no native max var: the instantaneous 2t sample is stored in BOTH
    # columns (mirrors hrrr.py) so aggregation's MAX(tmax_f) derives the daily high.
    rows = build_rows(RUN, VALID, "KORD", "aifs", [(0, 300.0)])
    assert rows[0]["temperature_f"] == rows[0]["tmax_f"]
    assert rows[0]["temperature_f"] is not None


def test_build_rows_single_uses_member_zero():
    rows = build_rows(RUN, VALID, "KSEA", "aifs", [(0, 290.0)])
    assert [r["member_id"] for r in rows] == [0]
    assert all(r["model"] == "aifs" for r in rows)


def test_build_rows_ensemble_preserves_member_ids():
    members = [(n, 290.0 + n) for n in range(1, 51)]  # 50 perturbed members
    rows = build_rows(RUN, VALID, "KSEA", "aifs_ens", members)
    assert [r["member_id"] for r in rows] == list(range(1, 51))
    assert all(r["model"] == "aifs_ens" for r in rows)
    assert all(r["init_time"] == RUN and r["valid_time"] == VALID for r in rows)


def test_lon_for_grid_negative_grid_passthrough():
    # AIFS native grid: -180..179.75 -> station's negative longitude unchanged.
    assert lon_for_grid(-180.0, 179.75, -87.93) == _approx(-87.93)


def test_lon_for_grid_360_grid_wraps():
    # A 0..360 grid (e.g. GEFS convention) must wrap a western longitude.
    assert lon_for_grid(0.0, 359.75, -87.93) == _approx(272.07)


def _grid(lats, lons, values, members=None):
    """Build a tiny t2m Dataset. values indexed [lat,lon] (det) or [member,lat,lon]."""
    if members is None:
        da = xr.DataArray(np.asarray(values, float), dims=["latitude", "longitude"],
                          coords={"latitude": lats, "longitude": lons}, name="t2m")
    else:
        da = xr.DataArray(np.asarray(values, float), dims=["number", "latitude", "longitude"],
                          coords={"number": members, "latitude": lats, "longitude": lons}, name="t2m")
    return da.to_dataset()


def test_extract_deterministic_picks_nearest_single_value():
    lats = [40.0, 42.0, 44.0]
    lons = [-90.0, -88.0, -86.0]
    vals = [[i * 10 + j for j in range(3)] for i in range(3)]  # [lat][lon]
    ds = _grid(lats, lons, vals)
    out = _extract_member_temps_k(ds, "t2m", 42.1, -88.1)  # nearest -> (42,-88) = vals[1][1]=11
    assert out == [(0, _approx(11.0))]


def test_extract_ensemble_vectorized_aligns_members_and_values():
    lats = [40.0, 42.0, 44.0]
    lons = [-90.0, -88.0, -86.0]
    members = [1, 2, 3]
    # member m has value (290 + m) at the (42,-88) cell, distinct elsewhere
    data = np.zeros((3, 3, 3))
    for mi, m in enumerate(members):
        data[mi, 1, 1] = 290.0 + m
    ds = _grid(lats, lons, data, members=members)
    out = _extract_member_temps_k(ds, "t2m", 42.0, -88.0)
    assert out == [(1, _approx(291.0)), (2, _approx(292.0)), (3, _approx(293.0))]


def _approx(x, tol=1e-6):
    class _A:
        def __eq__(self, other):
            return abs(other - x) < tol
        def __repr__(self):
            return f"~{x}"
    return _A()
