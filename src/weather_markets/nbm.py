"""NBM (NOAA National Blend of Models) daily-HIGH forecast ingestion.

NBM is NOAA/MDL's calibrated, statistically-downscaled 2.5 km CONUS blend. Unlike
GEFS/IFS (raw ensemble members), NBM ships an ALREADY-CALIBRATED predictive
distribution for daily-Tmax:
  * core (Herbie model="nbm",    product="co"): calibrated TMAX mean + ens std dev.
  * QMD  (Herbie model="nbmqmd", product="co"): 21 TMAX percentiles (0,5,...,100 %).
Both fetched from AWS (deep archive, back past 2024-06; see the P0-A probe report).

STORAGE ENCODING — additive to `forecasts`, NO schema change.
The table has columns (init_time, valid_time, station_id, model, member_id,
temperature_f, tmax_f) and no std/spread column, so NBM's calibrated distribution
is encoded as pseudo-members in tmax_f, namespaced by `model`, which the daily-high
MAX path (aggregation.compute_daily_highs) and the skill harness
(forecast_model_skill.fetch_member_highs) pool EXACTLY like real members:

  model='nbm'      3 Gaussian pseudo-members per window (the SCORED representation):
                     member_id 0 -> mu        (the calibrated mean)
                     member_id 1 -> mu + sigma
                     member_id 2 -> mu - sigma
                   {mu-σ, mu, mu+σ} has sample mean == mu and sample stdev == sigma,
                   so the harness's mean/stdev EMOS recovers NBM's calibrated
                   location AND spread. (member_id 0 IS the mean, per the task spec.)

  model='nbm_qmd'  21 percentile pseudo-members per window (stored for the deferred
                     EMOS-covariate bake-off; not in the scored combined_nbm config):
                     member_id = percentile level (0,5,10,...,100)
                     tmax_f     = that percentile's calibrated TMAX (°F)
                   i.e. the calibrated predictive CDF as an empirical sample.

DAILY-Tmax WINDOWING (the P0-A gotcha). NBM TMAX is a windowed max referenced to
the 00Z init (e.g. ":TMAX:2 m above ground:12-24 hour max fcst:"), NOT a local
calendar day. We store each window with valid_time = init + fxx (the window END),
exactly as GEFS/IFS store their short windowed maxes, and let the existing
local-day-D filter + MAX select the window(s) landing on local day D. NBM core
publishes the same-day windowed TMAX as a SINGLE "12-24 hour max fcst" message at
fxx=24 (fxx 12/18/30 carry none — confirmed empirically). For a 00Z day-D init that
window (valid 00Z day-D+1) maps to the evening of local day D for every US station,
and its 12-24Z period contains each station's afternoon high — so fxx=24 alone IS
the day-D daily high; the existing local-day MAX path needs no NBM-specific logic.

NBM is a PROJECTED 2.5 km Lambert-Conformal CONUS grid (~1597×2345), so station
extraction is nearest-neighbour on the 2-D lat/lon arrays (like HRRR), NOT .sel().

CAVEAT (read before trusting the pooled number): NBM is ALREADY calibrated, so
pooling it and re-fitting rolling-EMOS double-calibrates. combined_nbm is a rough
DIRECTIONAL read; NBM's proper test is as an EMOS covariate (deferred).

Writes ADDITIVE rows to `forecasts` only — no EMOS/blend/aggregation-caller/trading
code is touched.
"""
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone

import numpy as np

# NBM core publishes the same-day windowed TMAX as a SINGLE "12-24 hour max fcst"
# message at fxx=24 (confirmed empirically; fxx 12/18/30 carry no TMAX-2m window).
# Its 12-24Z period contains every US station's local afternoon peak and its end
# time (valid 00Z day-D+1) lands on local day D for all US tz, so fxx=24 alone IS
# the day-D daily high.
DEFAULT_FORECAST_HOURS = [24]

# Herbie idx selectors (wgrib2 style). The windowed-max TMAX message family:
#   mean : ':TMAX:2 m above ground:12-24 hour max fcst:'
#   std  : ':TMAX:2 m above ground:12-24 hour max fcst:ens std dev:'
#   pctl : ':TMAX:2 m above ground:12-24 hour max fcst:50% level:'
TMAX_MEAN_SEARCH = r":TMAX:2 m above ground:\d+-\d+ hour max fcst:$"
TMAX_STD_SEARCH = r":TMAX:2 m above ground:\d+-\d+ hour max fcst:ens std dev:"
TMAX_PCT_SEARCH = r":TMAX:2 m above ground:\d+-\d+ hour max fcst:\d+% level:"

_PCT_RE = re.compile(r":(\d{1,3})% level:")


def kelvin_to_fahrenheit(kelvin: float) -> float:
    """Convert an absolute temperature (K) to °F."""
    return (kelvin - 273.15) * 9 / 5 + 32


