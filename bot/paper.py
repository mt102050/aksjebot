"""Papirhandel. Ingen ekte penger. Hver anbefaling logges med dato og pris og måles mot indeks."""

ENTER_PCT = 90      # inn når aksjen er blant øverste 10 prosent
EXIT_PCT = 70       # ut når den faller under øverste 30 prosent
MAX_PER_MARKET = 15
MAX_PER_SECTOR = 4
CYC_ENTER_PCT = 80
CYC_EXIT_PCT = 60
CYC_MAX_PER_MARKET = 8
CYC_MAX_LEVERAGE = 3.0  # netto gjeld / EBITDA
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
        "cyc": {"open": {}, "closed": []},
        "inited": {"long": [], "cyc": []},
    }


def migrate(state):
    """Eldre state-filer mangler syklisk bok. Markeder som alt hadde en startliste regnes som startet."""
    state.setdefault("cyc", {"open": {}, "closed": []})
    if "inited" not in state:
        done = sorted(state.get("ew", {})) if state.get("last_review") else []
        state["inited"] = {"long": done, "cyc": []}
    return state


def _long_ok(r):
    return (not r.get("cyc") and r.get("pct") is not None and r["pct"] >= ENTER_PCT
            and r["above200"] and r["quality"] >= 50)


def _cyc_ok(r):
    nd = (r.get("f") or {}).get("nd_ebitda")
    return (r.get("cyc") and _num(r.get("cpct")) is not None and r["cpct"] >= CYC_ENTER_PCT
            and r["above200"] and (nd is None or nd <= CYC_MAX_LEVERAGE))


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


BOOKS = {
    # navn: (sorteringsfelt, inngang, utgangsgrense, maks per marked, hendelsesprefiks, utgangstekst)
    "long": ("pct", _long_ok, EXIT_PCT, MAX_PER_MARKET, "LONG", "falt ut av øverste 30 prosent"),
    "cyc": ("cpct", _cyc_ok, CYC_EXIT_PCT, CYC_MAX_PER_MARKET, "CYC", "falt ut av øverste 40 prosent av sykliske"),
}


def _review(state, name, rows, by_t, today, markets, events):
    key, ok, exit_below, max_mkt, prefix, why = BOOKS[name]
    book = state[name]["open"]
    inited = state["inited"][name]
    for t in list(book):
        p, r = book[t], by_t.get(t)
        if p["market"] not in markets or not r:
            continue
        val = _num(r.get(key))
        if val is None or val < exit_below:
            c = _close(book.pop(t), r["price"], state, today, why)
            state[name]["closed"].append(c)
            events.append({"type": prefix + "_EXIT", **c})
    by_mkt, by_sec = {}, {}
    for t, p in book.items():
        rr = by_t.get(t)
        by_mkt[p["market"]] = by_mkt.get(p["market"], 0) + 1
        if rr:
            k = (p["market"], rr.get("sector"))
            by_sec[k] = by_sec.get(k, 0) + 1
    for r in sorted(rows, key=lambda x: -(_num(x.get(key)) or 0)):
        if r["market"] not in markets or r["ticker"] in book or not ok(r):
            continue
        k = (r["market"], r.get("sector"))
        if by_mkt.get(r["market"], 0) >= max_mkt or by_sec.get(k, 0) >= MAX_PER_SECTOR:
            continue
        by_mkt[r["market"]] = by_mkt.get(r["market"], 0) + 1
        by_sec[k] = by_sec.get(k, 0) + 1
        book[r["ticker"]] = _pos(r, state, today)
        kind = "_INIT" if r["market"] not in inited else "_ENTER"
        events.append({"type": prefix + kind, **book[r["ticker"]], "pct": _num(r.get(key))})
    for m in markets:
        if m not in inited:
            inited.append(m)


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
    migrate(state)
    if state["last_date"] and today <= state["last_date"]:
        # ingen ny handelsdag: bare nye markeder eller bøker får startliste
        by_t = {r["ticker"]: r for r in rows}
        all_mkts = sorted({r["market"] for r in rows})
        for name in BOOKS:
            new = [m for m in all_mkts if m not in state["inited"][name]]
            if new:
                _review(state, name, rows, by_t, today, new, events)
        return events

    first_run = state["last_date"] is None
    by_t = {r["ticker"]: r for r in rows}
    do_review = is_review_day(state, today) if review is None else review
    all_mkts = sorted({r["market"] for r in rows})

    # --- langsiktig og syklisk bok: hele listen månedlig, nye markeder med en gang ---
    for name in BOOKS:
        markets = all_mkts if do_review else [m for m in all_mkts if m not in state["inited"][name]]
        if markets:
            _review(state, name, rows, by_t, today, markets, events)
    if do_review:
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
