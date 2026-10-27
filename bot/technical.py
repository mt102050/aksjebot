"""Teknisk analyse for graf-fanen. Beskriver kursbildet. Gir ingen kjøpssignaler, fordi slike
mønstre har svak dokumentasjon. Alt er rene regnestykker, så det kan testes uten nett."""
import pandas as pd


def rsi_series(close: pd.Series, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(100.0)


def atr_pct(df: pd.DataFrame, n=14):
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean().iloc[-1]
    return float(atr / df["Close"].iloc[-1])


def pivots(df: pd.DataFrame, k=5):
    """Lokale topper og bunner: høyeste/laveste kurs innenfor k dager på hver side."""
    hi, lo = df["High"], df["Low"]
    tops, bots = [], []
    for i in range(k, len(df) - k):
        if hi.iloc[i] == hi.iloc[i - k:i + k + 1].max():
            tops.append(float(hi.iloc[i]))
        if lo.iloc[i] == lo.iloc[i - k:i + k + 1].min():
            bots.append(float(lo.iloc[i]))
    return tops, bots


def cluster(levels, tol=0.015):
    """Slår sammen nivåer innenfor 1,5 prosent. Returnerer (nivå, antall berøringer)."""
    out = []
    for x in sorted(levels):
        if out and abs(x - out[-1][0]) / out[-1][0] <= tol:
            lvl, n = out[-1]
            out[-1] = ((lvl * n + x) / (n + 1), n + 1)
        else:
            out.append((x, 1))
    return out


def levels(df: pd.DataFrame, lookback=125):
    d = df.iloc[-lookback:]
    tops, bots = pivots(d)
    price = float(d["Close"].iloc[-1])
    allv = cluster(tops + bots)
    sup = sorted([lv for lv in allv if lv[0] < price * 0.995], key=lambda x: -x[0])[:2]
    res = sorted([lv for lv in allv if lv[0] > price * 1.005], key=lambda x: x[0])[:2]
    return [{"price": round(p, 4), "touches": n} for p, n in sup], [{"price": round(p, 4), "touches": n} for p, n in res]


def analyse(df: pd.DataFrame):
    """df: daglige OHLCV med DatetimeIndex. Returnerer serier for graf og et sammendrag."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    close = df["Close"]
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    rsi = rsi_series(close)
    price = float(close.iloc[-1])
    m50 = float(ma50.iloc[-1]) if pd.notna(ma50.iloc[-1]) else None
    m200 = float(ma200.iloc[-1]) if pd.notna(ma200.iloc[-1]) else None

    if m50 and m200 and price > m50 > m200:
        trend = "opptrend"
    elif m50 and m200 and price < m50 < m200:
        trend = "nedtrend"
    else:
        trend = "blandet"

    w = close.iloc[-252:]
    hi52, lo52 = float(w.max()), float(w.min())
    vol = df["Volume"] if "Volume" in df else pd.Series(dtype=float)
    vol_ratio = None
    if len(vol) >= 50 and vol.iloc[-50:].mean() > 0:
        vol_ratio = float(vol.iloc[-5:].mean() / vol.iloc[-50:].mean())
    sup, res = levels(df)
    r_now = float(rsi.iloc[-1])

    def nf(x, d=2, sign=False):
        return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}").replace(".", ",")

    notes = []
    notes.append({"opptrend": "Kursen ligger over 50- og 200-dagers snitt, og 50 over 200. Det er en opptrend.",
                  "nedtrend": "Kursen ligger under 50- og 200-dagers snitt, og 50 under 200. Det er en nedtrend.",
                  "blandet": "Snittene peker ikke i samme retning. Trenden er uklar."}[trend])
    if r_now >= 70:
        notes.append(f"RSI er {r_now:.0f}. Kursen har steget raskt, og tilbakefall er vanlig etter slike perioder.")
    elif r_now <= 30:
        notes.append(f"RSI er {r_now:.0f}. Kursen har falt raskt.")
    if sup:
        notes.append(f"Nærmeste støtte rundt {nf(sup[0]['price'])} ({nf((sup[0]['price'] / price - 1) * 100, 1, True)} %).")
    if res:
        notes.append(f"Nærmeste motstand rundt {nf(res[0]['price'])} ({nf((res[0]['price'] / price - 1) * 100, 1, True)} %).")
    if vol_ratio is not None and vol_ratio >= 1.5:
        notes.append(f"Volumet siste uke er {nf(vol_ratio, 1)} ganger normalt. Sjekk om det har kommet nyheter.")
    dd = price / hi52 - 1
    if dd <= -0.25:
        notes.append(f"Kursen er {dd * 100:.0f} % under toppen siste år.")

    keep = slice(-260, None)  # vis ett år, men regn snittene på hele historikken

    def ser(s, n=1):
        return [None if pd.isna(v) else round(float(v), 4) for v in s.iloc[keep]]

    return {
        "t": [d.strftime("%Y-%m-%d") for d in df.index[keep]],
        "o": ser(df["Open"]), "h": ser(df["High"]), "l": ser(df["Low"]), "c": ser(close),
        "v": [None if pd.isna(v) else int(v) for v in vol.iloc[keep]] if len(vol) else [],
        "ma50": ser(ma50), "ma200": ser(ma200), "rsi": ser(rsi),
        "summary": {
            "price": round(price, 4), "trend": trend, "ma50": m50, "ma200": m200, "rsi": round(r_now, 1),
            "atr_pct": round(atr_pct(df), 4), "hi52": hi52, "lo52": lo52, "dd52": round(dd, 4),
            "vol_ratio": None if vol_ratio is None else round(vol_ratio, 2),
            "support": sup, "resistance": res, "notes": notes,
        },
    }
