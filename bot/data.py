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


def drop_intraday(closes: pd.Series, now=None):
    """Yahoo gir dagens ufullstendige kurs midt i handelsdagen. Bruk bare avsluttede dager."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if len(closes) and closes.index[-1].date() >= now.date() and now.hour < 21:
        return closes.iloc[:-1]
    return closes


def price_stats(hist: pd.DataFrame, now=None):
    closes = drop_intraday(hist["Close"].dropna(), now)
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


def _mcap_fallback(info, price):
    """Yahoo mangler av og til markedsverdi (for eksempel Frontline, Gjensidige). Regn den ut selv."""
    shares = num(info.get("sharesOutstanding"))
    return shares * price if shares and price else None


def build_record(ticker, info, hist):
    rec = price_stats(hist)
    rec.update({
        "ticker": ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "ccy": info.get("currency"),
        "fin_ccy": info.get("financialCurrency"),
        "mcap": num(info.get("marketCap")) or _mcap_fallback(info, rec["price"]),
        "eps": num(info.get("trailingEps")),
        "fcf": num(info.get("freeCashflow")),
        "ev_ebitda": num(info.get("enterpriseToEbitda")),
        "pb": num(info.get("priceToBook")),
        "pe": num(info.get("trailingPE")),
        "roe": num(info.get("returnOnEquity")),
        "opm": num(info.get("operatingMargins")),
        "pm": num(info.get("profitMargins")),
        "de": num(info.get("debtToEquity")),
        "debt": num(info.get("totalDebt")),
        "cash": num(info.get("totalCash")),
        "ebitda": num(info.get("ebitda")),
    })
    return rec


def avg_net_income(stmt):
    """Snitt av årsresultat over tilgjengelige år (Yahoo gir normalt 4). Brukes for sykliske selskaper."""
    if stmt is None or getattr(stmt, "empty", True):
        return None, 0
    for key in ("Net Income", "Net Income Common Stockholders"):
        if key in stmt.index:
            vals = [num(v) for v in stmt.loc[key].tolist()]
            vals = [v for v in vals if v is not None]
            if vals:
                return sum(vals) / len(vals), len(vals)
    return None, 0


def fetch_one(ticker, retries=3, pause=1.5, with_info=True):
    last = None
    for i in range(retries):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="2y", auto_adjust=True)
            if hist is None or hist.empty:
                raise ValueError("ingen kursdata")
            info = (t.info or {}) if with_info else {}
            rec = build_record(ticker, info, hist)
            if with_info and rec["mcap"] is None:
                try:
                    rec["mcap"] = num(t.fast_info["marketCap"])
                except Exception:  # noqa: BLE001
                    pass
            if with_info:
                from .scoring import is_cyclical
                if is_cyclical(rec):
                    try:
                        rec["ni_avg"], rec["ni_years"] = avg_net_income(t.income_stmt)
                    except Exception:  # noqa: BLE001 - mangler regnskap gir bare færre nøkkeltall
                        rec["ni_avg"], rec["ni_years"] = None, 0
            return rec
        except Exception as e:  # noqa: BLE001 - Yahoo kaster mange ulike feil
            last = e
            time.sleep(pause * (2 ** i))
    return {"ticker": ticker, "error": str(last)[:160]}


def fetch_all(tickers, workers=4, with_info=True, pause=1.5, sleep=0.2):
    CACHE.mkdir(exist_ok=True)
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    folder = CACHE / day
    folder.mkdir(exist_ok=True)

    def job(t):
        f = folder / (t.replace("^", "_") + ".json")
        if f.exists():
            return json.loads(f.read_text())
        rec = fetch_one(t, pause=pause, with_info=with_info)
        if "error" not in rec:
            f.write_text(json.dumps(rec))
        time.sleep(sleep)
        return rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(job, tickers))


def mark_stale(recs, max_days=7):
    """Aksjer uten ferske kurser (nedlagt, flyttet, stoppet) skal ikke rangeres."""
    ok = [r for r in recs if "error" not in r and r.get("date")]
    if not ok:
        return recs
    latest = {}
    for r in ok:
        latest[r["market"]] = max(latest.get(r["market"], ""), r["date"])
    out = []
    for r in recs:
        if "error" in r or not r.get("date"):
            out.append(r)
            continue
        lag = (dt.date.fromisoformat(latest[r["market"]]) - dt.date.fromisoformat(r["date"])).days
        out.append({"ticker": r["ticker"], "market": r["market"], "name": r.get("name"),
                    "error": f"foreldet kurs ({r['date']})"} if lag > max_days else r)
    return out
