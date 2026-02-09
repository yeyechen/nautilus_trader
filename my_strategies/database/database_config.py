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


def _require_env(name: str) -> str:
    value = getenv(name, "")
    if not value:
        raise EnvironmentError(
            f"{name} is not set. "
            "Copy .env.example to .env and fill in your values."
        )
    return value


def get_signal_db_config() -> ClickHouseConfig:
    return ClickHouseConfig(
        host=_require_env("SIGNAL_CLICKHOUSE_HOST"),
        port=int(_require_env("SIGNAL_CLICKHOUSE_PORT")),
        user=_require_env("SIGNAL_CLICKHOUSE_USER"),
        password=_require_env("SIGNAL_CLICKHOUSE_PASSWORD"),
        database=_require_env("SIGNAL_CLICKHOUSE_DATABASE"),
        secure=True,
    )


def get_log_db_config() -> ClickHouseConfig:
    return ClickHouseConfig(
        host=_require_env("LOG_CLICKHOUSE_HOST"),
        port=int(_require_env("LOG_CLICKHOUSE_PORT")),
        user=_require_env("LOG_CLICKHOUSE_USER"),
        password=_require_env("LOG_CLICKHOUSE_PASSWORD"),
        database=_require_env("LOG_CLICKHOUSE_DATABASE"),
        secure=False,
    )
