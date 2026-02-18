"""Unified backtest runner for all venues."""

import argparse
from datetime import UTC
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fill_model import FixedBpsSlippageFillModel
from strategy import MyStrategy
from strategy import MyStrategyConfig

from my_analysis import TearsheetConfig
from my_analysis import create_tearsheet
from my_strategies.utils import BINANCE
from my_strategies.utils import HYPERLIQUID
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


VENUE_CONFIGS = {
    "binance": {"venue": BINANCE, "name": "Binance"},
    "hyperliquid": {"venue": HYPERLIQUID, "name": "Hyperliquid"},
}

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_LOG_DIR = Path(__file__).parent.parent / "logs"
SIGNALS_PATH = (
    DEFAULT_DATA_DIR / "signal" / "signals_2024-12-01_2026-02-13_20260213_015447.parquet"
)

def run_backtest(
    venue_key: str,
    signals_path: Path = SIGNALS_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    log_dir: Path = DEFAULT_LOG_DIR,
    start_capital: float = 100_000,
    fixed_slippage_bps: float = 5.0,
    start_date: datetime | None = None,
    bar_spec: str = "1-HOUR",
    external_data_dir: Path | None = None,
) -> None:
    venue_config = VENUE_CONFIGS[venue_key]
    venue = venue_config["venue"]

    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    engine_config = BacktestEngineConfig(
        trader_id=TraderId("BACKTEST-001"),
        logging=LoggingConfig(
            log_level="ERROR",
            log_level_file="INFO",
            log_directory=str(log_dir),
            log_file_name=f"backtest_{venue_key}_{timestamp}",
        ),
    )
    engine = BacktestEngine(config=engine_config)

    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(start_capital, USDT)],
        base_currency=USDT,
        default_leverage=Decimal(1),
        fill_model=FixedBpsSlippageFillModel(slippage_bps=fixed_slippage_bps),
        use_message_queue=False,
    )

    symbols = get_available_symbols(signals_path, data_dir, venue=venue_key, external_data_dir=external_data_dir)
    print(f"Found {len(symbols)} symbols with matching data")

    # Load per-symbol precision specs (Hyperliquid metadata)
    instrument_specs = load_hyperliquid_instrument_specs()

    instruments = {}
    bar_types = {}
    all_bars = []

    for symbol in symbols:
        print(f"Loading {symbol}...")
        spec = instrument_specs.get(symbol, {})
        instrument = create_instrument(
            symbol,
            venue,
            price_precision=spec.get("price_precision", 2),
            size_precision=spec.get("size_precision", 8),
        )
        instruments[symbol] = instrument
        engine.add_instrument(instrument)

        bar_type = BarType.from_str(f"{instrument.id}-{bar_spec}-LAST-EXTERNAL")
        bar_types[symbol] = bar_type

        bars = load_bars(instrument, bar_type, data_dir, venue=venue_key, external_data_dir=external_data_dir)
        all_bars.extend(bars)
        print(f"  Loaded {len(bars)} bars")

    engine.add_data(all_bars)

    symbol_mapping = {sym: f"{sym}USDT-PERP" for sym in symbols}

    config = MyStrategyConfig(
        instrument_ids=tuple(inst.id for inst in instruments.values()),
        bar_types=tuple(bar_types.values()),
        signals_path=str(signals_path),
        symbol_mapping=symbol_mapping,
    )
    strategy = MyStrategy(config=config)
    engine.add_strategy(strategy)

    print("\nRunning backtest...")
    engine.run(start=start_date)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(engine.trader.generate_account_report(venue))
    print(engine.trader.generate_order_fills_report())
    print(engine.trader.generate_positions_report())
    print(f"\nLogs written to: {log_dir}/backtest_{venue_key}_{timestamp}.log")

    print("\n" + "=" * 60)
    print("GENERATING DETAILED REPORTS")
    print("=" * 60)

    daily_snapshots_df = strategy.get_daily_snapshots_df()
    daily_snapshots_path = log_dir / f"daily_positions_{timestamp}.csv"
    daily_snapshots_df.to_csv(daily_snapshots_path, index=False)
    print(f"Daily positions CSV: {daily_snapshots_path}")
    print(f"Total daily snapshots: {len(strategy.daily_snapshots)}")

    tearsheet_config = TearsheetConfig(theme="plotly_dark")
    tearsheet_path = log_dir / f"tearsheet_{venue_key}_{timestamp}.html"
    sample_instrument = next(iter(instruments.values()))
    taker_fee_bps = float(sample_instrument.taker_fee) * 10_000
    title = (
        f"JennyLauV6 | "
        f"Capital: ${start_capital:,.0f} | "
        f"Slippage: {fixed_slippage_bps} bps | "
        f"Taker Fee: {taker_fee_bps:.1f} bps | "
        f"Reserve: {config.capital_reserve_pct*100:.0f}% | "
        f"Min Order: ${config.min_order_notional:.0f} | "
        f"Signal Offset: {config.signal_offset_days}d"
    )
    create_tearsheet(
        engine,
        output_path=str(tearsheet_path),
        title=title,
        config=tearsheet_config,
    )
    print(f"Tearsheet written to: {tearsheet_path}")

    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run multi-asset backtest")
    parser.add_argument(
        "--venue",
        required=True,
        choices=list(VENUE_CONFIGS.keys()),
        help="Trading venue to backtest against",
    )
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
        default="1-HOUR",
        help="Bar spec string, e.g. '1-HOUR' or '1-MINUTE' (default: 1-HOUR)",
    )
    parser.add_argument(
        "--external-data-dir",
        type=Path,
        default=None,
        help="External data directory with {SYMBOL}USDT.parquet files",
    )
    args = parser.parse_args()

    bt_start_date = None
    if args.start_date:
        bt_start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=UTC)

    run_backtest(
        venue_key=args.venue,
        data_dir=args.data_dir,
        log_dir=args.log_dir,
        start_capital=args.capital,
        start_date=bt_start_date,
        bar_spec=args.bar_spec,
        external_data_dir=args.external_data_dir,
    )
