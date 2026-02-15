from pathlib import Path

import pandas as pd


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
        # Use default signal file path
        signal_file_path = (
            Path(__file__).parent.parent
            / "data"
            / "signal"
            / "signals_2024-12-01_2026-02-13_20260213_015447.parquet"
        )
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
