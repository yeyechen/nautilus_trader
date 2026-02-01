from typing import Any

from clickhouse_driver import Client

from .database_config import ClickHouseConfig


class ClickHouseConnection:

    def __init__(self, config: ClickHouseConfig):
        self._config = config
        self._client = None
        self.connect()

    def connect(self) -> None:
        if self._client is None:
            self._client = Client(
                host=self._config.host,
                port=self._config.port,
                user=self._config.user,
                password=self._config.password,
                database=self._config.database,
                secure=self._config.secure,
            )

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.disconnect()
            self._client = None

    def execute(self, query: str, params: Any | None = None) -> list:
        if self._client is None:
            raise RuntimeError("Not connected to database")
        return self._client.execute(query, params)
