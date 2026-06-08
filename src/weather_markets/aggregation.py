"""
Aggregation functions for ensemble forecasts.
"""
import math
import statistics
from datetime import date, datetime, timedelta, timezone

class NoForecastDataError(Exception):
    """Raised when no forecast data exists for the requested query."""
    pass

def compute_daily_highs(
    init_time: datetime,
    target_date: date,
    conn,
    station_id: str = "KNYC",
    timezone_name: str = "America/New_York",
    bias_correction: float = 0.0,
    model: str = "gefs",
) -> dict[int, float]:

    sql = """
        SELECT member_id, MAX(tmax_f) AS daily_high_f
        FROM forecasts
        WHERE init_time = %s
          AND station_id = %s
          AND model = %s
          AND valid_time AT TIME ZONE %s >= %s::timestamp
          AND valid_time AT TIME ZONE %s <  (%s::date + interval '1 day')::timestamp
        GROUP BY member_id
        ORDER BY member_id
    """
    
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (init_time, station_id, model, timezone_name, target_date, timezone_name, target_date),
        )
        rows = cur.fetchall()
    
    if not rows:
        raise NoForecastDataError(
            f"No forecasts for init_time={init_time}, "
            f"target_date={target_date}, station_id={station_id}"
        )
    
    return {member_id: high for member_id, high in rows}

def is_yes(high, contract):
    bracket_type = contract["bracket_type"]
    if bracket_type == "greater_than":
        return high >= contract["strike_low"] + 1
    elif bracket_type == "less_than":
        return high < contract["strike_high"]
    elif bracket_type == "between":
        return (
            contract["strike_low"] <= high 
            and high < contract["strike_high"] + 1
        )
    else:
        raise ValueError(f"Unknown bracket_type: {bracket_type!r}")

def compute_ensemble_probabilities(
    highs,  # dict[int, float] or list[float]
    contracts: list[dict],
) -> dict[str, float]:
    """..."""
    # Normalize input to a list of values
    if isinstance(highs, dict):
        values = list(highs.values())
    else:
        values = list(highs)
    
    if not values:
        raise ValueError("highs cannot be empty")
    
    n_members = len(values)
    result = {}
    for contract in contracts:
        yes_count = sum(1 for h in values if is_yes(h, contract))
        result[contract["ticker"]] = yes_count / n_members
    return result

def fetch_observed_high(
    target_date: date,
    conn,
    station_id: str = "KNYC",
) -> float | None:

    sql = """
        SELECT high_temp_f
        FROM observations
        WHERE date = %s AND station_id = %s
    """
    
    with conn.cursor() as cur:
        cur.execute(sql, (target_date, station_id))
        row = cur.fetchone()
    
    if row is None:
        return None
    
    return float(row[0])

def fetch_contracts_for_date(
    target_date: date,
    conn,
    station_id: str = "KNYC",
    series: str | None = "KXHIGHNY",
    platform: str | None = None,
) -> list[dict]:
    """
    Fetch contracts whose target_date matches the given date.

    Defaults to KXHIGHNY only — the production daily-highs strategy. Pass
    series=None to disable the series filter (returns all series for the date),
    or pass another series ticker (e.g. "KXLOWTNYC") to scope to a different
    contract family. platform='polymarket' filters to Polymarket-side contracts
    only (Kalshi default if omitted).

    Returns:
        List of contract dicts with keys: ticker, bracket_type, strike_low, strike_high.
        Empty list if no contracts exist for that date.
    """

    if series is None:
        sql = """
            SELECT ticker, bracket_type, strike_low, strike_high
            FROM contracts
            WHERE target_date = %s
              AND station_id = %s
        """
        params = [target_date, station_id]
        if platform is not None:
            sql += " AND platform = %s"
            params.append(platform)
        sql += " ORDER BY bracket_type, strike_low"
        params = tuple(params)
    else:
        sql = """
            SELECT ticker, bracket_type, strike_low, strike_high
            FROM contracts
            WHERE target_date = %s
              AND station_id = %s
              AND series = %s
        """
        params = [target_date, station_id, series]
        if platform is not None:
            sql += " AND platform = %s"
            params.append(platform)
        sql += " ORDER BY bracket_type, strike_low"
        params = tuple(params)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
    {"ticker": t, "bracket_type": b, "strike_low": l, "strike_high": h}
    for t, b, l, h in rows
    ]


