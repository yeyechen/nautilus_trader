"""Shared backtest engine setup, data loading, and reporting utilities."""

import argparse
import json
from datetime import UTC
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from my_strategies.analysis import TearsheetConfig
from my_strategies.analysis import create_tearsheet
from my_strategies.models.fill_model import FixedBpsSlippageFillModel
from my_strategies.utils import BINANCE
from my_strategies.utils import get_available_symbols
from my_strategies.utils import load_all_bars
from my_strategies.utils import load_funding_rates
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model import TraderId
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Currency
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity


DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_LOG_DIR = Path(__file__).parent.parent / "logs"
SIGNALS_PATH = (
    DEFAULT_DATA_DIR / "signal" / "signals_2024-12-01_2026-02-21_20260221_125721.parquet"
)


HYPERLIQUID_PX_MAX_DECIMALS = 6


def create_instrument(
    base_symbol: str,
    venue: Venue | None = None,
    price_precision: int = 2,
    size_precision: int = 8,
    maker_fee: Decimal = Decimal("0.00015"),  # Tier 0 maker fee in hyperliquid
    taker_fee: Decimal = Decimal("0.00045"),  # Tier 0 taker fee in hyperliquid
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


def load_hyperliquid_instrument_specs(
    meta_path: Path | None = None,
) -> dict[str, dict]:
    """
    Load per-symbol size/price precision from Hyperliquid metadata JSON.

    Returns a dict keyed by symbol (e.g. "BTC") with keys:
        size_precision, price_precision
    """
    if meta_path is None:
        meta_path = (
            Path(__file__).parent.parent / "data" / "hyperliquid_meta_and_ctx" / "full_meta_and_ctx_20260109.json"
        )

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


def create_engine(
    log_dir: Path,
    log_prefix: str,
    start_capital: float,
    fixed_slippage_bps: float = 5.0,
) -> tuple[BacktestEngine, str]:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    engine_config = BacktestEngineConfig(
        trader_id=TraderId("BACKTEST-001"),
        logging=LoggingConfig(
            log_level="ERROR",
            log_level_file="INFO",
            log_directory=str(log_dir),
            log_file_name=f"{log_prefix}_{timestamp}",
        ),
    )
    engine = BacktestEngine(config=engine_config)

    engine.add_venue(
        venue=BINANCE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(start_capital, USDT)],
        base_currency=USDT,
        default_leverage=Decimal(1),
        fill_model=FixedBpsSlippageFillModel(slippage_bps=fixed_slippage_bps),
        use_message_queue=False,
    )

    return engine, timestamp


def load_instruments(
    engine: BacktestEngine,
    signals_path: Path,
    data_dir: Path,
    bar_spec: str,
) -> tuple[dict, dict]:
    """Create instruments and bar_types, add instruments to engine. No bar data loaded."""
    symbols = get_available_symbols(signals_path, data_dir)
    print(f"Found {len(symbols)} symbols with matching data")

    instrument_specs = load_hyperliquid_instrument_specs()

    instruments = {}
    bar_types = {}

    for symbol in symbols:
        spec = instrument_specs.get(symbol, {})
        instrument = create_instrument(
            base_symbol=symbol,
            venue=BINANCE,
            price_precision=spec.get("price_precision", 2),
            size_precision=spec.get("size_precision", 8),
        )
        instruments[symbol] = instrument
        engine.add_instrument(instrument)

        bar_type = BarType.from_str(f"{instrument.id}-{bar_spec}-LAST-EXTERNAL")
        bar_types[symbol] = bar_type

    return instruments, bar_types


def load_bar_data(
    engine: BacktestEngine,
    instruments: dict,
    bar_types: dict,
    data_dir: Path,
    loader_fn=load_all_bars,
) -> None:
    """Load bar data for all instruments using the given loader function."""
    all_bars = []
    for symbol, instrument in instruments.items():
        print(f"Loading {symbol}...")
        bar_type = bar_types[symbol]
        bars = loader_fn(instrument, bar_type, data_dir)
        all_bars.extend(bars)
        print(f"  Loaded {len(bars)} bars")

    engine.add_data(all_bars)


def load_funding_data(
    engine: BacktestEngine,
    instruments: dict,
    data_dir: Path,
) -> dict[int, float]:
    """Load funding rate data for all instruments. Returns mark prices keyed by ts_event nanos."""
    all_updates = []
    all_mark_prices: dict[int, float] = {}

    for symbol, instrument in instruments.items():
        updates, mark_prices = load_funding_rates(instrument, data_dir)
        if updates:
            all_updates.extend(updates)
            all_mark_prices.update(mark_prices)
            print(f"  {symbol}: {len(updates)} funding rate records")

    if all_updates:
        engine.add_data(all_updates)
        print(f"Loaded {len(all_updates)} total funding rate records")
    else:
        print("No funding rate data found")

    return all_mark_prices


def print_results(engine: BacktestEngine, log_dir: Path, timestamp: str) -> None:
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(engine.trader.generate_account_report(BINANCE))
    print(engine.trader.generate_order_fills_report())
    print(engine.trader.generate_positions_report())
    print(f"\nLogs written to: {log_dir}/backtest_{timestamp}.log")


def generate_reports(
    engine: BacktestEngine,
    strategy,
    log_dir: Path,
    timestamp: str,
    title: str,
) -> None:
    print("\n" + "=" * 60)
    print("GENERATING DETAILED REPORTS")
    print("=" * 60)

    daily_snapshots_df = strategy.get_daily_snapshots_df()
    daily_snapshots_path = log_dir / f"daily_positions_{timestamp}.csv"
    daily_snapshots_df.to_csv(daily_snapshots_path, index=False)
    print(f"Daily positions CSV: {daily_snapshots_path}")
    print(f"Total daily snapshots: {len(strategy.daily_snapshots)}")

    tearsheet_config = TearsheetConfig(theme="plotly_dark")
    tearsheet_path = log_dir / f"tearsheet_{timestamp}.html"
    funding_cost = getattr(strategy, "cumulative_funding_cost", 0.0)
    create_tearsheet(
        engine,
        output_path=str(tearsheet_path),
        title=title,
        config=tearsheet_config,
        cumulative_funding_cost=funding_cost,
    )
    print(f"Tearsheet written to: {tearsheet_path}")


def add_common_args(parser: argparse.ArgumentParser, default_bar_spec: str = "1-HOUR") -> None:
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help=f"Log directory (default: {DEFAULT_LOG_DIR})",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000,
        help="Starting capital in USDT (default: 100000)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Backtest start date in YYYY-MM-DD format (default: use all data)",
    )
    parser.add_argument(
        "--bar-spec",
        type=str,
        default=default_bar_spec,
        help=f"Bar spec string, e.g. '1-HOUR' or '1-MINUTE' (default: {default_bar_spec})",
    )
    parser.add_argument(
        "--rebalance-hour",
        type=int,
        default=0,
        help="Hour of day (0-23 UTC) to rebalance (default: 0)",
    )


def parse_start_date(date_str: str | None) -> datetime | None:
    if date_str is None:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
