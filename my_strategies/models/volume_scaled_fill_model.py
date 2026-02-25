"""Volume-scaled slippage fill model for backtesting."""

from nautilus_trader.backtest.models import FillModel
from nautilus_trader.core.rust.model import BookType
from nautilus_trader.core.rust.model import OrderSide
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import BookOrder
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity


UNLIMITED = 1_000_000


class VolumeScaledSlippageFillModel(FillModel):
    """
    Fill model where slippage scales with order size relative to recent volume.

    Tier 1 (best price): a fraction of recent bar quote volume at best bid/ask.
    Tier 2 (slipped price): unlimited liquidity at best +/- slippage_bps.

    Small orders fill entirely at best price (near-zero slippage).
    Large orders that exceed tier 1 spill into tier 2 (full slippage on excess).
    """

    def __init__(self, slippage_bps: float = 5.0, tier1_volume_pct: float = 0.10):
        super().__init__(prob_fill_on_limit=1.0, prob_slippage=0.0)
        self._slippage_bps = slippage_bps
        self._slippage_factor = slippage_bps / 10_000.0
        self._tier1_volume_pct = tier1_volume_pct
        self._recent_volumes: dict[str, float] = {}

    def set_recent_volume(self, instrument_id_str: str, quote_volume: float):
        """Called by the strategy on each bar to update volume for an instrument."""
        self._recent_volumes[instrument_id_str] = quote_volume

    def get_orderbook_for_fill_simulation(self, instrument, order, best_bid, best_ask):
        inst_id = str(instrument.id)
        recent_vol = self._recent_volumes.get(inst_id, 0.0)

        bid_float = best_bid.as_double()
        ask_float = best_ask.as_double()
        prec = instrument.price_precision
        min_qty = 10 ** -instrument.size_precision

        # Tier 1: fraction of recent quote volume converted to base quantity
        if recent_vol > 0:
            tier1_notional = recent_vol * self._tier1_volume_pct
            mid_price = (bid_float + ask_float) / 2.0
            tier1_qty = max(tier1_notional / mid_price, min_qty) if mid_price > 0 else min_qty
        else:
            tier1_qty = min_qty

        # Tier 2: unlimited at slipped prices
        slipped_bid = bid_float * (1.0 - self._slippage_factor)
        slipped_ask = ask_float * (1.0 + self._slippage_factor)

        book = OrderBook(
            instrument_id=instrument.id,
            book_type=BookType.L2_MBP,
        )

        # Tier 1 at best prices
        book.add(BookOrder(
            side=OrderSide.BUY,
            price=Price(bid_float, prec),
            size=Quantity(tier1_qty, instrument.size_precision),
            order_id=1,
        ), 0, 0)
        book.add(BookOrder(
            side=OrderSide.SELL,
            price=Price(ask_float, prec),
            size=Quantity(tier1_qty, instrument.size_precision),
            order_id=2,
        ), 0, 0)

        # Tier 2 at slipped prices
        book.add(BookOrder(
            side=OrderSide.BUY,
            price=Price(slipped_bid, prec),
            size=Quantity(UNLIMITED, instrument.size_precision),
            order_id=3,
        ), 0, 0)
        book.add(BookOrder(
            side=OrderSide.SELL,
            price=Price(slipped_ask, prec),
            size=Quantity(UNLIMITED, instrument.size_precision),
            order_id=4,
        ), 0, 0)

        return book
