"""Henting av kurser og nøkkeltall fra Yahoo (yfinance). Alt kan feile, så hver ticker håndteres alene."""
import datetime as dt
import json
import math
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf

CACHE = pathlib.Path("cache")


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def rsi14(closes: pd.Series):
    d = closes.diff().dropna()
    if len(d) < 15:
        return None
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    if dn == 0:
        return 100.0
    return float(100 - 100 / (1 + up / dn))


def price_stats(hist: pd.DataFrame):
    closes = hist["Close"].dropna()
    if len(closes) < 220:
        raise ValueError("for lite kurshistorikk")
    price = float(closes.iloc[-1])
    ma200 = float(closes.iloc[-200:].mean())
    window = closes.iloc[-252:]
    high52 = float(window.max())
    ret_12_1 = None
    if len(closes) >= 252:
        ret_12_1 = float(closes.iloc[-21] / closes.iloc[-252] - 1)
    ret_1m = float(closes.iloc[-1] / closes.iloc[-22] - 1) if len(closes) > 22 else None
    recent = {d.strftime("%Y-%m-%d"): float(v) for d, v in closes.iloc[-15:].items()}
    return {
        "date": closes.index[-1].strftime("%Y-%m-%d"),
        "price": price,
        "ma200": ma200,
        "above200": price > ma200,
        "high52": high52,
        "dd": price / high52 - 1,
        "ret_12_1": ret_12_1,
        "ret_1m": ret_1m,
        "rsi": rsi14(closes),
        "recent": recent,
    }


def build_record(ticker, info, hist):
    rec = price_stats(hist)
    rec.update({
        "ticker": ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "ccy": info.get("currency"),
        "fin_ccy": info.get("financialCurrency"),
        "mcap": num(info.get("marketCap")),
        "eps": num(info.get("trailingEps")),
        "fcf": num(info.get("freeCashflow")),
        "ev_ebitda": num(info.get("enterpriseToEbitda")),
        "pb": num(info.get("priceToBook")),
        "pe": num(info.get("trailingPE")),
        "roe": num(info.get("returnOnEquity")),
        "opm": num(info.get("operatingMargins")),
        "pm": num(info.get("profitMargins")),
        "de": num(info.get("debtToEquity")),
    })
    return rec


def fetch_one(ticker, retries=3, pause=1.5, with_info=True):
    last = None
    for i in range(retries):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="2y", auto_adjust=True)
            if hist is None or hist.empty:
                raise ValueError("ingen kursdata")
            info = (t.info or {}) if with_info else {}
            return build_record(ticker, info, hist)
        except Exception as e:  # noqa: BLE001 - Yahoo kaster mange ulike feil
            last = e
            time.sleep(pause * (2 ** i))
    return {"ticker": ticker, "error": str(last)[:160]}


def fetch_all(tickers, workers=4, with_info=True):
    CACHE.mkdir(exist_ok=True)
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    folder = CACHE / day
    folder.mkdir(exist_ok=True)

    def job(t):
        f = folder / (t.replace("^", "_") + ".json")
        if f.exists():
            return json.loads(f.read_text())
        rec = fetch_one(t, with_info=with_info)
        if "error" not in rec:
            f.write_text(json.dumps(rec))
        time.sleep(0.2)
        return rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(job, tickers))
