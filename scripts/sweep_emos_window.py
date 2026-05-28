"""
Window-size sweep for rolling EMOS.

For each candidate window w in WINDOW_SIZES, computes rolling out-of-sample
CRPS over the evaluation range and reports which window minimizes mean CRPS.
All windows are evaluated on the same set of dates for a fair comparison.

Supports both 12Z combined (default) and 00Z ECMWF workflows via CLI flags:
    uv run python scripts/sweep_emos_window.py                              # 12Z combined
    uv run python scripts/sweep_emos_window.py --model ifs --init-hour 0    # 00Z ECMWF

Output files are suffixed with the workflow so re-runs don't clobber.
"""
import argparse
import csv
import math
import statistics
import time
from bisect import bisect_left
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt

from weather_markets.db import get_connection
from weather_markets.aggregation import collect_training_pairs
from weather_markets.emos import fit_emos, crps_gaussian


WINDOW_SIZES = [30, 45, 60, 90, 120]
MIN_TRAIN_DAYS = 30
EVAL_START = date(2025, 8, 29)        # first eval day = PRECOMPUTE_START + max(WINDOW_SIZES)
PRECOMPUTE_START = date(2025, 5, 1)   # earliest forecast/observation data in the DB
STATION_ID = "KNYC"

# Model name → list of model codes passed to compute_combined_daily_highs.
MODEL_TO_CODES = {
    "combined": ["gefs", "ifs"],
    "gefs": ["gefs"],
    "ifs": ["ifs"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=list(MODEL_TO_CODES), default="combined",
                        help="Ensemble source: combined (gefs+ifs), gefs, or ifs.")
    parser.add_argument("--init-hour", type=int, choices=[0, 12], default=12,
                        help="Forecast init hour (UTC).")
    args = parser.parse_args()

    models = MODEL_TO_CODES[args.model]
    init_hour = args.init_hour
    workflow_tag = f"{args.model}_{init_hour:02d}z"
    output_png = Path(f"outputs/window_sweep_{workflow_tag}.png")
    output_csv = Path(f"outputs/window_sweep_daily_{workflow_tag}.csv")

    print(f"Workflow: model={args.model} (codes={models}), init_hour={init_hour:02d}Z")
    print(f"Output:   {output_png}, {output_csv}")
    print()
    # 1. Precompute training pairs once.
    print("=== Precomputing training pairs ===", flush=True)
    print("(expect ~30–60s — one DB roundtrip per model per day)", flush=True)
    t0 = time.time()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM observations WHERE station_id = %s",
                (STATION_ID,),
            )
            latest_obs = cur.fetchone()[0]
        if latest_obs is None or latest_obs < EVAL_START:
            print(f"Not enough observations (latest = {latest_obs}). Exiting.")
            return
        print(f"  range: {PRECOMPUTE_START} → {latest_obs}", flush=True)
        means, stds, obs, dates = collect_training_pairs(
            conn, PRECOMPUTE_START, latest_obs,
            station_id=STATION_ID, models=models, init_hour=init_hour,
        )
    print(f"  collected {len(dates)} training pairs in {time.time() - t0:.1f}s", flush=True)

    if not dates:
        print("No training data found. Exiting.")
        return

    # 2. Evaluation dates = precomputed dates on/after EVAL_START.
    eval_dates = [d for d in dates if d >= EVAL_START]
    if not eval_dates:
        print(f"No precomputed dates on or after {EVAL_START}. Exiting.")
        return
    print(
        f"\nEvaluation set: {len(eval_dates)} days "
        f"({eval_dates[0]} → {eval_dates[-1]})",
        flush=True,
    )

    # date → index lookup for D's own ensemble stats.
    date_to_idx = {d: i for i, d in enumerate(dates)}

    # 3. Score each window.
    results: dict[int, list[tuple[date, float, float]]] = {}
    for w in WINDOW_SIZES:
        print(f"\n=== window = {w} days ===", flush=True)
        scored: list[tuple[date, float, float]] = []
        skipped_insufficient = 0
        t_w = time.time()
        for D in eval_dates:
            train_lo = D - timedelta(days=w)
            # dates is sorted ascending — bisect gives [lo_idx, hi_idx) with
            # train_lo <= dates[i] < D. Strict < D guarantees no lookahead.
            lo_idx = bisect_left(dates, train_lo)
            hi_idx = bisect_left(dates, D)
            n_train = hi_idx - lo_idx
            if n_train < MIN_TRAIN_DAYS:
                skipped_insufficient += 1
                continue

            params = fit_emos(
                means[lo_idx:hi_idx],
                stds[lo_idx:hi_idx],
                obs[lo_idx:hi_idx],
            )

            idx_D = date_to_idx[D]
            emos_mu = params["a"] + params["b"] * means[idx_D]
            emos_var = params["c"] + params["d"] * stds[idx_D] ** 2
            if emos_var <= 0:
                continue
            emos_sigma = math.sqrt(emos_var)

            crps = crps_gaussian(emos_mu, emos_sigma, obs[idx_D])
            mae = abs(emos_mu - obs[idx_D])
            scored.append((D, crps, mae))
        results[w] = scored
        print(
            f"  scored {len(scored)} days in {time.time() - t_w:.1f}s "
            f"({skipped_insufficient} skipped for <{MIN_TRAIN_DAYS} train days)",
            flush=True,
        )

    # 4. Table.
    print()
    header = f"{'window_days':>11} | {'n_days':>6} | {'mean_crps':>9} | {'crps_se':>8} | {'mean_mae':>8}"
    print(header)
    print(f"{'-'*11}-+-{'-'*6}-+-{'-'*9}-+-{'-'*8}-+-{'-'*8}")
    summary: list[tuple[int, int, float, float, float]] = []
    for w in WINDOW_SIZES:
        scored = results[w]
        if not scored:
            print(f"{w:>11} | {0:>6} | {'NA':>9} | {'NA':>8} | {'NA':>8}")
            continue
        crps_vals = [r[1] for r in scored]
        mae_vals = [r[2] for r in scored]
        n = len(crps_vals)
        mean_crps = statistics.mean(crps_vals)
        crps_se = statistics.stdev(crps_vals) / math.sqrt(n) if n > 1 else float("nan")
        mean_mae = statistics.mean(mae_vals)
        summary.append((w, n, mean_crps, crps_se, mean_mae))
        print(f"{w:>11} | {n:>6} | {mean_crps:>9.4f} | {crps_se:>8.4f} | {mean_mae:>8.4f}")

    if not summary:
        print("\nNo windows produced scored days; cannot recommend.")
        return

    # 5. Recommendation: largest window within 1 SE of the best mean CRPS.
    best = min(summary, key=lambda r: r[2])
    best_w, _, best_crps, best_se, _ = best
    threshold = best_crps + best_se
    within = [r for r in summary if r[2] <= threshold]
    largest = max(within, key=lambda r: r[0])
    print(f"\nBest mean CRPS: w={best_w} ({best_crps:.4f})")
    print(
        f"Within 1 SE of best (≤ {threshold:.4f}): "
        f"{', '.join(f'w={r[0]}' for r in within)}"
    )
    print(f"Recommended default: w={largest[0]} (largest within 1 SE)")

    # 6. Plot.
    output_png.parent.mkdir(parents=True, exist_ok=True)
    ws = [r[0] for r in summary]
    ys = [r[2] for r in summary]
    yerrs = [r[3] for r in summary]
    plt.figure(figsize=(7, 4))
    plt.errorbar(ws, ys, yerr=yerrs, fmt="o-", capsize=4)
    plt.axhline(
        threshold,
        linestyle=":",
        color="gray",
        label=f"1 SE above best ({threshold:.4f})",
    )
    plt.xlabel("Window size (days)")
    plt.ylabel("Mean OOS CRPS")
    plt.title(f"Rolling EMOS sweep — {args.model} {init_hour:02d}Z ({len(eval_dates)} eval days)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_png, dpi=110)
    plt.close()
    print(f"\nPlot saved: {output_png}")

    # 7. CSV export of per-day results.
    with output_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "window_days", "crps", "mae"])
        for w in WINDOW_SIZES:
            for d, crps, mae in results[w]:
                writer.writerow([d.isoformat(), w, f"{crps:.6f}", f"{mae:.6f}"])
    print(f"CSV saved: {output_csv}")


if __name__ == "__main__":
    main()