def kelvin_delta_to_fahrenheit(delta_k: float) -> float:
    """Convert a temperature *difference* (e.g. a std dev), K -> °F: scale only."""
    return float(delta_k) * 9 / 5


def nearest_yx(lat2d, lon2d, target_lat: float, target_lon: float) -> tuple[int, int]:
    """(y, x) index of the grid cell nearest (target_lat, target_lon).

    NBM uses a 2-D Lambert grid; xarray .sel() doesn't work, so use squared-degree
    distance on the 2-D arrays (sub-cell accuracy is fine at 2.5 km). Mirrors
    hrrr._nearest_yx (kept standalone — no shared base class, per project style).
    """
    lat2d = np.asarray(lat2d, dtype=float)
    lon2d = np.asarray(lon2d, dtype=float)
    if lon2d.max() > 180:  # normalize 0-360 -> -180..180
        lon2d = np.where(lon2d > 180, lon2d - 360, lon2d)
    dist_sq = (lat2d - target_lat) ** 2 + (lon2d - target_lon) ** 2
    yi, xi = np.unravel_index(int(np.argmin(dist_sq)), dist_sq.shape)
    return int(yi), int(xi)


def gaussian_pseudo_members(mu: float, sigma: float) -> list[tuple[int, float]]:
    """Encode a calibrated Gaussian N(mu, sigma) as 3 pseudo-members.

    Returns [(0, mu), (1, mu+sigma), (2, mu-sigma)]. The set {mu-σ, mu, mu+σ} has
    sample mean mu and sample stdev sigma exactly, so the harness's mean/stdev
    pooling reads NBM's calibrated location and spread straight back. member_id 0
    is the mean.
    """
    sigma = abs(float(sigma))
    mu = float(mu)
    return [(0, mu), (1, mu + sigma), (2, mu - sigma)]


def parse_percentile_level(search_this: str) -> int | None:
    """Extract the integer percentile from an NBM-QMD idx line, else None.

    ':TMAX:...:50% level:' -> 50 ; ':TMAX:...max fcst:' -> None ;
    ':APTMP:...:prob >305:' -> None (a probability threshold, not a percentile).
    """
    m = _PCT_RE.search(search_this or "")
    return int(m.group(1)) if m else None


# ── ingest ──────────────────────────────────────────────────────────────────
# NBM-QMD ships only INSTANTANEOUS 2 m TMP percentiles (':TMP:...:NN% level:'),
# NOT windowed-max-Tmax percentiles, and cfgrib silently collapses the 21
# messages into one (no percentile dim), so QMD needs per-percentile extraction.
# QMD is therefore OFF by default in the backfill (it is the wrong shape for a
# clean daily-max CDF and only feeds the deferred EMOS-covariate test); core's
# native calibrated windowed TMAX (mean+std) is the daily-Tmax representation.
PERCENTILES = list(range(0, 101, 5))            # 0,5,...,100  (21 levels)
DEFAULT_SAVE_DIR = os.path.expanduser("~/data/_p1_nbm")

# Herbie's own templates label these models 'nbm' (core) and 'nbmqmd' (QMD).
_CORE_MODEL, _QMD_MODEL = "nbm", "nbmqmd"

_INSERT_SQL = """
    INSERT INTO forecasts (init_time, valid_time, station_id, model, member_id, temperature_f, tmax_f)
    VALUES (%(init_time)s, %(valid_time)s, %(station_id)s, %(model)s, %(member_id)s, %(temperature_f)s, %(tmax_f)s)
    ON CONFLICT (init_time, valid_time, station_id, model, member_id) DO NOTHING
"""


def _nearest_value(ds, station, cached_yx):
    """Nearest-cell scalar from a single-message NBM dataset (2-D Lambert grid)."""
    var = list(ds.data_vars)[0]
    if cached_yx is None:
        cached_yx = nearest_yx(ds.latitude.values, ds.longitude.values,
                               station.latitude, station.longitude)
    yi, xi = cached_yx
    return float(np.asarray(ds[var].values)[yi, xi]), cached_yx


def _xr_one(H, search):
    """xarray for a search expected to match ONE message; remove_grib=True so
    Herbie deletes the GRIB right after loading (keeps the box's disk/RAM bounded).
    Returns the dataset or None."""
    ds = H.xarray(search, remove_grib=True)
    if isinstance(ds, list):
        ds = ds[0] if ds else None
    return ds


