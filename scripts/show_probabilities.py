# scripts/show_probabilities.py
"""Display ensemble probabilities and Kalshi prices side by side."""
from datetime import datetime, date, timezone
from rich.console import Console
from rich.table import Table

from weather_markets.db import get_connection
from weather_markets.aggregation import compute_daily_highs, compute_ensemble_probabilities



def main():

    target_date = date(2026, 5, 14)
    
    with get_connection() as conn:
        # Compute ensemble probabilities
        
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(init_time) FROM forecasts WHERE station_id = %s", ("KNYC",))
            init_time = cur.fetchone()[0]

        highs = compute_daily_highs(init_time, target_date, conn)
        
        # Fetch contracts (inline for now)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ticker, bracket_type, strike_low, strike_high
                FROM contracts
                WHERE target_date = %s
                ORDER BY bracket_type, strike_low
            """, (target_date,))
            contracts = [
                {"ticker": t, "bracket_type": b, "strike_low": l, "strike_high": h}
                for t, b, l, h in cur.fetchall()
            ]
        
        # Get latest prices
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                FROM prices
                WHERE ticker = ANY(%s)
                ORDER BY ticker, snapshot_at DESC
            """, ([c["ticker"] for c in contracts],))
            prices = {t: (b, a) for t, b, a in cur.fetchall()}
        
        probs = compute_ensemble_probabilities(highs, contracts)
    
    # Build the table
    console = Console()
    table = Table(title=f"NYC High Temp — {target_date}", show_lines=True)
    
    table.add_column("Contract", style="cyan")
    table.add_column("Range", style="magenta")
    table.add_column("Model P", justify="right", style="green")
    table.add_column("Yes Bid", justify="right")
    table.add_column("Yes Ask", justify="right")
    table.add_column("Edge", justify="right", style="bold yellow")
    
    for c in contracts:
        ticker = c["ticker"]
        bid, ask = prices.get(ticker, (None, None))
        model_p = probs[ticker]
        
        if c["bracket_type"] == "greater_than":
            range_str = f">{c['strike_low']}°"
        elif c["bracket_type"] == "less_than":
            range_str = f"<{c['strike_high']}°"
        else:
            range_str = f"{c['strike_low']}-{c['strike_high']}°"
        
        edge = (model_p * 100) - ask if ask is not None else None
        edge_str = f"{edge:+.1f}" if edge is not None else "—"
        
        table.add_row(
            ticker,
            range_str,
            f"{model_p:.1%}",
            f"{bid}¢" if bid is not None else "—",
            f"{ask}¢" if ask is not None else "—",
            edge_str,
        )
    
    console.print(table)


if __name__ == "__main__":
    main()