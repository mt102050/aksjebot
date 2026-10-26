"""Papirhandel. Ingen ekte penger. Hver anbefaling logges med dato og pris og måles mot indeks."""

ENTER_PCT = 90      # inn når aksjen er blant øverste 10 prosent
EXIT_PCT = 70       # ut når den faller under øverste 30 prosent
TACT_TARGET = 0.15
TACT_STOP = -0.08
TACT_MAX_DAYS = 40


def new_state():
    return {
        "version": 1,
        "last_date": None,
        "last_review": None,
        "ew": {},
        "real": {},
        "long": {"open": {}, "closed": []},
        "tact": {"open": {}, "closed": []},
    }


def update_ew(state, records):
    """Likevektet indeks over universet per marked. Gir referanse for 'slår screeningen snittaksjen'."""
    by_mkt = {}
    for r in records:
        if "error" in r or "recent" not in r:
            continue
        by_mkt.setdefault(r["market"], []).append(r)
    warnings = []
    for mkt, recs in by_mkt.items():
        last_date = max(r["date"] for r in recs)
        prev = state["ew"].get(mkt)
        if prev is None:
            state["ew"][mkt] = {"level": 100.0, "date": last_date}
            continue
        if last_date <= prev["date"]:
            continue
        rets = []
        for r in recs:
            rc = r["recent"]
            if prev["date"] in rc and last_date in rc and rc[prev["date"]] > 0:
                rets.append(rc[last_date] / rc[prev["date"]] - 1)
        if len(rets) < 10:
            warnings.append(f"{mkt}: for få aksjer med overlapp til å oppdatere likevektsindeksen")
            continue
        state["ew"][mkt] = {"level": prev["level"] * (1 + sum(rets) / len(rets)), "date": last_date}
    return warnings


def _pos(r, state, today):
    return {
        "ticker": r["ticker"], "name": r["name"], "market": r["market"],
        "entry_date": today, "entry_price": r["price"],
        "entry_ew": state["ew"].get(r["market"], {}).get("level"),
        "entry_real": state["real"].get(r["market"]),
    }


def _close(p, price, state, today, reason):
    ew_now = state["ew"].get(p["market"], {}).get("level")
    real_now = state["real"].get(p["market"])
    ret = price / p["entry_price"] - 1
    ew_ret = ew_now / p["entry_ew"] - 1 if ew_now and p.get("entry_ew") else None
    real_ret = real_now / p["entry_real"] - 1 if real_now and p.get("entry_real") else None
    return {
        **p, "exit_date": today, "exit_price": price, "reason": reason,
        "ret": ret, "ew_ret": ew_ret, "real_ret": real_ret,
        "excess_ew": None if ew_ret is None else ret - ew_ret,
        "excess_real": None if real_ret is None else ret - real_ret,
    }


def is_review_day(state, today):
    return state["last_review"] != today[:7]


def update(state, today, rows, tactical, review=None):
    """Oppdaterer papirporteføljen. Returnerer hendelser. Langsiktig vurderes første kjøring hver måned."""
    events = []
    if state["last_date"] and today <= state["last_date"]:
        return events  # ingen ny handelsdag

    first_run = state["last_date"] is None
    by_t = {r["ticker"]: r for r in rows}
    do_review = is_review_day(state, today) if review is None else review

    # --- langsiktig bok ---
    if do_review:
        lo = state["long"]["open"]
        for t in list(lo):
            r = by_t.get(t)
            if r and r["pct"] < EXIT_PCT:
                c = _close(lo.pop(t), r["price"], state, today, "falt ut av øverste 30 prosent")
                state["long"]["closed"].append(c)
                events.append({"type": "LONG_EXIT", **c})
        for r in sorted(rows, key=lambda x: -x["pct"]):
            if r["ticker"] in lo:
                continue
            if r["pct"] >= ENTER_PCT and r["above200"] and r["quality"] >= 50:
                lo[r["ticker"]] = _pos(r, state, today)
                events.append({"type": "LONG_INIT" if first_run else "LONG_ENTER", **lo[r["ticker"]],
                               "pct": r["pct"]})
        state["last_review"] = today[:7]

    # --- taktisk bok ---
    to = state["tact"]["open"]
    for t in list(to):
        p, r = to[t], by_t.get(t)
        if not r:
            continue
        ret = r["price"] / p["entry_price"] - 1
        age = (_days(today) - _days(p["entry_date"]))
        reason = None
        if ret >= TACT_TARGET:
            reason = "mål nådd"
        elif ret <= TACT_STOP:
            reason = "stopp"
        elif age >= TACT_MAX_DAYS:
            reason = "tid ute"
        if reason:
            c = _close(to.pop(t), r["price"], state, today, reason)
            state["tact"]["closed"].append(c)
            events.append({"type": "TACT_EXIT", **c})
    if not first_run:
        for s in tactical:
            if s["ticker"] in to or s["ticker"] not in by_t:
                continue
            p = _pos(by_t[s["ticker"]], state, today)
            p["kind"] = s["kind"]
            to[s["ticker"]] = p
            events.append({"type": "TACT_ENTER", **p})

    state["last_date"] = today
    return events


def _days(d):
    import datetime as dt
    return dt.date.fromisoformat(d).toordinal()


def summary(closed):
    """Ærlig oppsummering. Få handler betyr at tallene sier lite."""
    n = len(closed)
    ex = [c["excess_ew"] for c in closed if c.get("excess_ew") is not None]
    exr = [c["excess_real"] for c in closed if c.get("excess_real") is not None]
    rets = [c["ret"] for c in closed]
    return {
        "n": n,
        "avg_ret": sum(rets) / n if n else None,
        "avg_excess_ew": sum(ex) / len(ex) if ex else None,
        "avg_excess_real": sum(exr) / len(exr) if exr else None,
        "hit_rate": sum(1 for r in rets if r > 0) / n if n else None,
        "enough": n >= 30,
    }
