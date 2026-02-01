from datetime import datetime
from datetime import timedelta
from datetime import timezone
from math import isclose

from my_strategies.database import ClickHouseConnection

from .signal_handler_config import SignalHandlerConfig


class SignalHandler:

    def __init__(self, config: SignalHandlerConfig):
        self._database_config = config.database_config
        self._database_connection = ClickHouseConnection(self._database_config)

        self._signal_database_name = config.signal_database_name
        self._signal_table_name = config.signal_table_name
        self._tz = config.timezone if config.timezone else timezone.utc  # noqa: UP017
        self._signal_offset_days = config.signal_offset_days

    def fetch_target_portfolio_weights_for_today(self) -> dict:
        today = datetime.now(self._tz)
        target_date = today - timedelta(days=self._signal_offset_days)
        return self.fetch_target_portfolio_weights_for_date(target_date)

    def fetch_target_portfolio_weights_for_date(self, target_date: datetime) -> dict:
        query, params = self._build_weights_query(target_date)
        result = self._database_connection.execute(query, params)
        return {row[0]: row[1] for row in result} if result else None

    def _build_weights_query(self, target_date: datetime) -> tuple[str, dict]:
        target_date_str = target_date.strftime("%Y-%m-%d")
        table = f"{self._signal_database_name}.{self._signal_table_name}"
        # Table name is from config (trusted source), user input is parameterized
        query = f"""
            SELECT
                UPPER(symbol) AS symbol,
                toFloat64(weight) AS weight
            FROM {table}
            WHERE weight IS NOT NULL
            AND NOT isNaN(toFloat64(weight))
            AND toDate(date) = toDate(%(target_date)s)
            AND inserted_at = (
                SELECT max(inserted_at)
                FROM {table}
                WHERE weight IS NOT NULL
                AND NOT isNaN(toFloat64(weight))
                AND toDate(date) = toDate(%(target_date)s)
            )
            LIMIT 1 BY date, symbol
        """  # noqa: S608
        return query, {"target_date": target_date_str}

    def validate_target_weights(self, weights: dict[str, float]) -> bool:
        """Validate weights: each in [-1,1] and sum to 0 (net neutral)."""
        weight_sum = sum(weights.values())
        return all(-1.0 <= w <= 1.0 for w in weights.values()) and isclose(
            weight_sum, 0.0, abs_tol=1e-8
        )

    @staticmethod
    def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
        gross = sum(abs(w) for w in weights.values())
        return {symbol: w / gross for symbol, w in weights.items()}
