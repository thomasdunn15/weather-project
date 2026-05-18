"""Backtest the naive ensemble baseline over a date range."""
from datetime import date, timedelta

from weather_markets.db import get_connection
from weather_markets.backtesting import backtest_range


def main() -> None:
    start = date(2026, 5, 5)
    
    with get_connection() as conn:
        # Auto-detect end date from latest observation
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM observations WHERE station_id = %s",
                ("KNYC",),
            )
            end = cur.fetchone()[0]
        
        target_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        results = backtest_range(target_dates, conn)
    
    # Print a summary table
    print(f"\n{'Date':<12} {'Observed':>10} {'Mean Brier':>12}")
    print(f"{'-'*12} {'-'*10} {'-'*12}")
    for r in results:
        print(f"{r['target_date']!s:<12} {r['observed']:>10} {r['mean_brier']:>12.4f}")
    
    if results:
        overall = sum(r['mean_brier'] for r in results) / len(results)
        print(f"\nOverall mean Brier across {len(results)} days: {overall:.4f}")
    else:
        print("\nNo backtestable days found.")


if __name__ == "__main__":
    main()