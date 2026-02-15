import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from my_strategies.database import ClickHouseConfig
from my_strategies.database import get_signal_db_config


@dataclass(frozen=True)
class SignalHandlerConfig:
    database_config: ClickHouseConfig
    signal_database_name: str
    signal_table_name: str
    timezone: ZoneInfo


def get_signal_handler_config() -> SignalHandlerConfig:
    return SignalHandlerConfig(
        database_config=get_signal_db_config(),
        signal_database_name=os.getenv("SIGNAL_DATABASE_NAME"),
        signal_table_name=os.getenv("SIGNAL_TABLE_NAME"),
        timezone=ZoneInfo(os.getenv("TIMEZONE", "UTC")),
    )
