"""Assemble backtest results and upload to the Backtest API."""

import json
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine


API_URL = "https://vlydxw2evsvcxwsfgz2lwjhdiy0wntzy.lambda-url.ap-southeast-1.on.aws"
API_KEY = "dfe4080df9d1605f61626f2dc667fa3c"
NOTIFY_URL = "https://kcwu8slsq9.execute-api.ap-southeast-1.amazonaws.com/Prod/send"


def _api_put(path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-API-Key": API_KEY}
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method="PUT")
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _api_post(path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-API-Key": API_KEY}
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _build_equity_series(strategy) -> pd.DataFrame:
    """Build a daily equity DataFrame from strategy snapshots."""
    dates = []
    equities = []
    for snap in strategy.daily_snapshots:
        dates.append(snap["date"])
        equities.append(snap["equity"])
    df = pd.DataFrame({"date": pd.to_datetime(dates), "equity": equities})
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    return df


def _build_daily_pnl(equity_df: pd.DataFrame) -> list[dict]:
    """Build dailyPnl section: date, daily_return, cumulative_pnl, daily_pnl, equity."""
    start_equity = equity_df["equity"].iloc[0]
    result = []
    for i, row in equity_df.iterrows():
        if i == 0:
            daily_pnl = 0.0
            daily_return = 0.0
        else:
            daily_pnl = row["equity"] - equity_df["equity"].iloc[i - 1]
            prev_eq = equity_df["equity"].iloc[i - 1]
            daily_return = daily_pnl / prev_eq if prev_eq != 0 else 0.0

        cumulative_pnl = row["equity"] - start_equity
        result.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "daily_return": round(daily_return, 8),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "daily_pnl": round(daily_pnl, 2),
            "equity": round(row["equity"], 2),
        })
    return result


def _build_drawdown(equity_df: pd.DataFrame) -> list[dict]:
    """Build drawdown section from equity series."""
    equities = equity_df["equity"].values
    running_max = np.maximum.accumulate(equities)
    drawdown = (equities - running_max) / running_max
    result = []
    for i, row in equity_df.iterrows():
        result.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "drawdown": round(float(drawdown[i]), 6),
        })
    return result


def _build_btc_overlay(equity_df: pd.DataFrame, strategy) -> list[dict]:
    """Build btcOverlay section: normalized strategy vs BTC performance."""
    # Extract BTC prices from daily snapshots
    btc_prices = {}
    for snap in strategy.daily_snapshots:
        date_str = pd.to_datetime(snap["date"]).strftime("%Y-%m-%d")
        for pos in snap["positions"]:
            if pos["symbol"] == "BTC":
                btc_prices[date_str] = pos["price"]
                break

    start_equity = equity_df["equity"].iloc[0]
    first_date = equity_df["date"].iloc[0].strftime("%Y-%m-%d")
    btc_start = btc_prices.get(first_date)

    result = []
    for _, row in equity_df.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        strategy_norm = round(row["equity"] / start_equity * 100, 2)
        btc_price = btc_prices.get(date_str, 0)

        entry = {
            "date": date_str,
            "strategy_normalized": strategy_norm,
            "btc_price": round(btc_price, 2),
        }
        if btc_start and btc_price:
            entry["btc_normalized"] = round(btc_price / btc_start * 100, 2)
        else:
            entry["btc_normalized"] = 0

        result.append(entry)
    return result


