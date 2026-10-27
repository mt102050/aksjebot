"""Testporteføljer på papir. Svarer på ett spørsmål: slår rangeringen indeks og tilfeldige valg
etter kurtasje? Alle beløp i kroner.

A: topp 5 fra Oslo og Europa (det som kan ligge på ASK)
B: topp 5 fra alle markeder
C: like mange tilfeldige aksjer fra samme univers som A, samme dag (kontrollgruppe)

Regler:
- Signal på dagens rangering. Kjøp og salg skjer til sluttkurs ved neste kjøring (dagen etter).
- 1000 kr per post. Kjøper bare aksjer porteføljen ikke eier, og bare de som oppfyller kravene til kjøpslisten.
- Hver post holdes i inntil 91 dager. A og B selger tidligere hvis aksjen faller under øverste 30 prosent.
- Samme kronebeløp går samme dag inn i indeksen for aksjens marked (skyggeportefølje, uten kurtasje).
- Kurtasje: Nordnet Mini. Valutapåslag ved automatisk veksling. Justér under hvis klassen din er en annen.
- Utbytte er ikke med, verken for aksjer eller indeks.
"""
import datetime as dt
import random

LOT_NOK = 1000.0
PICKS = 5
HOLD_DAYS = 91
EXIT_PCT = 70
ENTER_PCT = 90
MAX_PENDING_DAYS = 5

# Nordnet Mini (prisliste oktober 2026): Norden 0,15 % min 29 kr, utenfor Norden 0,2 % min 49 kr.
FEE_NORDIC = (0.0015, 29.0)
FEE_OTHER = (0.0020, 49.0)
FX_FEE = 0.0025  # automatisk valutaveksling, per kjøp og per salg
NORDIC_SUFFIX = (".OL", ".ST", ".CO", ".HE")

PORTS = {
    "A": "Topp 5, Oslo og Europa",
    "B": "Topp 5, alle markeder",
    "C": "Tilfeldig 5, Oslo og Europa (kontroll)",
}
ASK_MARKETS = ("NO", "EU")


def fee(ticker, amount_nok, ccy):
    pct, minimum = FEE_NORDIC if ticker.endswith(NORDIC_SUFFIX) else FEE_OTHER
    f = max(amount_nok * pct, minimum)
    if ccy and ccy != "NOK":
        f += amount_nok * FX_FEE
    return f


def new_test():
    return {
        "last_date": None,
        "pending": [],
        "ports": {k: {"lots": [], "closed": [], "realized": 0.0, "invested": 0.0, "fees": 0.0,
                      "bench_lots": [], "bench_realized": 0.0} for k in PORTS},
        "history": [],
    }


def _days(a, b):
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days


def _nok(price, ccy, fx):
    if ccy in (None, "NOK"):
        return price
    r = fx.get(ccy)
    return price * r if r else None


def qualifies(r):
    return (not r.get("cyc") and r.get("pct") is not None and r["pct"] >= ENTER_PCT
            and r["above200"] and r["quality"] >= 50)


def _held(port, pending, name):
    return {l["ticker"] for l in port["lots"]} | {o["ticker"] for o in pending if o["port"] == name}


def make_orders(test, today, rows, rng_seed=None):
    """Nye kjøpsordre basert på dagens rangering. Utføres ved neste kjøring."""
    orders = []
    ask = [r for r in rows if r["market"] in ASK_MARKETS]
    for name, pool in (("A", ask), ("B", rows)):
        held = _held(test["ports"][name], test["pending"], name)
        picks = [r for r in sorted(pool, key=lambda x: -x["pct"]) if qualifies(r) and r["ticker"] not in held][:PICKS]
        orders += [{"port": name, "side": "buy", "ticker": r["ticker"], "market": r["market"], "signal": today}
                   for r in picks]
    n_a = sum(1 for o in orders if o["port"] == "A")
    held_c = _held(test["ports"]["C"], test["pending"], "C")
    pool_c = sorted(r["ticker"] for r in ask if r["ticker"] not in held_c and not r.get("cyc"))
    rng = random.Random(rng_seed or today)
    by_t = {r["ticker"]: r for r in ask}
    for t in rng.sample(pool_c, min(n_a, len(pool_c))):
        orders.append({"port": "C", "side": "buy", "ticker": t, "market": by_t[t]["market"], "signal": today})
    return orders


def sell_orders(test, today, by_t):
    out = []
    pend = {(o["port"], o["ticker"]) for o in test["pending"] if o["side"] == "sell"}
    for name, port in test["ports"].items():
        for l in port["lots"]:
            if (name, l["ticker"]) in pend:
                continue
            r = by_t.get(l["ticker"])
            reason = None
            if _days(today, l["buy_date"]) >= HOLD_DAYS:
                reason = "holdetid ute"
            elif name in ("A", "B") and r is not None and r.get("pct") is not None and r["pct"] < EXIT_PCT:
                reason = "falt ut av øverste 30 prosent"
            if reason:
                out.append({"port": name, "side": "sell", "ticker": l["ticker"], "signal": today, "reason": reason})
    return out