def ingest_nbm_run(
    run_time: datetime,
    station_id: str = "KNYC",
    forecast_hours: list[int] | None = None,
    save_dir: str | None = None,
    include_qmd: bool = False,
) -> dict:
    """Ingest one 00Z NBM run for one station (core always; QMD opt-in).

    Writes additive rows to `forecasts`:
      model='nbm'      -> 3 Gaussian pseudo-members per windowed-TMAX message
                          (member_id 0=mu, 1=mu+σ, 2=mu-σ; tmax_f in °F).
      model='nbm_qmd'  -> (only if include_qmd) instantaneous-TMP percentile
                          pseudo-members (member_id=percentile; tmax_f in °F).
                          NB: instantaneous, not windowed-max — see module docstring.

    valid_time = init + fxx (window END), so the existing local-day-D MAX path
    selects the windows that land on day D. Returns a summary dict.
    """
    if forecast_hours is None:
        forecast_hours = DEFAULT_FORECAST_HOURS
    if save_dir is None:
        save_dir = DEFAULT_SAVE_DIR
    from herbie import Herbie  # local import: keeps module import cheap for unit tests
    from .db import get_connection
    from .stations import get as get_station

    station = get_station(station_id)
    run_naive = run_time.replace(tzinfo=None) if run_time.tzinfo else run_time
    init_utc = run_time if run_time.tzinfo else run_time.replace(tzinfo=timezone.utc)

    rows: list[dict] = []
    yx_core = yx_qmd = None
    n_core_windows = 0
    n_qmd_windows = 0

    for fxx in forecast_hours:
        valid_time = init_utc + timedelta(hours=fxx)

        # ---- CORE: calibrated windowed-TMAX mean + ens std dev ----
        try:
            Hc = Herbie(run_naive, model=_CORE_MODEL, product="co", fxx=fxx,
                        priority=["aws", "nomads"], save_dir=save_dir, verbose=False)
            ds_mu = _xr_one(Hc, TMAX_MEAN_SEARCH)
            if ds_mu is not None:
                mu_k, yx_core = _nearest_value(ds_mu, station, yx_core)
                mu_f = kelvin_to_fahrenheit(mu_k)
                sigma_f = 0.0
                ds_sd = _xr_one(Hc, TMAX_STD_SEARCH)
                if ds_sd is not None:
                    sd_k, yx_core = _nearest_value(ds_sd, station, yx_core)
                    sigma_f = kelvin_delta_to_fahrenheit(sd_k)
                for mid, val in gaussian_pseudo_members(mu_f, sigma_f):
                    rows.append({"init_time": init_utc, "valid_time": valid_time,
                                 "station_id": station_id, "model": "nbm",
                                 "member_id": mid, "temperature_f": None, "tmax_f": val})
                n_core_windows += 1
                print(f"  fxx={fxx:3d}h core: mu={mu_f:.2f}°F sigma={sigma_f:.2f}°F")
            else:
                print(f"  fxx={fxx:3d}h core: no TMAX window message")
        except Exception as e:  # noqa: BLE001
            print(f"  fxx={fxx:3d}h core: SKIPPED ({type(e).__name__}: {str(e)[:100]})")

        # ---- QMD (opt-in): instantaneous-TMP percentiles, per-percentile ----
        if include_qmd:
            try:
                Hq = Herbie(run_naive, model=_QMD_MODEL, product="co", fxx=fxx,
                            priority=["aws", "nomads"], save_dir=save_dir, verbose=False)
                got = 0
                for pct in PERCENTILES:
                    search = rf":TMP:2 m above ground:\d+ hour fcst:{pct}% level:"
                    ds_p = _xr_one(Hq, search)
                    if ds_p is None:
                        continue
                    v_k, yx_qmd = _nearest_value(ds_p, station, yx_qmd)
                    rows.append({"init_time": init_utc, "valid_time": valid_time,
                                 "station_id": station_id, "model": "nbm_qmd",
                                 "member_id": pct, "temperature_f": None,
                                 "tmax_f": kelvin_to_fahrenheit(v_k)})
                    got += 1
                if got:
                    n_qmd_windows += 1
                print(f"  fxx={fxx:3d}h qmd: {got}/{len(PERCENTILES)} percentiles")
            except Exception as e:  # noqa: BLE001
                print(f"  fxx={fxx:3d}h qmd: SKIPPED ({type(e).__name__}: {str(e)[:100]})")

        time.sleep(0.3)  # gentle on AWS S3

    if rows:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(_INSERT_SQL, rows)

    return {
        "model": "nbm",
        "station_id": station_id,
        "rows_inserted": len(rows),
        "core_windows": n_core_windows,
        "qmd_windows": n_qmd_windows,
        "forecast_hours": forecast_hours,
    }


def purge_cache(save_dir: str | None = None) -> None:
    """Delete the isolated NBM Herbie cache (idx leftovers; GRIBs are auto-removed
    by remove_grib=True). Call between backfill chunks to bound disk on the box."""
    shutil.rmtree(save_dir or DEFAULT_SAVE_DIR, ignore_errors=True)
