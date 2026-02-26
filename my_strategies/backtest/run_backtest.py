"""Backtest runner — daily rebalance strategy."""

import argparse
from functools import partial
from pathlib import Path

from my_strategies.backtest.engine_setup import DEFAULT_DATA_DIR
from my_strategies.backtest.engine_setup import DEFAULT_LOG_DIR
from my_strategies.backtest.engine_setup import SIGNAL_NAMES
from my_strategies.backtest.engine_setup import SIGNALS_PATH
from my_strategies.backtest.engine_setup import add_common_args
from my_strategies.backtest.engine_setup import create_engine
from my_strategies.backtest.engine_setup import generate_reports
from my_strategies.backtest.engine_setup import load_bar_data
from my_strategies.backtest.engine_setup import load_funding_data
from my_strategies.backtest.engine_setup import load_instruments
from my_strategies.backtest.engine_setup import parse_start_date
from my_strategies.backtest.engine_setup import print_results
from my_strategies.strategies.strategy import MyStrategy
from my_strategies.strategies.strategy import MyStrategyConfig
from my_strategies.utils import load_bars_daily


def run_backtest(
    signals_path: Path = SIGNALS_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    log_dir: Path = DEFAULT_LOG_DIR,
    start_capital: float = 100_000,
    fixed_slippage_bps: float = 5.0,
    start_date=None,
    bar_spec: str = "1-HOUR",
    rebalance_hour: int = 0,
    simulate_funding: bool = False,
) -> None:
    engine, timestamp = create_engine(log_dir, "backtest", start_capital, fixed_slippage_bps)

    instruments, bar_types = load_instruments(engine, signals_path, data_dir, bar_spec)
    load_bar_data(engine, instruments, bar_types, data_dir, loader_fn=partial(load_bars_daily, hour=rebalance_hour))

    mark_prices = {}
    if simulate_funding:
        mark_prices = load_funding_data(engine, instruments, data_dir)

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

    print_results(engine, log_dir, timestamp)

    sample_instrument = next(iter(instruments.values()))
    taker_fee_bps = float(sample_instrument.taker_fee) * 10_000
    signal_name = SIGNAL_NAMES.get(signals_path, signals_path.stem)
    title = (
        f"{signal_name} | "
        f"Slippage: {fixed_slippage_bps} bps | "
        f"Taker Fee: {taker_fee_bps:.1f} bps | "
        f"Reserve: {config.capital_reserve_pct*100:.0f}% | "
        f"Min Order: ${config.min_order_notional:.0f} | "
        f"Signal Offset: {config.signal_offset_days}d | "
        f"Rebalance: {config.rebalance_hour:02d}:00 UTC"
    )
    generate_reports(engine, strategy, log_dir, timestamp, title)

    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run multi-asset backtest")
    add_common_args(parser)
    args = parser.parse_args()

    run_backtest(
        data_dir=args.data_dir,
        log_dir=args.log_dir,
        start_capital=args.capital,
        fixed_slippage_bps=args.fixed_slippage_bps,
        start_date=parse_start_date(args.start_date),
        bar_spec=args.bar_spec,
        rebalance_hour=args.rebalance_hour,
        simulate_funding=args.simulate_funding,
    )