def execute(test, today, by_t, fx, bench):
    """Utfører ventende ordre til dagens sluttkurs. bench: {marked: (indeksnivå, valuta)}."""
    events, keep = [], []
    for o in test["pending"]:
        if o["signal"] >= today:
            keep.append(o)
            continue
        r = by_t.get(o["ticker"])
        port = test["ports"][o["port"]]
        if o["side"] == "buy":
            px = _nok(r["price"], r.get("ccy"), fx) if r else None
            b = bench.get(o["market"])
            bpx = _nok(b[0], b[1], fx) if b else None
            if not px or not bpx:
                if _days(today, o["signal"]) <= MAX_PENDING_DAYS:
                    keep.append(o)
                continue
            f = fee(o["ticker"], LOT_NOK, r.get("ccy"))
            lot = {"ticker": o["ticker"], "name": r["name"], "market": o["market"], "ccy": r.get("ccy"),
                   "signal": o["signal"], "buy_date": today, "buy_nok": px, "shares": (LOT_NOK - f) / px,
                   "fee_buy": f, "last_nok": px}
            port["lots"].append(lot)
            port["invested"] += LOT_NOK
            port["fees"] += f
            port["bench_lots"].append({"ticker": o["ticker"], "market": o["market"], "units": LOT_NOK / bpx,
                                       "buy_date": today, "last_nok": bpx})
            events.append({"type": "TEST_BUY", "port": o["port"], "ticker": o["ticker"], "price_nok": px})
        else:
            lot = next((l for l in port["lots"] if l["ticker"] == o["ticker"]), None)
            if not lot:
                continue
            px = _nok(r["price"], r.get("ccy"), fx) if r else None
            px = px or lot["last_nok"]
            gross = lot["shares"] * px
            f = fee(o["ticker"], gross, lot.get("ccy"))
            net = gross - f
            port["lots"].remove(lot)
            port["realized"] += net
            port["fees"] += f
            bl = next((b for b in port["bench_lots"] if b["ticker"] == o["ticker"] and b["buy_date"] == lot["buy_date"]), None)
            b_net = None
            if bl:
                bm = bench.get(bl["market"])
                bpx = (_nok(bm[0], bm[1], fx) if bm else None) or bl["last_nok"]
                b_net = bl["units"] * bpx
                port["bench_lots"].remove(bl)
                port["bench_realized"] += b_net
            c = {**lot, "sell_date": today, "sell_nok": px, "net": net, "fee_sell": f, "reason": o.get("reason"),
                 "ret": net / LOT_NOK - 1, "bench_ret": None if b_net is None else b_net / LOT_NOK - 1}
            port["closed"].append(c)
            events.append({"type": "TEST_SELL", "port": o["port"], "ticker": o["ticker"], "ret": c["ret"]})
    test["pending"] = keep
    return events


def mark(test, today, by_t, fx, bench):
    """Verdsetter alle åpne poster og lagrer et punkt i historikken."""
    snap = {"date": today}
    for name, port in test["ports"].items():
        val = 0.0
        for l in port["lots"]:
            r = by_t.get(l["ticker"])
            px = _nok(r["price"], r.get("ccy"), fx) if r else None
            if px:
                l["last_nok"] = px
            val += l["shares"] * l["last_nok"]
        bval = 0.0
        for b in port["bench_lots"]:
            bm = bench.get(b["market"])
            px = _nok(bm[0], bm[1], fx) if bm else None
            if px:
                b["last_nok"] = px
            bval += b["units"] * b["last_nok"]
        inv = port["invested"]
        snap[name] = {
            "invested": round(inv, 2),
            "value": round(val + port["realized"], 2),
            "bench": round(bval + port["bench_realized"], 2),
            "fees": round(port["fees"], 2),
            "open": len(port["lots"]),
        }
    test["history"] = [h for h in test["history"] if h["date"] != today] + [snap]
    return snap


def run_day(test, today, rows, fx, bench):
    """Én dag: utfør gårsdagens ordre, verdsett, lag nye ordre. Gjør ingenting to ganger samme dag."""
    if test["last_date"] and today <= test["last_date"]:
        return []
    by_t = {r["ticker"]: r for r in rows}
    events = execute(test, today, by_t, fx, bench)
    mark(test, today, by_t, fx, bench)
    test["pending"] += sell_orders(test, today, by_t)
    test["pending"] += make_orders(test, today, rows)
    test["last_date"] = today
    return events


def summary(test):
    out = {}
    last = test["history"][-1] if test["history"] else None
    for name, port in test["ports"].items():
        h = last.get(name) if last else None
        inv = h["invested"] if h else 0
        closed = port["closed"]
        ex = [c["ret"] - c["bench_ret"] for c in closed if c.get("bench_ret") is not None]
        out[name] = {
            "label": PORTS[name],
            "invested": inv,
            "value": h["value"] if h else 0,
            "bench": h["bench"] if h else 0,
            "ret": (h["value"] / inv - 1) if h and inv else None,
            "bench_ret": (h["bench"] / inv - 1) if h and inv else None,
            "fees": round(port["fees"], 2),
            "open": len(port["lots"]),
            "closed": len(closed),
            "avg_excess_closed": sum(ex) / len(ex) if ex else None,
            "hit_rate": sum(1 for c in closed if c["ret"] > 0) / len(closed) if closed else None,
        }
    out["days"] = len(test["history"])
    return out