def _build_stats(equity_df: pd.DataFrame, daily_pnl: list[dict]) -> dict:
    """Build stats section from equity and daily PnL data."""
    returns = equity_df["equity"].pct_change().dropna()
    total_days = len(equity_df) - 1
    if total_days <= 0:
        return {}

    total_return = (equity_df["equity"].iloc[-1] / equity_df["equity"].iloc[0]) - 1
    avg_daily_return = returns.mean()
    daily_vol = returns.std()

    # Sharpe (annualized, 365 days for crypto)
    sharpe = (avg_daily_return / daily_vol * np.sqrt(365)) if daily_vol > 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_std = downside.std() if len(downside) > 0 else 0
    sortino = (avg_daily_return / downside_std * np.sqrt(365)) if downside_std > 0 else 0

    # Max drawdown
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdowns = (cumulative - running_max) / running_max
    max_drawdown = drawdowns.min()

    # CAGR
    years = total_days / 365
    annualized_apy = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # Calmar
    calmar = annualized_apy / abs(max_drawdown) if max_drawdown != 0 else 0

    # Profitable days
    daily_pnl_values = [d["daily_pnl"] for d in daily_pnl[1:]]  # skip first day (0)
    profitable_days = sum(1 for p in daily_pnl_values if p > 0)
    profitable_pct = profitable_days / total_days if total_days > 0 else 0

    # Time underwater (days in drawdown)
    dd_series = (cumulative - running_max) / running_max
    underwater_days = (dd_series < -1e-8).sum()
    time_underwater_pct = underwater_days / total_days if total_days > 0 else 0

    # Longest drawdown period
    in_dd = (dd_series < -1e-8).astype(int)
    longest = 0
    current = 0
    for v in in_dd:
        if v:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    # Profit factor
    gains = sum(p for p in daily_pnl_values if p > 0)
    losses = abs(sum(p for p in daily_pnl_values if p < 0))
    profit_factor = gains / losses if losses > 0 else 0

    # Return over max DD
    return_over_max_dd = total_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # 30d return
    if len(returns) >= 30:
        return_30d = (1 + returns.iloc[-30:]).prod() - 1
    else:
        return_30d = total_return

    # BTC stats (placeholder — requires BTC returns for correlation/beta)
    stats = {
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown": round(float(max_drawdown), 8),
        "annualized_apy": round(annualized_apy, 8),
        "calmar": round(calmar, 4),
        "daily_volatility": round(float(daily_vol), 10),
        "avg_daily_return": round(float(avg_daily_return), 10),
        "total_days": total_days,
        "profitable_days": profitable_days,
        "profitable_pct": round(profitable_pct, 4),
        "time_underwater_pct": round(float(time_underwater_pct), 4),
        "longest_drawdown_days": longest,
        "profit_factor": round(profit_factor, 8),
        "return_over_max_dd": round(return_over_max_dd, 4),
        "return_30d": round(float(return_30d), 8),
        "vault_age_days": len(equity_df),
    }
    return stats


def _build_pnl_summary(equity_df: pd.DataFrame, daily_pnl: list[dict], engine: BacktestEngine) -> dict:
    """Build pnlSummary section for 24h, 7d, 30d, allTime windows."""
    start_equity = equity_df["equity"].iloc[0]
    end_equity = equity_df["equity"].iloc[-1]

    # Total volume from order fills
    fills_report = engine.trader.generate_order_fills_report()
    if len(fills_report) > 0 and "avg_px" in fills_report.columns and "filled_qty" in fills_report.columns:
        fills_report["notional"] = fills_report["avg_px"].astype(float) * fills_report["filled_qty"].astype(float)
        total_volume = float(fills_report["notional"].sum())
    else:
        total_volume = 0.0

    total_days = max(len(equity_df) - 1, 1)
    avg_daily_volume = total_volume / total_days

    def _window(n_days: int) -> dict:
        window_pnl = daily_pnl[-n_days:] if len(daily_pnl) >= n_days else daily_pnl
        pnl = sum(d["daily_pnl"] for d in window_pnl)
        vol = avg_daily_volume * min(n_days, total_days)
        roe = pnl / start_equity * 100 if start_equity > 0 else 0
        return {
            "volume": round(vol, 2),
            "roe": round(roe, 2),
            "pnl": round(pnl, 2),
        }

    all_time_pnl = end_equity - start_equity
    return {
        "24h": _window(1),
        "7d": _window(7),
        "30d": _window(30),
        "allTime": {
            "volume": round(total_volume, 2),
            "roe": round(all_time_pnl / start_equity * 100, 2),
            "pnl": round(all_time_pnl, 2),
        },
    }


