from datetime import UTC
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from strategy import MyStrategy
from strategy import MyStrategyConfig

from my_strategies.utils import configure_crypto_statistics
from my_strategies.utils import create_instrument
from my_strategies.utils import get_available_symbols
from my_strategies.utils import load_bars
from nautilus_trader.analysis import create_tearsheet
from nautilus_trader.analysis.config import GridLayout
from nautilus_trader.analysis.config import TearsheetConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model import TraderId
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money


BINANCE = Venue("BINANCE")
DATA_DIR = Path(__file__).parent.parent / "data"
LOG_DIR = Path(__file__).parent.parent / "logs"
SIGNALS_PATH = (
    DATA_DIR / "signal" / "signals_2025-01-01_2026-01-31_20260131_065633.parquet"
)
START_CAPITAL = 10_000

if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    engine_config = BacktestEngineConfig(
        trader_id=TraderId("BACKTEST-001"),
        logging=LoggingConfig(
            log_level="ERROR",
            log_level_file="INFO",
            log_directory=str(LOG_DIR),
            log_file_name=f"backtest_binance_{timestamp}",
        ),
    )
    engine = BacktestEngine(config=engine_config)
    configure_crypto_statistics(engine)  # Use 365-day annualization for crypto

    engine.add_venue(
        venue=BINANCE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(START_CAPITAL, USDT)],
        base_currency=USDT,
        default_leverage=Decimal(1),
    )

    symbols = get_available_symbols(SIGNALS_PATH, DATA_DIR, venue="binance")
    print(f"Found {len(symbols)} symbols with matching data")

    instruments = {}
    bar_types = {}
    all_bars = []

    for symbol in symbols:
        print(f"Loading {symbol}...")
        instrument = create_instrument(symbol, BINANCE)
        instruments[symbol] = instrument
        engine.add_instrument(instrument)

        bar_type = BarType.from_str(f"{instrument.id}-1-HOUR-LAST-EXTERNAL")
        bar_types[symbol] = bar_type

        bars = load_bars(instrument, bar_type, DATA_DIR, venue="binance")
        all_bars.extend(bars)
        print(f"  Loaded {len(bars)} bars")

    engine.add_data(all_bars)

    symbol_mapping = {sym: f"{sym}USDT-PERP" for sym in symbols}

    config = MyStrategyConfig(
        instrument_ids=tuple(inst.id for inst in instruments.values()),
        bar_types=tuple(bar_types.values()),
        signals_path=str(SIGNALS_PATH),
        symbol_mapping=symbol_mapping,
    )
    strategy = MyStrategy(config=config)
    engine.add_strategy(strategy)

    print("\nRunning backtest...")
    engine.run()

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(engine.trader.generate_account_report(BINANCE))
    print(engine.trader.generate_order_fills_report())
    print(engine.trader.generate_positions_report())
    print(f"\nLogs written to: {LOG_DIR}/backtest_binance_{timestamp}.log")
    # Generate positions CSV for detailed analysis
    print("\n" + "=" * 60)
    print("GENERATING DETAILED REPORTS")
    print("=" * 60)

    # Generate daily position snapshots CSV
    daily_snapshots_df = strategy.get_daily_snapshots_df()
    daily_snapshots_path = LOG_DIR / f"daily_positions_{timestamp}.csv"
    daily_snapshots_df.to_csv(daily_snapshots_path, index=False)
    print(f"Daily positions CSV: {daily_snapshots_path}")
    print(f"Total daily snapshots: {len(strategy.daily_snapshots)}")

    tearsheet_config = TearsheetConfig(
        theme="plotly_dark",
        height=1800,
        show_logo=False,
        layout=GridLayout(
            rows=4,
            cols=2,
            heights=[0.40, 0.25, 0.20, 0.15],
            vertical_spacing=0.08,
            horizontal_spacing=0.08,
        ),
    )
    tearsheet_path = LOG_DIR / f"tearsheet_binance_{timestamp}.html"
    create_tearsheet(
        engine,
        output_path=str(tearsheet_path),
        title="Hyperliquid Multi-Asset Strategy - binance candle",
        config=tearsheet_config,
    )
    print(f"Tearsheet written to: {tearsheet_path}")

    engine.dispose()
