"""Shared backtest engine setup, data loading, and reporting utilities."""

import argparse
from datetime import UTC
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from my_strategies.analysis import TearsheetConfig
from my_strategies.analysis import create_tearsheet
from my_strategies.models.fill_model import FixedBpsSlippageFillModel
from my_strategies.utils import BINANCE
from my_strategies.utils import create_instrument
from my_strategies.utils import get_available_symbols
from my_strategies.utils import load_bars
from my_strategies.utils import load_hyperliquid_instrument_specs
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model import TraderId
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.objects import Money


DEFAULT_DATA_DIR = Path("/home/ra_yeye/2026_projects/data")
DEFAULT_LOG_DIR = Path(__file__).parent.parent / "logs"
SIGNALS_PATH = (
    DEFAULT_DATA_DIR / "signal" / "signals_2024-12-01_2026-02-21_20260221_125721.parquet"
)


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


def load_instruments_and_bars(
    engine: BacktestEngine,
    signals_path: Path,
    data_dir: Path,
    bar_spec: str,
) -> tuple[dict, dict]:
    symbols = get_available_symbols(signals_path, data_dir)
    print(f"Found {len(symbols)} symbols with matching data")

    instrument_specs = load_hyperliquid_instrument_specs()

    instruments = {}
    bar_types = {}
    all_bars = []

    for symbol in symbols:
        print(f"Loading {symbol}...")
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

        bars = load_bars(instrument, bar_type, data_dir)
        all_bars.extend(bars)
        print(f"  Loaded {len(bars)} bars")

    engine.add_data(all_bars)

    return instruments, bar_types


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
    create_tearsheet(
        engine,
        output_path=str(tearsheet_path),
        title=title,
        config=tearsheet_config,
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


def parse_start_date(date_str: str | None) -> datetime | None:
    if date_str is None:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