def _build_parameters(equity_df: pd.DataFrame, engine: BacktestEngine) -> dict:
    """Build parameters section."""
    fills_report = engine.trader.generate_order_fills_report()
    total_trades = len(fills_report)

    total_days = max(len(equity_df) - 1, 1)
    if total_trades > 0 and "avg_px" in fills_report.columns and "filled_qty" in fills_report.columns:
        fills_report["notional"] = fills_report["avg_px"].astype(float) * fills_report["filled_qty"].astype(float)
        total_volume = float(fills_report["notional"].sum())
    else:
        total_volume = 0.0
    avg_daily_turnover = total_volume / total_days

    return {
        "startDate": equity_df["date"].iloc[0].strftime("%Y-%m-%d"),
        "endDate": equity_df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "startingCapital": round(equity_df["equity"].iloc[0], 2),
        "totalTrades": total_trades,
        "avgDailyTurnover": round(avg_daily_turnover, 2),
    }


def _build_positions(strategy) -> dict:
    """Build positions section from the last daily snapshot."""
    if not strategy.daily_snapshots:
        return {"snapshotDate": "", "assetPositions": []}

    last_snap = strategy.daily_snapshots[-1]
    snapshot_date = pd.to_datetime(last_snap["date"]).strftime("%Y-%m-%d")

    asset_positions = []
    for pos in last_snap["positions"]:
        notional = abs(pos["notional"])
        szi = str(pos["quantity"])
        asset_positions.append({
            "type": "oneWay",
            "position": {
                "leverage": {"type": "isolated", "rawUsd": "0", "value": 1},
                "szi": szi,
                "marginUsed": str(round(notional, 2)),
                "unrealizedPnl": "0",
                "cumFunding": {"allTime": "0", "sinceOpen": "0", "sinceChange": "0"},
                "entryPx": str(pos["price"]),
                "returnOnEquity": "0",
                "liquidationPx": "0",
                "positionValue": str(round(notional, 2)),
                "maxLeverage": 1,
                "coin": pos["symbol"],
            },
        })

    return {
        "snapshotDate": snapshot_date,
        "assetPositions": asset_positions,
    }


def upload_backtest_results(engine: BacktestEngine, strategy) -> None:
    """Assemble all sections from backtest results and upload via API."""
    print("\n" + "=" * 60)
    print("UPLOADING BACKTEST RESULTS TO API")
    print("=" * 60)

    equity_df = _build_equity_series(strategy)
    if len(equity_df) < 2:
        print("ERROR: Not enough data points to upload.")
        return

    daily_pnl = _build_daily_pnl(equity_df)
    drawdown = _build_drawdown(equity_df)
    btc_overlay = _build_btc_overlay(equity_df, strategy)
    stats = _build_stats(equity_df, daily_pnl)
    pnl_summary = _build_pnl_summary(equity_df, daily_pnl, engine)
    parameters = _build_parameters(equity_df, engine)
    positions = _build_positions(strategy)

    payload = {
        "parameters": parameters,
        "stats": {"data": stats},
        "dailyPnl": {"data": daily_pnl},
        "drawdown": {"data": drawdown},
        "btcOverlay": {"data": btc_overlay},
        "pnlSummary": pnl_summary,
        "positions": positions,
    }

    print(f"  Parameters: {parameters['startDate']} to {parameters['endDate']}")
    print(f"  Total trades: {parameters['totalTrades']}")
    print(f"  Sharpe: {stats.get('sharpe')}, Max DD: {stats.get('max_drawdown')}")
    print(f"  Equity points: {len(daily_pnl)}, Positions: {len(positions['assetPositions'])}")

    status, response = _api_post("/backtest/data", payload)
    if 200 <= status < 300:
        print(f"  Upload successful (HTTP {status})")
    else:
        print(f"  Upload FAILED (HTTP {status}): {response}")

    # --- Notify teammate ---
    message = f"Backtest updated: {parameters['startDate']} to {parameters['endDate']}"
    _notify(message)

    print("=" * 60)


def _notify(message: str) -> None:
    """Send a notification via the notification API."""
    body = json.dumps({"topic": "daily", "message": message}).encode()
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(NOTIFY_URL, data=body, headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req)
        print(f"  Notification sent (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"  Notification FAILED (HTTP {e.code}): {e.read().decode()}")
