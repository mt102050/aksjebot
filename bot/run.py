"""Daglig kjøring: hent data, rangér, oppdater papirportefølje, skriv data til docs/data og send varsler."""
import datetime as dt
import json
import pathlib
import sys

from . import data, notify, paper, scoring, universe

OUT = pathlib.Path("docs/data")
MIN_COVERAGE = {"US": 0.80, "NO": 0.55}


def load_state():
    f = OUT / "state.json"
    if f.exists():
        return json.loads(f.read_text())
    return paper.new_state()


def slim(r, in_book):
    f = r["f"]
    return {
        "ticker": r["ticker"], "name": r["name"], "market": r["market"], "sector": r.get("sector"),
        "ccy": r.get("ccy"), "price": round(r["price"], 2), "mcap": r.get("mcap"),
        "score": round(r["score"], 1), "pct": round(r["pct"], 1),
        "value": round(r["value"], 1), "quality": round(r["quality"], 1), "mom": round(r["mom"], 1),
        "above200": bool(r["above200"]), "dd": round(r["dd"], 3), "rsi": None if r.get("rsi") is None else round(r["rsi"], 1),
        "ret_12_1": None if r.get("ret_12_1") is None else round(r["ret_12_1"], 3),
        "fin": bool(r["fin"]), "cyc": bool(r["cyc"]), "flags": r["flags"], "in_book": in_book,
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
    for r in recs:
        r.update({"name": meta[r["ticker"]]["name"], "market": meta[r["ticker"]]["market"]})

    # datadekning: stopp heller enn å gi anbefalinger på dårlig grunnlag
    for mkt, need in MIN_COVERAGE.items():
        total = sum(1 for u in uni if u["market"] == mkt)
        good = sum(1 for r in recs if r["market"] == mkt and "error" not in r)
        if total and good / total < need:
            msg = f"Datafeil {mkt}: bare {good} av {total} aksjer hentet. Ingen anbefalinger i dag."
            notify.send("Aksjebot: " + msg)
            print(msg)
            sys.exit(1)

    idx = data.fetch_all([t for t, _ in universe.INDICES])
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
    rows, dropped = scoring.score_universe(recs)
    if not rows:
        notify.send("Aksjebot: ingen aksjer kunne rangeres i dag.")
        sys.exit(1)
    as_of = max(r["date"] for r in recs if "error" not in r)
    tact = scoring.tactical_signals(rows)

    events = paper.update(state, as_of, rows, tact)
    in_book = set(state["long"]["open"])
    failed = [r["ticker"] for r in recs if "error" in r]
    if failed:
        warnings_page = [f"{len(failed)} tickere feilet (se liste i appen)"]
    else:
        warnings_page = []

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "as_of": as_of,
        "universe": {m: {"n": sum(1 for u in uni if u["market"] == m),
                         "scored": sum(1 for r in rows if r["market"] == m)} for m in ("US", "NO")},
        "warnings": warnings + warnings_page,
        "failed": failed,
        "dropped": dropped[:400],
        "rows": [slim(r, r["ticker"] in in_book) for r in sorted(rows, key=lambda x: -x["pct"])],
        "tactical": tact,
        "indices": index_rows(idx),
        "events": events,
        "summary": {"long": paper.summary(state["long"]["closed"]), "tact": paper.summary(state["tact"]["closed"])},
    }
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    (OUT / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1))

    weekly = None
    if dt.date.fromisoformat(as_of).weekday() == 0:
        s = out["summary"]["long"]
        weekly = f"Ukestatus: {len(state['long']['open'])} åpne langsiktige, {len(state['tact']['open'])} åpne taktiske. Lukkede langsiktige: {s['n']}."
    msg = notify.build_message(as_of, events, warnings, weekly)
    if msg:
        notify.send(msg)
    print(f"Ferdig {as_of}: {len(rows)} rangert, {len(events)} hendelser, {len(failed)} feilet.")


if __name__ == "__main__":
    main()
