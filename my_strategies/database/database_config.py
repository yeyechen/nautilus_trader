from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class ClickHouseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    secure: bool


def get_signal_db_config() -> ClickHouseConfig:
    return ClickHouseConfig(
        host=getenv("SIGNAL_CLICKHOUSE_HOST", ""),
        port=int(getenv("SIGNAL_CLICKHOUSE_PORT", "")),
        user=getenv("SIGNAL_CLICKHOUSE_USER", ""),
        password=getenv("SIGNAL_CLICKHOUSE_PASSWORD", ""),
        database=getenv("SIGNAL_CLICKHOUSE_DATABASE", ""),
        secure=True,
    )


def get_log_db_config() -> ClickHouseConfig:
    return ClickHouseConfig(
        host=getenv("LOG_CLICKHOUSE_HOST", ""),
        port=int(getenv("LOG_CLICKHOUSE_PORT", "")),
        user=getenv("LOG_CLICKHOUSE_USER", ""),
        password=getenv("LOG_CLICKHOUSE_PASSWORD", ""),
        database=getenv("LOG_CLICKHOUSE_DATABASE", ""),
        secure=False,
    )
