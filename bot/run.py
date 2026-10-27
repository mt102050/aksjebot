"""Daglig kjøring: hent data, rangér, oppdater papirportefølje, skriv data til docs/data og send varsler."""
import datetime as dt
import json
import math
import pathlib
import sys

from . import data, notify, paper, scoring, universe

OUT = pathlib.Path("docs/data")
MIN_COVERAGE = {"US": 0.80, "NO": 0.55, "EU": 0.60}


def clean(x):
    """JSON tillater ikke NaN eller Infinity. Nettleseren nekter å lese slike filer, så de blir null."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def dump(obj, **kw):
    return json.dumps(clean(obj), ensure_ascii=False, allow_nan=False, **kw)


def load_state():
    f = OUT / "state.json"
    if f.exists():
        return paper.migrate(json.loads(f.read_text()))
    return paper.new_state()


def _r(x, n=1):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else round(v, n)


def slim(r, in_book, in_cyc=False):
    f = r["f"]
    return {
        "ticker": r["ticker"], "name": r["name"], "market": r["market"], "sector": r.get("sector"),
        "ccy": r.get("ccy"), "price": round(r["price"], 2), "mcap": r.get("mcap"),
        "score": round(r["score"], 1), "pct": round(r["pct"], 1),
        "value": round(r["value"], 1), "quality": round(r["quality"], 1), "mom": round(r["mom"], 1),
        "above200": bool(r["above200"]), "dd": round(r["dd"], 3), "rsi": None if r.get("rsi") is None else round(r["rsi"], 1),
        "ret_12_1": None if r.get("ret_12_1") is None else round(r["ret_12_1"], 3),
        "fin": bool(r["fin"]), "cyc": bool(r["cyc"]), "flags": r["flags"], "in_book": in_book,
        "in_cyc": in_cyc, "cscore": _r(r.get("cscore")), "cpct": _r(r.get("cpct")),
        "m": {k: (None if v is None else round(v, 4)) for k, v in f.items()},
        "pe": r.get("pe"), "pb": r.get("pb"),
    }


def index_rows(recs):
    out = []
    names = dict(universe.INDICES)
    for r in recs:
        if "error" in r:
            continue
        out.append({
            "ticker": r["ticker"], "name": names.get(r["ticker"], r["ticker"]), "price": round(r["price"], 2),
            "above200": bool(r["above200"]), "dd": round(r["dd"], 3),
            "ret_12_1": None if r.get("ret_12_1") is None else round(r["ret_12_1"], 3),
            "pe": r.get("pe"),
        })
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    state = load_state()
    warnings = []

    uni = universe.load()
    meta = {u["ticker"]: u for u in uni}
    recs = data.fetch_all([u["ticker"] for u in uni])
    bad = [r["ticker"] for r in recs if "error" in r]
    if bad:  # Yahoo stryper ofte tempoet. Ny runde, sakte og én om gangen.
        again = {r["ticker"]: r for r in data.fetch_all(bad, workers=1, pause=4.0, sleep=1.0)}
        recs = [again.get(r["ticker"], r) if "error" in r else r for r in recs]
    for r in recs:
        r.update({"name": meta[r["ticker"]]["name"], "market": meta[r["ticker"]]["market"]})
    recs = data.mark_stale(recs)
    pairs = {(r["fin_ccy"], r["ccy"]) for r in recs if "error" not in r and r.get("fin_ccy") and r.get("ccy")
             and r["fin_ccy"] != r["ccy"] and len(r["fin_ccy"]) == 3 and len(r["ccy"]) == 3
             and r["fin_ccy"].isupper() and r["ccy"].isupper()}
    fx = {}
    for fin, ccy in pairs:
        q = data.fetch_one(f"{fin}{ccy}=X", retries=2, with_info=False)
        if "error" not in q:
            fx[(fin, ccy)] = q["price"]

    # datadekning: stopp heller enn å gi anbefalinger på dårlig grunnlag
    for mkt, need in MIN_COVERAGE.items():
        total = sum(1 for u in uni if u["market"] == mkt)
        good = sum(1 for r in recs if r["market"] == mkt and "error" not in r)
        if total and good / total < need:
            msg = f"Datafeil {mkt}: bare {good} av {total} aksjer hentet. Ingen anbefalinger i dag."
            notify.send("Aksjebot: " + msg)
            print(msg)
            sys.exit(1)

    idx = data.fetch_all([t for t, _ in universe.INDICES], with_info=False)
    real = {}
    for mkt, cands in universe.REAL_BENCH.items():
        for t in cands:
            hit = next((r for r in idx if r["ticker"] == t and "error" not in r), None)
            if hit is None:
                hit = data.fetch_one(t, retries=2, with_info=False)
            if "error" not in hit:
                real[mkt] = hit["price"]
                break
        else:
            warnings.append(f"Fant ikke indeksreferanse for {mkt}. Bruker bare likevektsindeksen.")
    state["real"].update(real)

    warnings += paper.update_ew(state, recs)
    rows, dropped = scoring.score_universe(recs, fx)
    if not rows:
        notify.send("Aksjebot: ingen aksjer kunne rangeres i dag.")
        sys.exit(1)
    as_of = max(r["date"] for r in recs if "error" not in r)
    dates = {}
    for r in recs:
        if "error" not in r:
            dates[r["market"]] = max(dates.get(r["market"], ""), r["date"])
    label = {"NO": "Oslo", "EU": "Europa", "US": "USA"}
    lag_notes = []  # bare i appen, ikke på Telegram
    for m, d in sorted(dates.items()):
        if d < as_of:
            lag_notes.append(f"{label.get(m, m)}: siste kurs er fra {d}. Yahoo ligger etter.")
    tact = scoring.tactical_signals(rows)

    events = paper.update(state, as_of, rows, tact)
    in_book = set(state["long"]["open"])
    in_cyc = set(state["cyc"]["open"])
    failed = [r["ticker"] for r in recs if "error" in r and "for lite kurshistorikk" not in r["error"]]
    if failed:
        warnings_page = [f"{len(failed)} tickere feilet (se liste i appen)"]
    else:
        warnings_page = []

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "as_of": as_of,
        "dates": dates,
        "universe": {m: {"n": sum(1 for u in uni if u["market"] == m),
                         "scored": sum(1 for r in rows if r["market"] == m)} for m in ("NO", "EU", "US")},
        "warnings": warnings + warnings_page + lag_notes,
        "failed": failed,
        "dropped": dropped[:400],
        "rows": [slim(r, r["ticker"] in in_book, r["ticker"] in in_cyc) for r in sorted(rows, key=lambda x: -x["pct"])],
        "tactical": tact,
        "indices": index_rows(idx),
        "events": events,
        "summary": {"long": paper.summary(state["long"]["closed"]), "tact": paper.summary(state["tact"]["closed"]),
                    "cyc": paper.summary(state["cyc"]["closed"])},
    }
    (OUT / "latest.json").write_text(dump(out, separators=(",", ":")))
    (OUT / "state.json").write_text(dump(state, indent=1))

    weekly = None
    if dt.date.fromisoformat(as_of).weekday() == 0:
        s = out["summary"]["long"]
        weekly = f"Ukestatus: {len(state['long']['open'])} på kjøpslisten, {len(state['cyc']['open'])} på syklisk liste, {len(state['tact']['open'])} åpne taktiske. Lukkede langsiktige: {s['n']}."
    msg = notify.build_message(as_of, events, warnings, weekly)
    if msg:
        notify.send(msg)
    print(f"Ferdig {as_of}: {len(rows)} rangert, {len(events)} hendelser, {len(failed)} feilet.")


if __name__ == "__main__":
    main()
