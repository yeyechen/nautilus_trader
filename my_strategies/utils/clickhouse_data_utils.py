"""Data loading utilities backed by ClickHouse instead of local parquet files."""

from datetime import UTC
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from my_strategies.database.database_config import get_signal_db_config
from my_strategies.database.database_connection import ClickHouseConnection
from my_strategies.signal_handler import get_signal_handler_config
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.persistence.wranglers import BarDataWrangler


# Load environment variables from .env file in project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")


def _query_clickhouse_klines(
    symbol: str,
    interval: str = "1h",
    start_date: str | None = None,
    end_date: str | None = None,
    hour_filter: int | None = None,
) -> pd.DataFrame:
    """Query ClickHouse for klines data and return an OHLCV DataFrame indexed by timestamp.

    Parameters
    ----------
    symbol : str
        Trading pair symbol, e.g. "BTCUSDT".
    interval : str
        Kline interval, e.g. "1h", "1m".
    start_date : str, optional
        Start date filter in "YYYY-MM-DD" format.
    end_date : str, optional
        End date filter in "YYYY-MM-DD" format.
    hour_filter : int, optional
        If provided, only return bars at this UTC hour (minute == 0).

    Returns
    -------
    pd.DataFrame
        DataFrame with timestamp index and columns: open, high, low, close, volume.
    """
    config = get_signal_db_config()
    conn = ClickHouseConnection(config)

    query = """
    SELECT
        toTimeZone(timestamp, 'UTC') as timestamp,
        open,
        high,
        low,
        close,
        volume
    FROM binance.bn_perp_klines
    WHERE symbol = %(symbol)s
      AND interval = %(interval)s
    """
    params: dict = {"symbol": symbol, "interval": interval}

    if hour_filter is not None:
        query += " AND toHour(toTimeZone(timestamp, 'UTC')) = %(hour)s"
        query += " AND toMinute(toTimeZone(timestamp, 'UTC')) = 0"
        params["hour"] = hour_filter

    if start_date is not None:
        query += " AND timestamp >= %(start_date)s"
        params["start_date"] = start_date

    if end_date is not None:
        query += " AND timestamp <= %(end_date)s"
        params["end_date"] = end_date

    query += " ORDER BY timestamp ASC"

    try:
        results = conn.execute(query, params)
        columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(results, columns=columns)

        if len(df) == 0:
            return df

        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype(np.float64)
        df = df.set_index("timestamp")
        return df
    finally:
        conn.disconnect()


def get_available_symbols_clickhouse(
    signals_path: Path,
    interval: str = "1h",
) -> list[str]:
    """Get symbols that exist in both the signal file and ClickHouse."""
    signals_df = pd.read_parquet(signals_path)
    signal_symbols = sorted(signals_df["symbol"].unique())

    config = get_signal_db_config()
    conn = ClickHouseConnection(config)
    try:
        results = conn.execute(
            "SELECT DISTINCT symbol FROM binance.bn_perp_klines WHERE interval = %(interval)s",
            {"interval": interval},
        )
        ch_symbols = {row[0] for row in results}
    finally:
        conn.disconnect()

    # Signal symbols are base (e.g. "BTC"), ClickHouse has "BTCUSDT"
    available = []
    for sym in signal_symbols:
        if f"{sym}USDT" in ch_symbols:
            available.append(sym)
    return sorted(available)


def load_bars_daily_clickhouse(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    hour: int = 0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Bar]:
    """Load daily bars at a specific UTC hour from ClickHouse."""
    symbol = str(instrument.raw_symbol)  # e.g. "BTCUSDT"
    df = _query_clickhouse_klines(
        symbol=symbol,
        interval="1h",
        start_date=start_date,
        end_date=end_date,
        hour_filter=hour,
    )
    if len(df) == 0:
        return []
    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


def fetch_signals_clickhouse(
    start_date: str = "2024-12-01",
    end_date: str | None = None,
) -> tuple[pd.DataFrame, Path]:
    """Fetch latest signals from ClickHouse and save to a temp parquet file.

    Returns
    -------
    tuple[pd.DataFrame, Path]
        The signals DataFrame and the path to the saved parquet file.
    """
    if end_date is None:
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")

    signal_config = get_signal_handler_config()
    db_config = get_signal_db_config()
    conn = ClickHouseConnection(db_config)

    table = f"{signal_config.signal_database_name}.{signal_config.signal_table_name}"

    query = f"""
    WITH latest_inserts AS (
        SELECT
            toDate(date) AS signal_date,
            max(inserted_at) AS max_inserted_at
        FROM {table}
        WHERE weight IS NOT NULL
        AND NOT isNaN(toFloat64(weight))
        AND toDate(date) >= toDate(%(start_date)s)
        AND toDate(date) <= toDate(%(end_date)s)
        GROUP BY toDate(date)
    )
    SELECT
        t.date AS date,
        UPPER(t.symbol) AS symbol,
        toFloat64(t.weight) AS weight,
        toTimeZone(t.inserted_at, 'UTC') AS inserted_at
    FROM {table} t
    INNER JOIN latest_inserts li
        ON toDate(t.date) = li.signal_date
        AND t.inserted_at = li.max_inserted_at
    WHERE t.weight IS NOT NULL
    AND NOT isNaN(toFloat64(t.weight))
    ORDER BY date ASC, symbol ASC
    """  # noqa: S608

    params = {"start_date": start_date, "end_date": end_date}

    try:
        results = conn.execute(query, params)
        columns = ["date", "symbol", "weight", "inserted_at"]
        df = pd.DataFrame(results, columns=columns)

        if "date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"])
        if "inserted_at" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["inserted_at"]):
            df["inserted_at"] = pd.to_datetime(df["inserted_at"])

        # Save to data/signals/ directory
        output_dir = Path(__file__).parent.parent / "data" / "signals"
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"signals_live_{start_date}_{end_date}.parquet"
        df.to_parquet(file_path, index=False)

        print(f"Fetched {len(df)} signal records ({df['date'].min().date()} to {df['date'].max().date()})")
        print(f"  Unique symbols: {df['symbol'].nunique()}, Unique dates: {df['date'].dt.date.nunique()}")
        print(f"  Saved to: {file_path}")

        return df, file_path
    finally:
        conn.disconnect()


def load_bars_all_clickhouse(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    interval: str = "1h",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Bar]:
    """Load all bars from ClickHouse (no hour filter)."""
    symbol = str(instrument.raw_symbol)
    df = _query_clickhouse_klines(
        symbol=symbol,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
    )
    if len(df) == 0:
        return []
    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)
