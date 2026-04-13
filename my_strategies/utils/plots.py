"""Plotting and portfolio performance utilities for notebook analysis."""

from typing import Any, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tabulate import tabulate


# Plot style constants
BLUE_HEX = "#1e88e5"
RED_HEX = "#f31d36"
DEFAULT_FIGSIZE = (12, 6)


# ---------------------------------------------------------------------------
# Performance analysis (from 2025_summer_projects/utils/portfolio_analysis.py)
# ---------------------------------------------------------------------------


def calculate_portfolio_performance(
    portfolio_df: pd.DataFrame,
    date_col: str,
    ret_col: str,
    freq: str,
) -> dict[str, float]:
    """
    Calculate key performance metrics for a portfolio.

    Args:
        portfolio_df: DataFrame with portfolio returns
        date_col: Date column name
        ret_col: Return column name
        freq: Frequency ('D'=daily, 'W'=weekly, 'M'=monthly)

    Returns:
        Dictionary with performance metrics
    """
    df = portfolio_df.dropna(subset=[ret_col]).sort_values(date_col).copy()
    df["cum_ret"] = (1 + df[ret_col]).cumprod()

    total_ret = df["cum_ret"].iloc[-1] - 1

    n_years = (df[date_col].max() - df[date_col].min()).days / 365.25
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0.0

    ann_factors = {"M": 12, "W": 52, "D": 365}
    ann_factor = ann_factors[freq]

    ann_ret = df[ret_col].mean() * ann_factor
    ann_vol = df[ret_col].std() * np.sqrt(ann_factor)
    sharpe = ann_ret / ann_vol if ann_vol != 0 else 0

    rolling_max = df["cum_ret"].expanding().max()
    drawdowns = df["cum_ret"] / rolling_max - 1
    max_drawdown = drawdowns.min()

    return {
        "total_return": total_ret,
        "cagr": cagr,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
    }


def print_portfolio_performance(
    portfolio_df: pd.DataFrame,
    date_col: str,
    ret_col: str,
    freq: str,
) -> None:
    """Print formatted portfolio performance metrics."""
    metrics = calculate_portfolio_performance(portfolio_df, date_col, ret_col, freq)

    formatted_metrics = {
        "Total Return": f"{metrics['total_return']*100:.2f}%",
        "CAGR": f"{metrics['cagr']*100:.2f}%",
        "Sharpe Ratio": f"{metrics['sharpe_ratio']:.2f}",
        "Max Drawdown": f"{metrics['max_drawdown']*100:.2f}%",
        "Ann. Return": f"{metrics['annualized_return']*100:.2f}%",
        "Ann. Volatility": f"{metrics['annualized_volatility']*100:.2f}%",
    }

    pretty_print(formatted_metrics)


def pretty_print(data: Union[dict[str, Any], pd.DataFrame]) -> None:
    """Pretty print a dictionary or DataFrame in tabular format."""
    if isinstance(data, dict):
        df = pd.DataFrame([data])
    elif isinstance(data, pd.DataFrame):
        df = data
    else:
        raise TypeError("Input must be dict or DataFrame")

    print(tabulate(df, headers="keys", tablefmt="rounded_grid", showindex=False))


# ---------------------------------------------------------------------------
# Plotting (from 2025_summer_projects/utils/plotting.py)
# ---------------------------------------------------------------------------


def plot_cum_returns(
    portfolio_df: pd.DataFrame,
    index_col_name: str,
    ret_col_lst: list[str],
    figsize: tuple[int, int] | None = None,
    title: str | None = None,
) -> None:
    """
    Plot cumulative returns for multiple portfolios.

    Args:
        portfolio_df: DataFrame containing portfolio returns
        index_col_name: Name of the date/index column
        ret_col_lst: List of return column names to plot
        figsize: Figure size (width, height)
        title: Plot title
    """
    plt.figure(figsize=figsize or DEFAULT_FIGSIZE)

    for col in ret_col_lst:
        cum_returns = (1 + portfolio_df[col]).cumprod() - 1

        color = None
        if "_EW" in col:
            color = BLUE_HEX
        elif "_VW" in col:
            color = RED_HEX

        plt.plot(
            portfolio_df[index_col_name], cum_returns,
            label=col, color=color, linewidth=2,
        )

    plt.xlabel(index_col_name.title())
    plt.ylabel("Cumulative Returns")
    plt.title(title or "Cumulative Returns of Portfolios")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def plot_drawdown_chart(
    portfolio_df: pd.DataFrame,
    date_col: str,
    ret_col: str,
    figsize: tuple[int, int] | None = None,
) -> None:
    """
    Plot portfolio drawdown over time.

    Args:
        portfolio_df: DataFrame with portfolio returns
        date_col: Date column name
        ret_col: Return column name
        figsize: Figure size
    """
    df = portfolio_df.dropna(subset=[ret_col]).sort_values(date_col).copy()
    df["cum_ret"] = (1 + df[ret_col]).cumprod()
    df["rolling_max"] = df["cum_ret"].expanding().max()
    df["drawdown"] = (df["cum_ret"] / df["rolling_max"] - 1) * 100

    plt.figure(figsize=figsize or DEFAULT_FIGSIZE)
    plt.fill_between(df[date_col], df["drawdown"], 0, color=RED_HEX, alpha=0.3)
    plt.plot(df[date_col], df["drawdown"], color=RED_HEX, linewidth=1)

    plt.xlabel(date_col.title())
    plt.ylabel("Drawdown (%)")
    plt.title("Portfolio Drawdown Over Time")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()
