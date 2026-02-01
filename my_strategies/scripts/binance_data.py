from datetime import datetime
from datetime import timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from my_strategies.database.database_config import get_signal_db_config
from my_strategies.database.database_connection import ClickHouseConnection


# Load environment variables from .env file in project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")


def load_binance_klines_daily(
    symbol: str | None = None,
    interval: str = "1h",
    start_date: str | None = None,
    end_date: str | None = None,
    save_to_file: bool = True,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Load Binance perpetual klines data filtered for 00:00 UTC and optionally save to parquet."""
    # Get database config and connect
    config = get_signal_db_config()
    conn = ClickHouseConnection(config)

    # Build query with filters
    # IMPORTANT: Convert to UTC timezone before filtering to ensure we get 00:00 UTC, not 00:00 local time
    query = """
    SELECT
        symbol,
        exchange,
        interval,
        toTimeZone(timestamp, 'UTC') as timestamp,
        type,
        toTimeZone(close_time, 'UTC') as close_time,
        open,
        high,
        low,
        close,
        volume,
        quote_volume,
        taker_buy_volume,
        taker_buy_quote_volume,
        trades_count
    FROM binance.bn_perp_klines
    WHERE toHour(toTimeZone(timestamp, 'UTC')) = 0
      AND toMinute(toTimeZone(timestamp, 'UTC')) = 0
      AND toSecond(toTimeZone(timestamp, 'UTC')) = 0
    """

    params = {}

    # Add symbol filter if provided
    if symbol is not None:
        query += " AND symbol = %(symbol)s"
        params["symbol"] = symbol

    # Add interval filter
    query += " AND interval = %(interval)s"
    params["interval"] = interval

    # Add date range filters
    if start_date is not None:
        query += " AND timestamp >= %(start_date)s"
        params["start_date"] = start_date

    if end_date is not None:
        query += " AND timestamp <= %(end_date)s"
        params["end_date"] = end_date

    # Add ORDER BY and LIMIT at the end
    query += " ORDER BY timestamp ASC"
    # Uncomment the line below to limit results (useful for testing)
    # query += " LIMIT 100"

    try:
        # Execute query and get results
        results = conn.execute(query, params)

        # Column names based on actual schema
        columns = [
            "symbol",
            "exchange",
            "interval",
            "timestamp",
            "type",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "trades_count",
        ]

        # Create DataFrame
        df = pd.DataFrame(results, columns=columns)

        # Convert timestamps to datetime if they're not already
        if "timestamp" in df.columns and not pd.api.types.is_datetime64_any_dtype(
            df["timestamp"]
        ):
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        if "close_time" in df.columns and not pd.api.types.is_datetime64_any_dtype(
            df["close_time"]
        ):
            df["close_time"] = pd.to_datetime(df["close_time"])

        # Save to parquet if requested
        if save_to_file and len(df) > 0:
            # Use default data directory if not specified
            if output_dir is None:
                output_path = Path(__file__).parent.parent / "data"
            else:
                output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate filename
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")  # noqa: UP017
            symbol_part = symbol if symbol else "all_symbols"
            filename = f"binance_{symbol_part}_{interval}_daily_{timestamp_str}.parquet"
            file_path = output_path / filename

            df.to_parquet(file_path, index=False)
            print(f"\nSaved to: {file_path}")

        return df

    finally:
        conn.disconnect()


def get_unique_symbols(interval: str = "1h") -> list[str]:
    """Get list of all unique symbols in the database for a given interval."""
    config = get_signal_db_config()
    conn = ClickHouseConnection(config)

    query = """
    SELECT DISTINCT symbol
    FROM binance.bn_perp_klines
    WHERE interval = %(interval)s
    ORDER BY symbol ASC
    """

    try:
        results = conn.execute(query, {"interval": interval})
        return [row[0] for row in results]
    finally:
        conn.disconnect()


def verify_timezone(df: pd.DataFrame) -> None:
    """Verify that all timestamps are at 00:00:00 UTC."""
    if len(df) == 0:
        print("No data to verify")
        return

    print("\n" + "=" * 80)
    print("TIMEZONE VERIFICATION")
    print("=" * 80)

    # Check hours, minutes, seconds
    hours = df["timestamp"].dt.hour.unique()
    minutes = df["timestamp"].dt.minute.unique()
    seconds = df["timestamp"].dt.second.unique()

    print(f"Unique hours in data: {sorted(hours)}")
    print(f"Unique minutes in data: {sorted(minutes)}")
    print(f"Unique seconds in data: {sorted(seconds)}")

    if len(hours) == 1 and hours[0] == 0 and len(minutes) == 1 and minutes[0] == 0:
        print("✓ PASSED: All timestamps are at 00:00:00 UTC")
    else:
        print("✗ FAILED: Timestamps are NOT at 00:00:00 UTC")

    print("\nSample timestamps:")
    print(df[["symbol", "timestamp"]].head(5))


if __name__ == "__main__":
    # Configuration
    INTERVAL = "1h"
    START_DATE = "2025-01-01"
    END_DATE = "2025-12-31"

    print("=" * 80)
    print("BINANCE KLINES DATA LOADER")
    print("=" * 80)
    print(f"Interval: {INTERVAL}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print("Filter: 00:00 UTC timestamps only")
    print("Output: /Users/mikey/Desktop/nautilus_trader/my_strategies/data/")
    print("=" * 80)

    # Get all unique symbols
    print("\nFetching unique symbols from database...")
    symbols = get_unique_symbols(interval=INTERVAL)
    print(f"Found {len(symbols)} unique symbols")

    # Loop through each symbol and generate parquet file
    print("\nGenerating parquet files for each symbol...\n")
    successful = 0
    failed = 0

    for i, symbol in enumerate(symbols, 1):
        try:
            print(f"[{i}/{len(symbols)}] Processing {symbol}...")
            df = load_binance_klines_daily(
                symbol=symbol,
                interval=INTERVAL,
                start_date=START_DATE,
                end_date=END_DATE,
                save_to_file=True,
                output_dir=None,  # Uses default: my_strategies/data/
            )

            if len(df) > 0:
                print(f"  ✓ Loaded {len(df)} rows")
                successful += 1
            else:
                print(f"  ⚠ No data found")

        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed += 1

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total symbols: {len(symbols)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print("Output directory: /Users/mikey/Desktop/nautilus_trader/my_strategies/data/")
    print("=" * 80)
