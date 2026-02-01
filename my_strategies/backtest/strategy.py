from datetime import timedelta

import pandas as pd

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


CAPITAL_RESERVE_PCT = 0.05  # 5% reserve, 95% capital in use
MIN_ORDER_NOTIONAL = 10.0  # Minimum order value in USD
SIGNAL_OFFSET_DAYS = 2  # Fetch signals from 2 days ago


class MyStrategyConfig(StrategyConfig, frozen=True):
    instrument_ids: tuple[InstrumentId, ...]
    bar_types: tuple[BarType, ...]
    signals_path: str
    symbol_mapping: dict[
        str, str
    ]  # signal symbol -> instrument symbol (e.g., "BTC" -> "BTCUSDT-PERP")


class MyStrategy(Strategy):

    def __init__(self, config: MyStrategyConfig):
        super().__init__(config)
        self.instruments: dict[InstrumentId, Instrument] = {}
        self.instrument_id_map: dict[str, InstrumentId] = {}
        self.signals_df: pd.DataFrame = None
        self.last_prices: dict[InstrumentId, float] = {}

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
        signal_date = current_date - timedelta(days=SIGNAL_OFFSET_DAYS)
        self.log.info(
            f"Rebalance triggered at {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC, "
            f"using signals from {signal_date}",
            color=LogColor.CYAN,
        )

        weights = self._get_weights_for_date(signal_date)
        if not weights:
            self.log.warning(f"No signals for {signal_date}")
            return

        account = self.portfolio.account(self.config.instrument_ids[0].venue)
        if not account:
            self.log.error("No account found")
            return

        total_equity = float(account.balance_total().as_double())
        capital_in_use = total_equity * (1 - CAPITAL_RESERVE_PCT)
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

            if delta_notional < MIN_ORDER_NOTIONAL:
                self.log.warning(
                    f"Order too small for {signal_symbol}: ${delta_notional:.2f} < ${MIN_ORDER_NOTIONAL}"
                )
                continue

            self._submit_order(instrument_id, instrument, delta_qty)

    def _get_weights_for_date(self, target_date) -> dict[str, float]:
        day_signals = self.signals_df[self.signals_df["date"] == target_date]
        if day_signals.empty:
            return {}
        return dict(zip(day_signals["symbol"], day_signals["weight"], strict=True))

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

    def on_stop(self):
        self.log.info("Strategy stopped")
