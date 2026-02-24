"""
Fetch historical funding rates from Binance Futures API for all symbols.

Usage:
    python -m my_strategies.scripts.fetch_binance_funding_rates
"""

import time
from pathlib import Path

import pandas as pd
from binance.client import Client


# --- Configuration ---
START_DATE = "2024-12-01"
END_DATE = "2026-02-22"

START_MS = int(pd.Timestamp(START_DATE, tz="UTC").timestamp() * 1000)
END_MS = int(pd.Timestamp(END_DATE, tz="UTC").timestamp() * 1000) + 86400_000 - 1

DATA_DIR = Path(__file__).parent.parent / "data"
BAR_DATA_DIR = DATA_DIR / "binance_1m_perps_20241201_20260213"
OUTPUT_DIR = DATA_DIR / "binance_funding_rates"

LIMIT = 1000
SLEEP_BETWEEN_SYMBOLS = 0.5


def fetch_funding_rates(
    client: Client, symbol: str, start_ms: int, end_ms: int,
) -> pd.DataFrame:
    """Fetch all historical funding rates for a symbol, handling pagination."""
    all_records = []
    cursor = start_ms

    while cursor < end_ms:
        batch = client.futures_funding_rate(
            symbol=symbol,
            startTime=cursor,
            endTime=end_ms,
            limit=LIMIT,
        )
        if not batch:
            break

        all_records.extend(batch)

        last_time = batch[-1]["fundingTime"]
        if last_time == cursor:
            break
        cursor = last_time + 1

        if len(batch) == LIMIT:
            time.sleep(0.2)

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["markPrice"] = df["markPrice"].astype(float)

    df = df.rename(columns={
        "fundingTime": "timestamp",
        "fundingRate": "funding_rate",
        "markPrice": "mark_price",
    })

    df = df[["symbol", "timestamp", "funding_rate", "mark_price"]].reset_index(drop=True)
    return df


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("BINANCE HISTORICAL FUNDING RATES FETCHER")
    print("=" * 60)
    print(f"Date range: {START_DATE} -> {END_DATE}")
    print(f"Output dir: {OUTPUT_DIR}")
    print("=" * 60)

    symbols = sorted([f.stem for f in BAR_DATA_DIR.glob("*.parquet")])
    print(f"\nFound {len(symbols)} symbols")

    existing = {f.stem for f in OUTPUT_DIR.glob("*.parquet")}
    remaining = [s for s in symbols if s not in existing]
    if len(remaining) < len(symbols):
        print(f"Skipping {len(symbols) - len(remaining)} already-downloaded symbols")
    symbols_to_fetch = remaining

    if not symbols_to_fetch:
        print("All symbols already downloaded. Nothing to do.")
        return

    print(f"Fetching {len(symbols_to_fetch)} symbols...\n")

    client = Client()

    successful = 0
    failed = 0
    failed_symbols = []

    for i, symbol in enumerate(symbols_to_fetch, 1):
        try:
            print(f"[{i}/{len(symbols_to_fetch)}] {symbol}...", end=" ", flush=True)
            t0 = time.time()

            df = fetch_funding_rates(client, symbol, START_MS, END_MS)

            if len(df) == 0:
                print("no data")
                continue

            output_path = OUTPUT_DIR / f"{symbol}.parquet"
            df.to_parquet(output_path, index=False)

            elapsed = time.time() - t0
            print(
                f"{len(df)} records  ({elapsed:.1f}s)  "
                f"[{df['timestamp'].min().date()} -> {df['timestamp'].max().date()}]"
            )
            successful += 1

        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1
            failed_symbols.append(symbol)

        if i < len(symbols_to_fetch):
            time.sleep(SLEEP_BETWEEN_SYMBOLS)

    print("\n" + "=" * 60)
    print(f"Successful: {successful}  |  Failed: {failed}")
    if failed_symbols:
        print(f"Failed symbols: {', '.join(failed_symbols)}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
