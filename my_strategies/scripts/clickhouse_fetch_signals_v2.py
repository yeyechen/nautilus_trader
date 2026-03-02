from datetime import UTC
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from my_strategies.database import ClickHouseConnection
from my_strategies.database import get_signal_db_config
from my_strategies.signal_handler import get_signal_v2_handler_config


load_dotenv(Path(__file__).parent.parent.parent / ".env")


def fetch_signals_v2_for_date_range(
    start_date: str,
    end_date: str,
    save_to_file: bool = True,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Fetch latest signals for each day in the date range from the v2 signal table."""
    signal_config = get_signal_v2_handler_config()
    db_config = get_signal_db_config()
    conn = ClickHouseConnection(db_config)

    table = f"{signal_config.signal_database_name}.{signal_config.signal_table_name}"

    query = f"""
    WITH latest_inserts AS (
        SELECT
            toDate(timestamp) AS signal_date,
            max(inserted_at) AS max_inserted_at
        FROM {table}
        WHERE weight IS NOT NULL
        AND NOT isNaN(toFloat64(weight))
        AND toDate(timestamp) >= toDate(%(start_date)s)
        AND toDate(timestamp) <= toDate(%(end_date)s)
        AND strategy_id = 'v2_ch_rf_combo_dow7'
        GROUP BY toDate(timestamp)
    )
    SELECT
        t.timestamp AS timestamp,
        UPPER(t.symbol) AS symbol,
        toFloat64(t.weight) AS weight,
        toTimeZone(t.inserted_at, 'UTC') AS inserted_at
    FROM {table} t
    INNER JOIN latest_inserts li
        ON toDate(t.timestamp) = li.signal_date
        AND t.inserted_at = li.max_inserted_at
    WHERE t.weight IS NOT NULL
    AND NOT isNaN(toFloat64(t.weight))
    AND t.strategy_id = 'v2_ch_rf_combo_dow7'
    ORDER BY timestamp ASC, symbol ASC
    """  # noqa: S608

    params = {"start_date": start_date, "end_date": end_date}

    try:
        results = conn.execute(query, params)
        columns = ["timestamp", "symbol", "weight", "inserted_at"]
        df = pd.DataFrame(results, columns=columns)

        if "timestamp" in df.columns and not pd.api.types.is_datetime64_any_dtype(
            df["timestamp"]
        ):
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        # Convert timestamp to date column for compatibility with strategy
        if "timestamp" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.normalize()
            df = df.drop(columns=["timestamp"])
        if "inserted_at" in df.columns and not pd.api.types.is_datetime64_any_dtype(
            df["inserted_at"]
        ):
            df["inserted_at"] = pd.to_datetime(df["inserted_at"])

        if save_to_file and len(df) > 0:
            if output_dir is None:
                output_path = Path(__file__).parent.parent / "data" / "signals"
            else:
                output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            timestamp_str = datetime.now(UTC).strftime(
                "%Y%m%d_%H%M%S"
            )  # noqa: UP017
            filename = f"signals_v2_{start_date}_{end_date}_{timestamp_str}.parquet"
            file_path = output_path / filename

            df.to_parquet(file_path, index=False)
            print(f"Saved to: {file_path}")

        return df

    finally:
        conn.disconnect()


if __name__ == "__main__":
    START_DATE = "2024-12-01"
    END_DATE = datetime.now(UTC).strftime("%Y-%m-%d")

    print("=" * 60)
    print("SIGNAL V2 DATA FETCHER")
    print("=" * 60)
    print(f"Date range: {START_DATE} to {END_DATE}")
    print("=" * 60)

    df = fetch_signals_v2_for_date_range(
        start_date=START_DATE,
        end_date=END_DATE,
        save_to_file=True,
    )

    print(f"\nFetched {len(df)} signal records")
    if len(df) > 0:
        print(f"Date range in data: {df['date'].min()} to {df['date'].max()}")
        print(f"Unique dates: {df['date'].dt.date.nunique()}")
        print(f"Unique symbols: {df['symbol'].nunique()}")