def collect_training_pairs_equal_weight(
    conn,
    start_date: date,
    end_date: date,
    station_id: str = "KNYC",
    models: list[str] | None = None,
    init_hour: int = 0,
) -> tuple[list[float], list[float], list[float], list[date]]:
    """Like collect_training_pairs but uses equal-model weighting.

    Each model gets equal weight in the ensemble mean regardless of member count
    (so HRRR gets 1/3 weight in a GEFS+IFS+HRRR setup, not 1/82). See
    compute_combined_daily_highs_stats(weighting='equal_model') for details.
    """
    means, stds, obs, dates = [], [], [], []
    d = start_date
    while d <= end_date:
        init = datetime(d.year, d.month, d.day, init_hour, 0, tzinfo=timezone.utc)
        try:
            mean, std, n = compute_combined_daily_highs_stats(
                init, d, conn,
                station_id=station_id, models=models, weighting="equal_model",
            )
        except NoForecastDataError:
            d += timedelta(days=1)
            continue
        observation = fetch_observed_high(d, conn, station_id=station_id)
        if observation is not None and std > 0 and n >= 2:
            means.append(mean)
            stds.append(std)
            obs.append(observation)
            dates.append(d)
        d += timedelta(days=1)
    return means, stds, obs, dates


def collect_training_pairs(
    conn,
    start_date: date,
    end_date: date,
    station_id: str = "KNYC",
    models: list[str] | None = None,
    init_hour: int = 12,
) -> tuple[list[float], list[float], list[float], list[date]]:
    """
    Walk [start_date, end_date] inclusive. For each day with both an ensemble
    forecast (at the given init_hour UTC) and an observation, append
    (mean, std, obs, date) to four parallel lists. Days with missing data on
    either side are skipped (INNER JOIN semantics).

    init_hour defaults to 12 to preserve legacy callers. Pass init_hour=0 for
    00Z-based training (e.g., for market-open trading with ECMWF 00Z runs).

    Shared by full-sample and rolling-window EMOS fits.
    """
    means, stds, obs, dates = [], [], [], []
    d = start_date
    while d <= end_date:
        init = datetime(d.year, d.month, d.day, init_hour, 0, tzinfo=timezone.utc)
        try:
            values = compute_combined_daily_highs(
                init, d, conn, station_id=station_id, models=models,
            )
        except NoForecastDataError:
            d += timedelta(days=1)
            continue
        observation = fetch_observed_high(d, conn, station_id=station_id)
        if observation is not None and len(values) >= 2:
            means.append(statistics.mean(values))
            stds.append(statistics.stdev(values))
            obs.append(observation)
            dates.append(d)
        d += timedelta(days=1)
    return means, stds, obs, dates


def compute_combined_daily_highs_stats(
    init_time: datetime,
    target_date: date,
    conn,
    *,
    station_id: str = "KNYC",
    timezone_name: str = "America/New_York",
    models: list[str] | None = None,
    weighting: str = "flat",
) -> tuple[float, float, int]:
    """Return (ensemble_mean, ensemble_std, n_members_effective) under a given weighting.

    weighting='flat' (default): treat all ensemble members across all models as
    equal samples (current production behavior). With 31 GEFS + 50 IFS + 1 HRRR
    this implicitly weights each model by its member count.

    weighting='equal_model': give each MODEL equal weight regardless of member
    count. Mean = arithmetic average of per-model means. Variance = pooled
    within-model variance for models with ≥2 members (skips deterministic models
    like HRRR for the variance estimate since they have no spread information).

    n_members_effective is the count of members used to compute mean.
    """
    if models is None:
        models = ["gefs", "ifs"]

    per_model_values: dict[str, list[float]] = {}
    for model in models:
        try:
            highs = compute_daily_highs(
                init_time, target_date, conn,
                station_id=station_id, timezone_name=timezone_name, model=model,
            )
            per_model_values[model] = list(highs.values())
        except NoForecastDataError:
            continue

    if not per_model_values:
        raise NoForecastDataError(
            f"No forecast data for any model on {target_date} from {init_time}"
        )

    if weighting == "flat":
        all_vals = [v for vals in per_model_values.values() for v in vals]
        mean = statistics.mean(all_vals)
        std = statistics.stdev(all_vals) if len(all_vals) >= 2 else 0.0
        return mean, std, len(all_vals)
    elif weighting == "equal_model":
        model_means = [statistics.mean(vals) for vals in per_model_values.values()]
        mean = statistics.mean(model_means)
        within_model_vars = [
            statistics.variance(vals) for vals in per_model_values.values() if len(vals) >= 2
        ]
        if within_model_vars:
            std = math.sqrt(statistics.mean(within_model_vars))
        elif len(model_means) >= 2:
            std = statistics.stdev(model_means)  # fall back to spread of model means
        else:
            std = 0.0
        n_effective = sum(len(vals) for vals in per_model_values.values())
        return mean, std, n_effective
    else:
        raise ValueError(f"Unknown weighting: {weighting!r}")


def compute_combined_daily_highs(
    init_time: datetime,
    target_date: date,
    conn,
    station_id: str = "KNYC",
    timezone_name: str = "America/New_York",
    models: list[str] | None = None,
) -> list[float]:
    """
    Compute daily highs across multiple models, returning a single combined list of values.

    Member IDs are not preserved (since they could collide across models).
    Returns a flat list of high values.
    """
    if models is None:
        models = ["gefs", "ifs"]

    all_values = []
    for model in models:
        try:
            highs = compute_daily_highs(
                init_time, target_date, conn,
                station_id=station_id,
                timezone_name=timezone_name,
                model=model,
            )
            all_values.extend(highs.values())
        except NoForecastDataError:
            continue  # OK if one model is missing

    if not all_values:
        raise NoForecastDataError(
            f"No forecast data for any model on {target_date} from {init_time}"
        )

    return all_values


