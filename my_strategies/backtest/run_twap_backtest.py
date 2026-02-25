"""TWAP backtest runner — executes rebalance orders via TWAP."""

import argparse
from functools import partial
from pathlib import Path

from my_strategies.backtest.engine_setup import DEFAULT_DATA_DIR
from my_strategies.backtest.engine_setup import DEFAULT_LOG_DIR
from my_strategies.backtest.engine_setup import SIGNALS_PATH
from my_strategies.backtest.engine_setup import add_common_args
from my_strategies.backtest.engine_setup import create_engine
from my_strategies.backtest.engine_setup import generate_reports
from my_strategies.backtest.engine_setup import load_bar_data
from my_strategies.backtest.engine_setup import load_instruments
from my_strategies.backtest.engine_setup import load_quote_volume_data
from my_strategies.backtest.engine_setup import parse_start_date
from my_strategies.backtest.engine_setup import print_results
from my_strategies.models.volume_scaled_fill_model import VolumeScaledSlippageFillModel
from my_strategies.strategies.twap_strategy import MyTWAPStrategy
from my_strategies.strategies.twap_strategy import MyTWAPStrategyConfig
from my_strategies.utils import load_bars_twap_window
from nautilus_trader.examples.algorithms.twap import TWAPExecAlgorithm


def run_twap_backtest(
    signals_path: Path = SIGNALS_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    log_dir: Path = DEFAULT_LOG_DIR,
    start_capital: float = 100_000,
    fixed_slippage_bps: float = 5.0,
    tier1_volume_pct: float = 0.10,
    start_date=None,
    bar_spec: str = "1-MINUTE",
    rebalance_hour: int = 0,
    twap_horizon_secs: float = 1800.0,
    twap_interval_secs: float = 60.0,
) -> None:
    fill_model = VolumeScaledSlippageFillModel(
        slippage_bps=fixed_slippage_bps,
        tier1_volume_pct=tier1_volume_pct,
    )
    engine, timestamp = create_engine(
        log_dir, "backtest_twap", start_capital, fill_model=fill_model,
    )

    instruments, bar_types = load_instruments(engine, signals_path, data_dir, bar_spec)
    load_bar_data(
        engine,
        instruments,
        bar_types,
        data_dir,
        loader_fn=partial(load_bars_twap_window, hour=rebalance_hour, window_end_hour=2),
    )

    print("\nLoading quote volume data...")
    quote_volumes = load_quote_volume_data(instruments, data_dir)

    symbol_mapping = {sym: f"{sym}USDT-PERP" for sym in instruments}
    config = MyTWAPStrategyConfig(
        instrument_ids=tuple(inst.id for inst in instruments.values()),
        bar_types=tuple(bar_types.values()),
        signals_path=str(signals_path),
        symbol_mapping=symbol_mapping,
        rebalance_hour=rebalance_hour,
        twap_horizon_secs=twap_horizon_secs,
        twap_interval_secs=twap_interval_secs,
    )
    strategy = MyTWAPStrategy(config=config)
    strategy.fill_model = fill_model
    strategy.quote_volumes = quote_volumes
    engine.add_strategy(strategy)
    engine.add_exec_algorithm(TWAPExecAlgorithm())

    print("\nRunning TWAP backtest...")
    engine.run(start=start_date)

    print_results(engine, log_dir, timestamp)

    sample_instrument = next(iter(instruments.values()))
    taker_fee_bps = float(sample_instrument.taker_fee) * 10_000
    title = (
        f"JennyLauV6 TWAP | "
        f"Slippage: {fixed_slippage_bps} bps (vol-scaled, tier1={tier1_volume_pct:.0%}) | "
        f"Taker Fee: {taker_fee_bps:.1f} bps | "
        f"Reserve: {config.capital_reserve_pct*100:.0f}% | "
        f"Min Order: ${config.min_order_notional:.0f} | "
        f"Signal Offset: {config.signal_offset_days}d | "
        f"Rebalance: {config.rebalance_hour:02d}:00 UTC | "
        f"TWAP: {config.twap_horizon_secs / 60:.0f}min horizon, "
        f"{config.twap_interval_secs:.0f}s interval"
    )
    generate_reports(engine, strategy, log_dir, timestamp, title)

    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run TWAP multi-asset backtest")
    add_common_args(parser, default_bar_spec="1-MINUTE")
    parser.add_argument(
        "--twap-horizon-secs",
        type=float,
        default=1800.0,
        help="TWAP execution horizon in seconds (default: 1800 = 30min)",
    )
    parser.add_argument(
        "--twap-interval-secs",
        type=float,
        default=60.0,
        help="TWAP order interval in seconds (default: 60 = 1min)",
    )
    parser.add_argument(
        "--tier1-volume-pct",
        type=float,
        default=0.10,
        help="Fraction of bar quote volume available at best price (default: 0.10)",
    )
    args = parser.parse_args()

    run_twap_backtest(
        data_dir=args.data_dir,
        log_dir=args.log_dir,
        start_capital=args.capital,
        fixed_slippage_bps=5.0,
        tier1_volume_pct=args.tier1_volume_pct,
        start_date=parse_start_date(args.start_date),
        bar_spec=args.bar_spec,
        rebalance_hour=args.rebalance_hour,
        twap_horizon_secs=args.twap_horizon_secs,
        twap_interval_secs=args.twap_interval_secs,
    )
