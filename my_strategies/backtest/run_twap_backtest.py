"""TWAP backtest runner — executes rebalance orders via TWAP."""

import argparse
from pathlib import Path

from my_strategies.backtest.engine_setup import DEFAULT_DATA_DIR
from my_strategies.backtest.engine_setup import DEFAULT_LOG_DIR
from my_strategies.backtest.engine_setup import SIGNALS_PATH
from my_strategies.backtest.engine_setup import add_common_args
from my_strategies.backtest.engine_setup import create_engine
from my_strategies.backtest.engine_setup import generate_reports
from my_strategies.backtest.engine_setup import load_instruments_and_bars
from my_strategies.backtest.engine_setup import parse_start_date
from my_strategies.backtest.engine_setup import print_results
from my_strategies.strategies.twap_strategy import MyTWAPStrategy
from my_strategies.strategies.twap_strategy import MyTWAPStrategyConfig
from nautilus_trader.examples.algorithms.twap import TWAPExecAlgorithm


def run_twap_backtest(
    signals_path: Path = SIGNALS_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    log_dir: Path = DEFAULT_LOG_DIR,
    start_capital: float = 100_000,
    fixed_slippage_bps: float = 5.0,
    start_date=None,
    bar_spec: str = "1-MINUTE",
) -> None:
    engine, timestamp = create_engine(log_dir, "backtest_twap", start_capital, fixed_slippage_bps)

    instruments, bar_types = load_instruments_and_bars(
        engine, signals_path, data_dir, bar_spec,
    )

    symbol_mapping = {sym: f"{sym}USDT-PERP" for sym in instruments}
    config = MyTWAPStrategyConfig(
        instrument_ids=tuple(inst.id for inst in instruments.values()),
        bar_types=tuple(bar_types.values()),
        signals_path=str(signals_path),
        symbol_mapping=symbol_mapping,
    )
    strategy = MyTWAPStrategy(config=config)
    engine.add_strategy(strategy)
    engine.add_exec_algorithm(TWAPExecAlgorithm())

    print("\nRunning TWAP backtest...")
    engine.run(start=start_date)

    print_results(engine, log_dir, timestamp)

    sample_instrument = next(iter(instruments.values()))
    taker_fee_bps = float(sample_instrument.taker_fee) * 10_000
    title = (
        f"JennyLauV6 TWAP | "
        f"Capital: ${start_capital:,.0f} | "
        f"Slippage: {fixed_slippage_bps} bps | "
        f"Taker Fee: {taker_fee_bps:.1f} bps | "
        f"Reserve: {config.capital_reserve_pct*100:.0f}% | "
        f"Min Order: ${config.min_order_notional:.0f} | "
        f"Signal Offset: {config.signal_offset_days}d | "
        f"TWAP: {config.twap_horizon_secs / 60:.0f}min horizon, "
        f"{config.twap_interval_secs:.0f}s interval"
    )
    generate_reports(engine, strategy, log_dir, timestamp, title)

    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run TWAP multi-asset backtest")
    add_common_args(parser, default_bar_spec="1-MINUTE")
    args = parser.parse_args()

    run_twap_backtest(
        data_dir=args.data_dir,
        log_dir=args.log_dir,
        start_capital=args.capital,
        start_date=parse_start_date(args.start_date),
        bar_spec=args.bar_spec,
    )
