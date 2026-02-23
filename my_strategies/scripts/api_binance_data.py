"""
Fetch minute-level perpetual OHLCV data from Binance API for all signal-universe symbols.

Usage:
    python -m my_strategies.scripts.api_binance_data
"""
import time
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pandas as pd
from binance.client import Client
from binance.enums import HistoricalKlinesType

from my_strategies.utils.data_fetching import get_unique_symbols


# --- Configuration ---
START_DATE = "2024-12-01"
END_DATE = datetime.now(UTC).strftime("%Y-%m-%d")
INTERVAL = "1m"
OUTPUT_DIR = Path("/Volumes/MyBlackBox/binance_1m_perps_20241201_20260213")

# Pause between symbols to avoid rate limits
SLEEP_BETWEEN_SYMBOLS = 1.0


def fetch_perp_klines(
    client: Client,
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Fetch 1-minute perpetual futures klines from Binance for a single symbol.

    The python-binance library handles pagination internally, so this will
    automatically loop through all available data in the date range.
    """
    klines = client.get_historical_klines(
        symbol=symbol,
        interval=Client.KLINE_INTERVAL_1MINUTE,
        start_str=f"{start_date} 00:00:00",
        end_str=f"{end_date} 23:59:59",
        klines_type=HistoricalKlinesType.FUTURES,
    )

    if not klines:
        return pd.DataFrame()

    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades_count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore",
    ])

    # Convert types
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    for col in ["open", "high", "low", "close", "volume", "quote_volume",
                "taker_buy_volume", "taker_buy_quote_volume"]:
        df[col] = df[col].astype(float)
    df["trades_count"] = df["trades_count"].astype(int)

    # Add metadata columns
    df["symbol"] = symbol
    df["interval"] = INTERVAL

    # Select columns in consistent order
    df = df[[
        "symbol", "interval", "timestamp", "close_time",
        "open", "high", "low", "close", "volume", "quote_volume",
        "taker_buy_volume", "taker_buy_quote_volume", "trades_count",
    ]].reset_index(drop=True)

    return df


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("BINANCE PERPETUAL 1-MINUTE KLINES FETCHER (API)")
    print("=" * 80)
    print(f"Interval: {INTERVAL}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 80)

    # Get symbols
    symbols = get_unique_symbols()
    print(f"\nFound {len(symbols)} symbols to fetch")

    # Check which symbols already have data (for resume capability)
    existing = {f.stem for f in OUTPUT_DIR.glob("*.parquet")}
    remaining = [s for s in symbols if s not in existing]
    if len(remaining) < len(symbols):
        print(f"Skipping {len(symbols) - len(remaining)} already-downloaded symbols")
    symbols = remaining

    if not symbols:
        print("All symbols already downloaded. Nothing to do.")
        return

    print(f"Fetching {len(symbols)} symbols...\n")

    # Initialize Binance client (no API key needed for public market data)
    client = Client()

    successful = 0
    failed = 0
    failed_symbols = []

    for i, symbol in enumerate(symbols, 1):
        try:
            print(f"[{i}/{len(symbols)}] {symbol}...", end=" ", flush=True)
            t0 = time.time()

            df = fetch_perp_klines(client, symbol, START_DATE, END_DATE)

            if len(df) == 0:
                print("no data")
                continue

            # Save to parquet
            file_path = OUTPUT_DIR / f"{symbol}.parquet"
            df.to_parquet(file_path, index=False)

            elapsed = time.time() - t0
            print(f"{len(df):,} rows  ({elapsed:.1f}s)  [{df['timestamp'].min().date()} -> {df['timestamp'].max().date()}]")
            successful += 1

        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1
            failed_symbols.append(symbol)

        # Rate limit
        if i < len(symbols):
            time.sleep(SLEEP_BETWEEN_SYMBOLS)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total symbols: {len(symbols)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    if failed_symbols:
        print(f"Failed symbols: {', '.join(failed_symbols)}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()
