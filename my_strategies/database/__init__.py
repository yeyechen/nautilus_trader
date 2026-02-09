from .database_config import ClickHouseConfig
from .database_config import get_log_db_config
from .database_config import get_signal_db_config


def __getattr__(name: str):
    if name == "ClickHouseConnection":
        from .database_connection import ClickHouseConnection

        return ClickHouseConnection
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ClickHouseConfig",
    "ClickHouseConnection",
    "get_log_db_config",
    "get_signal_db_config",
]
