from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.data import FundingRateUpdate
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.persistence.wranglers import BarDataWrangler


BINANCE = Venue("BINANCE")
DATA_DIR = Path(__file__).parent.parent / "data"


BINANCE_DATA_SUBDIR = "binance_1m_perps_20241201_20260213"
BINANCE_FUNDING_SUBDIR = "binance_funding_rates"


def get_available_symbols(
    signals_path: Path,
    data_dir: Path | None = None,
) -> list[str]:
    if data_dir is None:
        data_dir = DATA_DIR

    signals_df = pd.read_parquet(signals_path)
    signal_symbols = set(signals_df["symbol"].unique())

    available = set()
    for f in (data_dir / BINANCE_DATA_SUBDIR).glob("*.parquet"):
        stem = f.stem  # e.g. "BTCUSDT"
        if stem.endswith("USDT"):
            available.add(stem[:-4])  # e.g. "BTC"

    return sorted(signal_symbols & available)


def load_bars_all(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path | None = None,
) -> list[Bar]:
    if data_dir is None:
        data_dir = DATA_DIR

    return _load_binance_bars(instrument, bar_type, data_dir)


def _load_binance_bars(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path,
) -> list[Bar]:
    df = _read_binance_parquet(instrument, data_dir)

    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


def load_bars_daily(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path | None = None,
    hour: int = 0,
) -> list[Bar]:
    """Lazy load bars at the rebalance hour only."""
    if data_dir is None:
        data_dir = DATA_DIR

    df = _read_binance_parquet(instrument, data_dir)
    df = df[(df.index.hour == hour) & (df.index.minute == 0)]

    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


def load_bars_twap_window(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path | None = None,
    hour: int = 0,
    window_end_hour: int = 2,
) -> list[Bar]:
    """Load minute-level bars within a daily window starting at rebalance hour.

    Keeps bars from ``hour`` up to (but not including) ``window_end_hour`` each
    day.  When ``window_end_hour <= hour`` the window is assumed to wrap past
    midnight (e.g. hour=23, window_end_hour=1 keeps hours 23 and 0).
    """
    if data_dir is None:
        data_dir = DATA_DIR

    df = _read_binance_parquet(instrument, data_dir)

    if window_end_hour > hour:
        df = df[(df.index.hour >= hour) & (df.index.hour < window_end_hour)]
    else:
        # Wrap around midnight
        df = df[(df.index.hour >= hour) | (df.index.hour < window_end_hour)]

    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


FUNDING_HOURS = {0, 8, 16}  # Binance funding settlement times (UTC)


def load_bars_eight_hourly(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path | None = None,
    hour: int = 0,
) -> list[Bar]:
    """Load bars at the rebalance hour and at each funding settlement hour (0, 8, 16 UTC)."""
    if data_dir is None:
        data_dir = DATA_DIR

    hours = FUNDING_HOURS | {hour}

    df = _read_binance_parquet(instrument, data_dir)
    df = df[df.index.hour.isin(hours) & (df.index.minute == 0)]

    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


def load_funding_rates(
    instrument: CryptoPerpetual,
    data_dir: Path | None = None,
) -> tuple[list[FundingRateUpdate], dict[int, float]]:
    """Load funding rate data for a symbol and return (updates, mark_prices_by_ts_nanos)."""
    if data_dir is None:
        data_dir = DATA_DIR

    symbol = str(instrument.raw_symbol)  # e.g. "BTCUSDT"
    filepath = data_dir / BINANCE_FUNDING_SUBDIR / f"{symbol}.parquet"
    if not filepath.exists():
        return [], {}

    df = pd.read_parquet(filepath)
    updates = []
    mark_prices = {}

    for _, row in df.iterrows():
        ts_nanos = int(row["timestamp"].value)  # pandas Timestamp -> nanoseconds
        rate = Decimal(str(row["funding_rate"]))
        mark_price = float(row["mark_price"])

        update = FundingRateUpdate(
            instrument_id=instrument.id,
            rate=rate,
            ts_event=ts_nanos,
            ts_init=ts_nanos,
        )
        updates.append(update)
        mark_prices[ts_nanos] = mark_price

    return updates, mark_prices


def load_quote_volumes(
    instrument: CryptoPerpetual,
    data_dir: Path | None = None,
) -> dict[int, float]:
    """Load per-minute quote volume keyed by timestamp nanos."""
    if data_dir is None:
        data_dir = DATA_DIR
    symbol = str(instrument.raw_symbol)  # e.g. "BTCUSDT"
    filepath = data_dir / BINANCE_DATA_SUBDIR / f"{symbol}.parquet"
    if not filepath.exists():
        return {}
    df = pd.read_parquet(filepath, columns=["timestamp", "quote_volume"])
    df["ts_nanos"] = df["timestamp"].astype("int64")
    return dict(zip(df["ts_nanos"], df["quote_volume"].astype(float)))


def _read_binance_parquet(
    instrument: CryptoPerpetual,
    data_dir: Path,
) -> pd.DataFrame:
    """Read and prepare a Binance parquet file as a timestamp-indexed OHLCV DataFrame."""
    symbol = str(instrument.raw_symbol)  # e.g. "BTCUSDT"
    filepath = data_dir / BINANCE_DATA_SUBDIR / f"{symbol}.parquet"
    if not filepath.exists():
        raise FileNotFoundError(f"No data file found for {symbol}")

    df = pd.read_parquet(filepath)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df[["open", "high", "low", "close", "volume"]] = df[
        ["open", "high", "low", "close", "volume"]
    ].astype(np.float64)
    df = df.set_index("timestamp")
    return df
