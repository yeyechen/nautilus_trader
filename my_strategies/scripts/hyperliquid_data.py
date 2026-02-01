from datetime import datetime
from datetime import timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from my_strategies.database import ClickHouseConnection
from my_strategies.database import get_signal_db_config


load_dotenv(Path(__file__).parent.parent.parent / ".env")

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "hyperliquid"
COLUMNS = [
    "time",
    "coin",
    "funding",
    "open_interest",
    "prev_day_px",
    "day_ntl_vlm",
    "premium",
    "oracle_px",
    "mid_px",
    "mark_px",
    "impact_bid_px",
    "impact_ask_px",
]


def load_hyperliquid_hourly(
    coin: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    save_to_file: bool = True,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    config = get_signal_db_config()
    conn = ClickHouseConnection(config)

    query = """
    SELECT
        toTimeZone(time, 'UTC') AS time,
        coin,
        funding,
        open_interest,
        prev_day_px,
        day_ntl_vlm,
        premium,
        oracle_px,
        mid_px,
        mark_px,
        impact_bid_px,
        impact_ask_px
    FROM hyperliquid.asset_ctx
    WHERE toMinute(toTimeZone(time, 'UTC')) = 0
      AND toSecond(toTimeZone(time, 'UTC')) = 0
    """

    params = {}

    if coin is not None:
        query += " AND coin = %(coin)s"
        params["coin"] = coin

    if start_date is not None:
        query += " AND time >= %(start_date)s"
        params["start_date"] = start_date

    if end_date is not None:
        query += " AND time <= %(end_date)s"
        params["end_date"] = end_date

    query += " ORDER BY time ASC"

    try:
        results = conn.execute(query, params)
        df = pd.DataFrame(results, columns=COLUMNS)

        if "time" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["time"]):
            df["time"] = pd.to_datetime(df["time"])

        if save_to_file and len(df) > 0:
            out_path = output_dir if output_dir else OUTPUT_DIR
            out_path.mkdir(parents=True, exist_ok=True)

            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")  # noqa: UP017
            coin_part = coin if coin else "all_coins"
            filename = f"hyperliquid_{coin_part}_hourly_{timestamp_str}.parquet"
            file_path = out_path / filename

            df.to_parquet(file_path, index=False)
            print(f"Saved to: {file_path}")

        return df

    finally:
        conn.disconnect()


def get_unique_coins() -> list[str]:
    config = get_signal_db_config()
    conn = ClickHouseConnection(config)

    query = """
    SELECT DISTINCT coin
    FROM hyperliquid.asset_ctx
    ORDER BY coin ASC
    """

    try:
        results = conn.execute(query, {})
        return [row[0] for row in results]
    finally:
        conn.disconnect()


if __name__ == "__main__":
    START_DATE = "2025-01-01"
    END_DATE = "2025-12-31"

    print("=" * 60)
    print("HYPERLIQUID DATA LOADER")
    print("=" * 60)
    print(f"Date range: {START_DATE} to {END_DATE}")
    print("Filter: Hourly data (minute=0, second=0) UTC")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)

    print("\nFetching unique coins...")
    coins = get_unique_coins()
    print(f"Found {len(coins)} unique coins")

    print("\nGenerating parquet files...\n")
    successful = 0
    failed = 0

    for i, coin in enumerate(coins, 1):
        try:
            print(f"[{i}/{len(coins)}] Processing {coin}...")
            df = load_hyperliquid_hourly(
                coin=coin,
                start_date=START_DATE,
                end_date=END_DATE,
                save_to_file=True,
            )

            if len(df) > 0:
                print(f"  Loaded {len(df)} rows")
                successful += 1
            else:
                print("  No data found")

        except Exception as e:
            print(f"  Error: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total coins: {len(coins)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)
