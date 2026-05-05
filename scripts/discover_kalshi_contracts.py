# scripts/discover_kalshi_contracts.py
"""Discover currently-active Kalshi NHIGH contracts for KNYC."""
from weather_markets.kalshi import discover_kalshi_contracts


def main() -> None:
    result = discover_kalshi_contracts()
    print(result)


if __name__ == "__main__":
    main()