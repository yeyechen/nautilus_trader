"""Backtest runner — daily rebalance strategy with live ClickHouse data."""

import argparse
import time
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from decimal import Decimal

from my_strategies.backtest.backtest_api_upload import upload_backtest_results
from my_strategies.backtest.engine_setup import add_common_args
from my_strategies.backtest.engine_setup import create_instrument
from my_strategies.backtest.engine_setup import load_hyperliquid_instrument_specs
from my_strategies.models.fixed_bps_fill_model import FixedBpsSlippageFillModel
from my_strategies.strategies.strategy import MyStrategy
from my_strategies.strategies.strategy import MyStrategyConfig
from my_strategies.utils import BINANCE
from my_strategies.utils.clickhouse_data_utils import (
    fetch_signals_clickhouse,
    get_available_symbols_clickhouse,
    load_bars_daily_clickhouse,
)
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model import TraderId
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.objects import Money

START_DATE = "2024-12-01"


def run_backtest(
    start_capital: float = 100_000,
    fixed_slippage_bps: float = 5.0,
    start_date=None,
    bar_spec: str = "1-HOUR",
    rebalance_hour: int = 0,
    simulate_funding: bool = False,
    ch_start_date: str = START_DATE,
    ch_end_date: str | None = None,
) -> None:
    if ch_end_date is None:
        ch_end_date = datetime.now(UTC).strftime("%Y-%m-%d")

    # --- Fetch live signals from ClickHouse ---
    print("Fetching live signals from ClickHouse...")
    _, signals_path = fetch_signals_clickhouse(
        start_date=ch_start_date,
        end_date=ch_end_date,
    )

    engine_config = BacktestEngineConfig(
        trader_id=TraderId("BACKTEST-001"),
        logging=LoggingConfig(log_level="ERROR"),
    )
    engine = BacktestEngine(config=engine_config)
    fill_model = FixedBpsSlippageFillModel(slippage_bps=fixed_slippage_bps)
    engine.add_venue(
        venue=BINANCE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(start_capital, USDT)],
        base_currency=USDT,
        default_leverage=Decimal(1),
        fill_model=fill_model,
        use_message_queue=False,
    )

    # --- Resolve symbols from signals + ClickHouse availability ---
    print("Querying ClickHouse for available symbols...")
    symbols = get_available_symbols_clickhouse(signals_path, interval="1h")
    print(f"Found {len(symbols)} symbols with matching data in ClickHouse")

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

    # --- Load bar data from ClickHouse ---
    all_bars = []
    for symbol, instrument in instruments.items():
        print(f"Loading {symbol} from ClickHouse...")
        bar_type = bar_types[symbol]
        bars = load_bars_daily_clickhouse(
            instrument,
            bar_type,
            hour=rebalance_hour,
            start_date=ch_start_date,
            end_date=ch_end_date,
        )
        all_bars.extend(bars)
        print(f"  Loaded {len(bars)} bars")

    engine.add_data(all_bars)

    # --- Funding (not yet migrated to ClickHouse) ---
    mark_prices = {}
    if simulate_funding:
        print("WARNING: Funding rate simulation not yet supported with ClickHouse data source.")

    symbol_mapping = {sym: f"{sym}USDT-PERP" for sym in instruments}
    config = MyStrategyConfig(
        instrument_ids=tuple(inst.id for inst in instruments.values()),
        bar_types=tuple(bar_types.values()),
        signals_path=str(signals_path),
        symbol_mapping=symbol_mapping,
        rebalance_hour=rebalance_hour,
        funding_mark_prices=mark_prices,
    )
    strategy = MyStrategy(config=config)
    engine.add_strategy(strategy)

    print("\nRunning backtest...")
    engine.run(start=start_date)

    # --- Upload results to teammate's API ---
    upload_backtest_results(engine, strategy)

    engine.dispose()


def wait_until_next_run(run_hour: int = 3, tz=None) -> None:
    """Sleep until the next scheduled run time."""
    if tz is None:
        tz = UTC
    now = datetime.now(tz)
    today_run = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    next_run = today_run if now < today_run else today_run + timedelta(days=1)
    seconds_to_sleep = (next_run - now).total_seconds()
    if seconds_to_sleep > 0:
        hours_left = seconds_to_sleep / 3600
        print(
            f"Waiting until next run at {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"({hours_left:.2f} hours)..."
        )
        time.sleep(seconds_to_sleep)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run multi-asset backtest (ClickHouse data)")
    add_common_args(parser)
    parser.add_argument(
        "--ch-start-date",
        type=str,
        default=START_DATE,
        help=f"ClickHouse query start date YYYY-MM-DD (default: {START_DATE})",
    )
    parser.add_argument(
        "--ch-end-date",
        type=str,
        default=None,
        help="ClickHouse query end date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously, sleeping until --run-hour each day",
    )
    parser.add_argument(
        "--run-hour",
        type=int,
        default=3,
        help="Hour of day (UTC) to run when using --loop (default: 3)",
    )
    args = parser.parse_args()

    while True:
        run_backtest(
            start_capital=args.capital,
            fixed_slippage_bps=args.fixed_slippage_bps,
            start_date=None,
            bar_spec=args.bar_spec,
            rebalance_hour=args.rebalance_hour,
            simulate_funding=args.simulate_funding,
            ch_start_date=args.ch_start_date,
            ch_end_date=args.ch_end_date,
        )
        if not args.loop:
            break
        wait_until_next_run(run_hour=args.run_hour)
