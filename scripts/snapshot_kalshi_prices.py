# scripts/snapshot_kalshi_prices.py
"""Snapshot current prices of all open Kalshi NHIGH contracts."""
from weather_markets.kalshi import snapshot_kalshi_prices


def main() -> None:
    result = snapshot_kalshi_prices()
    print(result)


if __name__ == "__main__":
    main()