# ===================================================================
# DAY-AHEAD LOW TEMPERATURE FORECASTS (for KXLOWTNYC strategy)
# ===================================================================
#
# Architecture differs from daily highs because the NYC daily low occurs in
# early morning (~04-08 EDT = 08-12 UTC), which is hours BEFORE a same-day
# 14:45 UTC decision could be made. So for lows we use the prior-day 00Z init
# and forecast the next morning's low — i.e., 17-21 hour forecast horizon.
#
# Forecast hours [30, 33, 36] from day-D 00Z map to 06/09/12 UTC on day D+1,
# covering the morning low window. We take MIN of instantaneous temperature
# across those three timesteps per ensemble member.

DEFAULT_LOW_FORECAST_HOURS = (30, 33, 36)


def compute_daily_lows(
    init_time: datetime,
    target_date: date,
    conn,
    station_id: str = "KNYC",
    model: str = "gefs",
    forecast_hours: tuple[int, ...] = DEFAULT_LOW_FORECAST_HOURS,
) -> dict[int, float]:
    """
    Per-member day-ahead morning low estimate.

    init_time should be the prior day's 00Z (i.e., target_date - 1 at 00 UTC).
    target_date is the day whose morning low we're predicting.

    Uses instantaneous temperature_f (not tmax_f) at forecast hours covering
    the early-morning window of target_date, taking MIN across timesteps per
    member.
    """
    sql = """
        SELECT member_id, MIN(temperature_f) AS morning_low_f
        FROM forecasts
        WHERE init_time = %s
          AND station_id = %s
          AND model = %s
          AND temperature_f IS NOT NULL
          AND EXTRACT(EPOCH FROM (valid_time - init_time))/3600 = ANY(%s)
        GROUP BY member_id
        ORDER BY member_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (init_time, station_id, model, list(forecast_hours)))
        rows = cur.fetchall()

    if not rows:
        raise NoForecastDataError(
            f"No low-forecast data for init_time={init_time}, "
            f"target_date={target_date}, station_id={station_id}, model={model}"
        )

    return {member_id: low for member_id, low in rows}


def compute_combined_daily_lows(
    init_time: datetime,
    target_date: date,
    conn,
    station_id: str = "KNYC",
    models: list[str] | None = None,
    forecast_hours: tuple[int, ...] = DEFAULT_LOW_FORECAST_HOURS,
) -> list[float]:
    """Combined-ensemble day-ahead morning low. Mirrors compute_combined_daily_highs."""
    if models is None:
        models = ["gefs", "ifs"]
    all_values = []
    for model in models:
        try:
            lows = compute_daily_lows(
                init_time, target_date, conn,
                station_id=station_id, model=model, forecast_hours=forecast_hours,
            )
            all_values.extend(lows.values())
        except NoForecastDataError:
            continue
    if not all_values:
        raise NoForecastDataError(
            f"No low-forecast data for any model on {target_date} from {init_time}"
        )
    return all_values


def fetch_observed_low(target_date: date, conn, station_id: str = "KNYC") -> float | None:
    """Observed daily low for target_date. Mirrors fetch_observed_high."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT low_temp_f FROM observations WHERE date = %s AND station_id = %s",
            (target_date, station_id),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def collect_training_pairs_for_lows(
    conn,
    start_date: date,
    end_date: date,
    station_id: str = "KNYC",
    models: list[str] | None = None,
    forecast_hours: tuple[int, ...] = DEFAULT_LOW_FORECAST_HOURS,
) -> tuple[list[float], list[float], list[float], list[date]]:
    """
    Walk [start_date, end_date] inclusive. For each target_date D, pull the
    prior day's 00Z forecast (init = D-1 at 00 UTC) and the observed low on D.
    Returns (means, stds, obs_lows, dates) for days with both sides present.
    """
    means, stds, obs, dates = [], [], [], []
    d = start_date
    while d <= end_date:
        init = datetime(d.year, d.month, d.day, 0, 0, tzinfo=timezone.utc) - timedelta(days=1)
        try:
            values = compute_combined_daily_lows(
                init, d, conn, station_id=station_id, models=models, forecast_hours=forecast_hours,
            )
        except NoForecastDataError:
            d += timedelta(days=1)
            continue
        observation = fetch_observed_low(d, conn, station_id=station_id)
        if observation is not None and len(values) >= 2:
            means.append(statistics.mean(values))
            stds.append(statistics.stdev(values))
            obs.append(observation)
            dates.append(d)
        d += timedelta(days=1)
    return means, stds, obs, dates