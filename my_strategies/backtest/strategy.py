from datetime import timedelta

import pandas as pd

from my_strategies.signal_handler.signal_handler import SignalHandler
from nautilus_trader.common.enums import LogColor
from nautilus_trader.common.events import TimeEvent
from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy


class MyStrategyConfig(StrategyConfig, frozen=True):
    instrument_ids: tuple[InstrumentId, ...]
    bar_types: tuple[BarType, ...]
    signals_path: str
    symbol_mapping: dict[
        str, str
    ]  # signal symbol -> instrument symbol (e.g., "BTC" -> "BTCUSDT-PERP")
    capital_reserve_pct: float = 0.05  # 5% reserve, 95% capital in use
    min_order_notional: float = 10.0  # Minimum order value in USD
    signal_offset_days: int = 2  # Fetch signals from N days ago


class MyStrategy(Strategy):

    def __init__(self, config: MyStrategyConfig):
        super().__init__(config)
        self.instruments: dict[InstrumentId, Instrument] = {}
        self.instrument_id_map: dict[str, InstrumentId] = {}
        self.signals_df: pd.DataFrame = None
        self.last_prices: dict[InstrumentId, float] = {}
        # Daily position snapshots: list of dicts with date, positions, equity
        self.daily_snapshots: list[dict] = []

    def on_start(self):
        self.signals_df = pd.read_parquet(self.config.signals_path)
        self.signals_df["date"] = pd.to_datetime(self.signals_df["date"]).dt.date
        self.log.info(f"Loaded {len(self.signals_df)} signal records")

        for instrument_id in self.config.instrument_ids:
            instrument = self.cache.instrument(instrument_id)
            if instrument:
                self.instruments[instrument_id] = instrument
                symbol = str(instrument_id.symbol)  # e.g., "BTCUSDT-PERP"
                self.instrument_id_map[symbol] = instrument_id
            else:
                self.log.warning(f"Instrument not found: {instrument_id}")

        # Reverse: instrument_symbol -> signal_symbol (e.g., "BTCUSDT-PERP" -> "BTC")
        self.reverse_symbol_mapping: dict[str, str] = {
            v: k for k, v in self.config.symbol_mapping.items()
        }

        for bar_type in self.config.bar_types:
            self.subscribe_bars(bar_type)

        first_rebalance = self._get_first_rebalance_time()
        self.clock.set_timer(
            name="daily_rebalance",
            interval=pd.Timedelta(days=1),
            start_time=first_rebalance,
            callback=self.on_rebalance,
        )
        self.log.info(
            f"Strategy started - first rebalance at {first_rebalance}",
            color=LogColor.GREEN,
        )

    def _get_total_equity(self) -> float:
        """Return total equity including unrealized PnL (matches live account_value)."""
        venue = self.config.instrument_ids[0].venue
        account = self.portfolio.account(venue)
        balance = float(account.balance_total().as_double()) if account else 0.0
        unrealized_pnls = self.portfolio.unrealized_pnls(venue)
        if unrealized_pnls:
            balance += sum(float(pnl.as_double()) for pnl in unrealized_pnls.values())
        return balance

    def _get_first_rebalance_time(self) -> pd.Timestamp:
        now = self.clock.utc_now()
        today_midnight = now.normalize()
        if now <= today_midnight:
            return today_midnight
        return today_midnight + pd.Timedelta(days=1)

    def on_bar(self, bar: Bar):
        # Use bar.open (price at bar start) to match 00:00 UTC rebalance time
        self.last_prices[bar.bar_type.instrument_id] = float(bar.open)

    def on_rebalance(self, event: TimeEvent):
        current_time = unix_nanos_to_dt(event.ts_event)
        current_date = current_time.date()
        signal_date = current_date - timedelta(days=self.config.signal_offset_days)
        self.log.info(
            f"Rebalance triggered at {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC, "
            f"using signals from {signal_date}",
            color=LogColor.CYAN,
        )

        # Record daily position snapshot BEFORE rebalancing
        self._record_daily_snapshot(current_date)

        signal_weights = self._get_weights_for_date(signal_date)
        if not signal_weights:
            self.log.warning(f"No signals for {signal_date}")
            return

        if not SignalHandler.validate_target_weights(signal_weights):
            self.log.error(f"Invalid signal weights for {signal_date}: {signal_weights}")
            return

        signal_weights = SignalHandler.normalize_weights(signal_weights)

        # Get complete weights including positions to close (weight=0)
        weights = self._get_complete_target_weights(signal_weights)
        self.log.info(
            f"Signals: {len(signal_weights)} symbols, "
            f"Complete targets: {len(weights)} symbols (including closes)"
        )

        total_equity = self._get_total_equity()
        if total_equity <= 0:
            self.log.error("No account equity")
            return

        capital_in_use = total_equity * (1 - self.config.capital_reserve_pct)
        self.log.info(
            f"Account equity: {total_equity:.2f}, capital in use: {capital_in_use:.2f}"
        )

        for signal_symbol, weight in weights.items():
            instrument_symbol = self.config.symbol_mapping.get(signal_symbol)
            if not instrument_symbol:
                self.log.warning(f"No mapping for signal symbol: {signal_symbol}")
                continue

            instrument_id = self._find_instrument_id(instrument_symbol)
            if not instrument_id or instrument_id not in self.instruments:
                self.log.warning(f"Instrument not found: {instrument_symbol}")
                continue

            instrument = self.instruments[instrument_id]
            current_price = self.last_prices.get(instrument_id)
            if not current_price or current_price <= 0:
                self.log.warning(f"No price for {instrument_id}")
                continue

            target_notional = capital_in_use * weight
            target_qty = target_notional / current_price

            current_position = self.portfolio.net_position(instrument_id)
            current_qty = float(current_position) if current_position else 0.0

            delta_qty = target_qty - current_qty
            delta_notional = abs(delta_qty * current_price)

            if delta_notional < self.config.min_order_notional:
                self.log.warning(
                    f"Order too small for {signal_symbol}: ${delta_notional:.2f} < ${self.config.min_order_notional}"
                )
                continue

            self._submit_order(instrument_id, instrument, delta_qty)

    def _get_weights_for_date(self, target_date) -> dict[str, float]:
        day_signals = self.signals_df[self.signals_df["date"] == target_date]
        if day_signals.empty:
            return {}
        return dict(zip(day_signals["symbol"], day_signals["weight"], strict=True))

    def _get_complete_target_weights(self, signal_weights: dict[str, float]) -> dict[str, float]:
        """
        Build complete target weights that include positions to be closed.
        """
        complete_weights = dict(signal_weights)  # Start with today's signal weights

        # Add zero weights for positions that need to be closed
        for instrument_id in self.instruments:
            net_qty = self.portfolio.net_position(instrument_id)
            if net_qty and float(net_qty) != 0.0:
                instrument_symbol = str(instrument_id.symbol)
                signal_symbol = self.reverse_symbol_mapping.get(instrument_symbol)
                if signal_symbol is None:
                    continue

                # If currently holding but not in signals, set target to 0 (close position)
                complete_weights.setdefault(signal_symbol, 0.0)

        return complete_weights

    def _record_daily_snapshot(self, snapshot_date) -> None:
        """Record current positions snapshot for daily analysis."""
        total_equity = self._get_total_equity()

        positions_data = []
        for instrument_id in self.instruments:
            net_qty = self.portfolio.net_position(instrument_id)
            qty = float(net_qty) if net_qty else 0.0
            if qty == 0.0:
                continue

            price = self.last_prices.get(instrument_id, 0.0)
            notional = qty * price
            side = "LONG" if qty > 0 else "SHORT"

            instrument_symbol = str(instrument_id.symbol)
            symbol = self.reverse_symbol_mapping.get(instrument_symbol, instrument_symbol)

            positions_data.append({
                "symbol": symbol,
                "instrument_id": str(instrument_id),
                "side": side,
                "quantity": qty,
                "price": price,
                "notional": notional,
            })

        self.daily_snapshots.append({
            "date": snapshot_date,
            "equity": total_equity,
            "num_positions": len(positions_data),
            "positions": positions_data,
        })

    def get_daily_snapshots_df(self) -> pd.DataFrame:
        """Convert daily snapshots to a flat DataFrame for analysis."""
        rows = []
        for snapshot in self.daily_snapshots:
            date = snapshot["date"]
            equity = snapshot["equity"]
            for pos in snapshot["positions"]:
                rows.append({
                    "date": date,
                    "equity": equity,
                    "symbol": pos["symbol"],
                    "instrument_id": pos["instrument_id"],
                    "side": pos["side"],
                    "quantity": pos["quantity"],
                    "price": pos["price"],
                    "notional": pos["notional"],
                })
        return pd.DataFrame(rows)

    def _find_instrument_id(self, instrument_symbol: str) -> InstrumentId | None:
        return self.instrument_id_map.get(instrument_symbol)

    def _submit_order(
        self, instrument_id: InstrumentId, instrument: Instrument, delta_qty: float
    ):
        side = OrderSide.BUY if delta_qty > 0 else OrderSide.SELL
        quantity = instrument.make_qty(abs(delta_qty))

        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=side,
            quantity=quantity,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self.log.info(
            f"Submitted {side.name} {quantity} {instrument_id}", color=LogColor.YELLOW
        )

    def on_stop(self) -> None:
        for instrument_id in self.instruments:
            self.cancel_all_orders(instrument_id)
            self.close_all_positions(instrument_id)
        for bar_type in self.config.bar_types:
            self.unsubscribe_bars(bar_type)
        self.log.info("Strategy stopped — all orders cancelled, positions closed")

    def on_reset(self) -> None:
        self.instruments.clear()
        self.instrument_id_map.clear()
        self.reverse_symbol_mapping.clear()
        self.signals_df = None
        self.last_prices.clear()
        self.daily_snapshots.clear()

    def on_dispose(self) -> None:
        self.signals_df = None
