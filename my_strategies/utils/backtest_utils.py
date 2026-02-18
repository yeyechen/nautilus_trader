import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Currency
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.persistence.wranglers import BarDataWrangler


BINANCE = Venue("BINANCE")
HYPERLIQUID = Venue("HYPERLIQUID")
DATA_DIR = Path(__file__).parent.parent / "data"


def get_available_symbols(
    signals_path: Path,
    data_dir: Path | None = None,
    venue: str = "binance",
    external_data_dir: Path | None = None,
) -> list[str]:
    if data_dir is None:
        data_dir = DATA_DIR

    signals_df = pd.read_parquet(signals_path)
    signal_symbols = set(signals_df["symbol"].unique())

    available = set()
    if external_data_dir is not None:
        # External data: files named {BASE}USDT.parquet (e.g. BTCUSDT.parquet)
        for f in external_data_dir.glob("*.parquet"):
            stem = f.stem
            if stem.endswith("USDT"):
                available.add(stem[:-4])
    elif venue == "binance":
        for f in (data_dir / "binance").glob("*.parquet"):
            parts = f.stem.split("_")
            if len(parts) >= 2 and parts[1].endswith("USDT"):
                available.add(parts[1][:-4])
    elif venue == "hyperliquid":
        for f in (data_dir / "hyperliquid").glob("*.parquet"):
            parts = f.stem.split("_")
            if len(parts) >= 2:
                available.add(parts[1])

    return sorted(signal_symbols & available)


def create_instrument(
    base_symbol: str,
    venue: Venue | None = None,
    price_precision: int = 2,
    size_precision: int = 8,
    maker_fee: Decimal = Decimal("0.00015"), # Tier 0 maker fee in hyperliquid
    taker_fee: Decimal = Decimal("0.00045"), # Tier 0 taker fee in hyperliquid
) -> CryptoPerpetual:
    if venue is None:
        venue = BINANCE

    price_increment = Price(10 ** -price_precision, price_precision)
    size_increment = Quantity(10 ** -size_precision, size_precision)

    base_currency = Currency.from_str(base_symbol)
    return CryptoPerpetual(
        instrument_id=InstrumentId(Symbol(f"{base_symbol}USDT-PERP"), venue),
        raw_symbol=Symbol(f"{base_symbol}USDT"),
        base_currency=base_currency,
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=price_precision,
        price_increment=price_increment,
        size_precision=size_precision,
        size_increment=size_increment,
        max_quantity=None,
        min_quantity=None,
        max_notional=None,
        min_notional=None,
        max_price=Price.from_str("1000000.00"),
        min_price=price_increment,
        margin_init=Decimal("0.05"),
        margin_maint=Decimal("0.025"),
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        ts_event=0,
        ts_init=0,
    )


def load_bars(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path | None = None,
    venue: str = "binance",
    external_data_dir: Path | None = None,
) -> list[Bar]:
    if data_dir is None:
        data_dir = DATA_DIR

    if external_data_dir is not None:
        return _load_external_bars(instrument, bar_type, external_data_dir)
    elif venue == "binance":
        return _load_binance_bars(instrument, bar_type, data_dir)
    elif venue == "hyperliquid":
        return _load_hyperliquid_bars(instrument, bar_type, data_dir)
    else:
        raise ValueError(f"Unsupported venue: {venue}")


def _load_binance_bars(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path,
) -> list[Bar]:
    symbol = str(instrument.raw_symbol)
    pattern = f"binance_{symbol}_1h_daily_*.parquet"
    files = list((data_dir / "binance").glob(pattern))
    if not files:
        raise FileNotFoundError(f"No data file found for {symbol}")

    df = pd.read_parquet(files[0])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df[["open", "high", "low", "close", "volume"]] = df[
        ["open", "high", "low", "close", "volume"]
    ].astype(np.float64)
    df = df.set_index("timestamp")

    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


def _load_external_bars(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    external_data_dir: Path,
) -> list[Bar]:
    """Load bars from external data directory (files named {SYMBOL}USDT.parquet)."""
    symbol = str(instrument.raw_symbol)  # e.g. "BTCUSDT"
    filepath = external_data_dir / f"{symbol}.parquet"
    if not filepath.exists():
        raise FileNotFoundError(f"No data file found: {filepath}")

    df = pd.read_parquet(filepath)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df[["open", "high", "low", "close", "volume"]] = df[
        ["open", "high", "low", "close", "volume"]
    ].astype(np.float64)
    df = df.set_index("timestamp")

    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


def _load_hyperliquid_bars(
    instrument: CryptoPerpetual,
    bar_type: BarType,
    data_dir: Path,
) -> list[Bar]:
    # Extract base symbol (e.g., "BTC" from "BTCUSDT")
    raw_symbol = str(instrument.raw_symbol)
    base_symbol = raw_symbol.replace("USDT", "")

    pattern = f"hyperliquid_{base_symbol}_*.parquet"
    files = list((data_dir / "hyperliquid").glob(pattern))
    if not files:
        raise FileNotFoundError(f"No data file found for {base_symbol}")

    df = pd.read_parquet(files[0])

    # Hyperliquid has mid_px instead of OHLC, construct bars from it
    # For hourly snapshots, open=high=low=close=mid_px
    df = df.rename(columns={"time": "timestamp"})
    df["open"] = df["mid_px"].astype(np.float64)
    df["high"] = df["mid_px"].astype(np.float64)
    df["low"] = df["mid_px"].astype(np.float64)
    df["close"] = df["mid_px"].astype(np.float64)
    # Use day_ntl_vlm as volume proxy (notional volume)
    df["volume"] = df["day_ntl_vlm"].astype(np.float64)

    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df = df.set_index("timestamp")

    wrangler = BarDataWrangler(bar_type, instrument)
    return wrangler.process(df)


HYPERLIQUID_PX_MAX_DECIMALS = 6


def load_hyperliquid_instrument_specs(
    meta_path: Path | None = None,
) -> dict[str, dict]:
    """
    Load per-symbol size/price precision from Hyperliquid metadata JSON.

    Returns a dict keyed by symbol (e.g. "BTC") with keys:
        size_precision, price_precision
    """
    if meta_path is None:
        meta_path = DATA_DIR / "hyperliquid_meta_and_ctx" / "full_meta_and_ctx_20260109.json"

    with open(meta_path) as f:
        raw = json.load(f)

    meta = raw[0]  # [meta_dict, ctxs_list]
    specs: dict[str, dict] = {}
    for asset in meta["universe"]:
        symbol = asset["name"]
        sz_decimals = int(asset["szDecimals"])
        px_decimals = max(0, HYPERLIQUID_PX_MAX_DECIMALS - sz_decimals)
        specs[symbol] = {
            "size_precision": sz_decimals,
            "price_precision": px_decimals,
        }
    return specs
