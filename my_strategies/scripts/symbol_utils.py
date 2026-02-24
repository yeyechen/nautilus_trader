from pathlib import Path

import pandas as pd

_DATA_DIR = Path(__file__).parent.parent / "data" / "signals"

SIGNAL_FILE_PATH = _DATA_DIR / "signals_2024-12-01_2026-02-21_20260221_125721.parquet"
SIGNAL_V2_FILE_PATH = _DATA_DIR / "signals_v2_2024-12-01_2026-02-24_20260224_041123.parquet"


def get_unique_symbols(
    signal_file_path: str | Path | None = None,
    quote_currency: str = "USDT",
) -> list[str]:
    """
    Get list of unique symbols from the signal parquet file.

    Args:
        signal_file_path: Path to the signal parquet file. If None, uses the default path.
        quote_currency: Quote currency suffix to append (e.g., 'USDT'). Set to empty string to skip.

    Returns:
        List of unique symbols sorted alphabetically with quote currency appended.
    """
    if signal_file_path is None:
        signal_file_path = SIGNAL_FILE_PATH
    else:
        signal_file_path = Path(signal_file_path)

    # Read the parquet file
    df = pd.read_parquet(signal_file_path)

    # Get unique symbols
    base_symbols = df["symbol"].unique().tolist()

    # Add quote currency suffix if provided
    if quote_currency:
        unique_symbols = sorted([f"{symbol}{quote_currency}" for symbol in base_symbols])
    else:
        unique_symbols = sorted(base_symbols)

    return unique_symbols
