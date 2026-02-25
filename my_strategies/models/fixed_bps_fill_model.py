"""Fixed basis-point slippage fill model for backtesting."""

from nautilus_trader.backtest.models import FillModel
from nautilus_trader.core.rust.model import BookType
from nautilus_trader.core.rust.model import OrderSide
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import BookOrder
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity


UNLIMITED = 1_000_000


class FixedBpsSlippageFillModel(FillModel):
    """
    Fill model that applies fixed basis-point slippage to all market orders.

    For BUY orders, the ask is shifted up by `slippage_bps`.
    For SELL orders, the bid is shifted down by `slippage_bps`.

    This mirrors the live trading engine's limit-order approach where orders
    are placed at mid_price * (1 +/- slippage_bps / 10_000).
    """

    def __init__(self, slippage_bps: float = 5.0):
        super().__init__(prob_fill_on_limit=1.0, prob_slippage=0.0)
        self._slippage_bps = slippage_bps
        self._slippage_factor = slippage_bps / 10_000.0

    def get_orderbook_for_fill_simulation(self, instrument, order, best_bid, best_ask):
        bid_float = best_bid.as_double()
        ask_float = best_ask.as_double()

        slipped_bid = bid_float * (1.0 - self._slippage_factor)
        slipped_ask = ask_float * (1.0 + self._slippage_factor)

        prec = instrument.price_precision

        book = OrderBook(
            instrument_id=instrument.id,
            book_type=BookType.L2_MBP,
        )

        bid_order = BookOrder(
            side=OrderSide.BUY,
            price=Price(slipped_bid, prec),
            size=Quantity(UNLIMITED, instrument.size_precision),
            order_id=1,
        )
        ask_order = BookOrder(
            side=OrderSide.SELL,
            price=Price(slipped_ask, prec),
            size=Quantity(UNLIMITED, instrument.size_precision),
            order_id=2,
        )

        book.add(bid_order, 0, 0)
        book.add(ask_order, 0, 0)

        return book
