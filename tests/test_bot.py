import copy
import random

from bot import notify, paper, scoring


def rec(t, mkt="US", **kw):
    base = {
        "ticker": t, "name": t, "market": mkt, "sector": "Technology", "industry": "Software",
        "ccy": "USD", "fin_ccy": "USD", "mcap": 5e9, "price": 100.0, "date": "2026-10-26",
        "eps": 5.0, "fcf": 3e8, "ev_ebitda": 10.0, "pb": 3.0, "pe": 20.0,
        "roe": 0.15, "opm": 0.15, "pm": 0.10, "de": 50.0,
        "above200": True, "high52": 110.0, "dd": -0.09, "ret_12_1": 0.10, "ret_1m": 0.01, "rsi": 50.0,
        "recent": {"2026-10-23": 99.0, "2026-10-26": 100.0},
    }
    base.update(kw)
    return base


def universe(n=30, seed=1):
    random.seed(seed)
    out = []
    for i in range(n):
        out.append(rec(f"T{i}", eps=random.uniform(-1, 10), fcf=random.uniform(-1e8, 5e8),
                       ev_ebitda=random.uniform(4, 30), roe=random.uniform(0, 0.4),
                       opm=random.uniform(0, 0.4), pm=random.uniform(0, 0.3), de=random.uniform(0, 200),
                       ret_12_1=random.uniform(-0.3, 0.6)))
    return out


def test_cheap_quality_beats_expensive_junk():
    recs = universe()
    recs.append(rec("GOOD", eps=12, fcf=9e8, ev_ebitda=3, roe=0.5, opm=0.5, pm=0.4, de=5, ret_12_1=0.9))
    recs.append(rec("JUNK", eps=-3, fcf=-5e8, ev_ebitda=40, roe=-0.2, opm=-0.1, pm=-0.2, de=300, ret_12_1=-0.5))
    rows, _ = scoring.score_universe(recs)
    s = {r["ticker"]: r["pct"] for r in rows}
    assert s["GOOD"] > 95
    assert s["JUNK"] < 10


def test_missing_data_is_dropped_not_guessed():
    recs = universe()
    recs.append(rec("EMPTY", eps=None, fcf=None, ev_ebitda=None, pb=None))
    rows, dropped = scoring.score_universe(recs)
    assert "EMPTY" not in {r["ticker"] for r in rows}
    assert any(d["ticker"] == "EMPTY" for d in dropped)


def test_currency_mismatch_does_not_fake_cheapness():
    f = scoring.features(rec("ADR", ccy="USD", fin_ccy="CNY", eps=50.0))
    assert f["ey"] is None and f["fcfy"] is None


def test_small_caps_and_errors_are_dropped():
    recs = universe() + [rec("TINY", mcap=1e6), {"ticker": "ERR", "market": "US", "error": "x"}]
    rows, dropped = scoring.score_universe(recs)
    tickers = {d["ticker"] for d in dropped}
    assert {"TINY", "ERR"} <= tickers


def test_cyclical_flag_and_financial_group():
    recs = universe()
    recs.append(rec("OIL", sector="Energy", industry="Oil & Gas E&P"))
    for i in range(10):
        recs.append(rec(f"B{i}", sector="Financial Services", industry="Banks", pb=0.5 + i * 0.1, roe=0.05 + i * 0.01))
    rows, _ = scoring.score_universe(recs)
    oil = next(r for r in rows if r["ticker"] == "OIL")
    assert oil["cyc"] and any("syklisk" in f for f in oil["flags"])
    assert all(r["fin"] for r in rows if r["ticker"].startswith("B"))


def _scored(recs):
    rows, _ = scoring.score_universe(recs)
    return rows


def test_first_run_is_silent_init_then_monthly_review_only():
    recs = universe(40)
    state = paper.new_state()
    paper.update_ew(state, recs)
    rows = _scored(recs)
    ev = paper.update(state, "2026-10-26", rows, [])
    assert ev and all(e["type"] == "LONG_INIT" for e in ev)
    # ny dag samme måned: ingen langsiktige endringer
    ev2 = paper.update(state, "2026-10-27", rows, [])
    assert not [e for e in ev2 if e["type"].startswith("LONG")]


def test_hysteresis_and_exit_on_next_month():
    recs = universe(40)
    state = paper.new_state()
    paper.update_ew(state, recs)
    rows = _scored(recs)
    paper.update(state, "2026-10-26", rows, [])
    held = next(iter(state["long"]["open"]))
    worse = copy.deepcopy(rows)
    for r in worse:
        if r["ticker"] == held:
            r["pct"] = 40.0
            r["price"] = 120.0
    ev = paper.update(state, "2026-11-02", worse, [])
    exits = [e for e in ev if e["type"] == "LONG_EXIT"]
    assert len(exits) == 1 and exits[0]["ticker"] == held
    assert abs(exits[0]["ret"] - 0.2) < 1e-9
    assert held not in state["long"]["open"]


def test_same_day_rerun_does_nothing():
    recs = universe(40)
    state = paper.new_state()
    paper.update_ew(state, recs)
    rows = _scored(recs)
    paper.update(state, "2026-10-26", rows, [])
    assert paper.update(state, "2026-10-26", rows, []) == []


def test_tactical_exit_rules():
    recs = universe(40)
    state = paper.new_state()
    paper.update_ew(state, recs)
    rows = _scored(recs)
    paper.update(state, "2026-10-26", rows, [])
    t = rows[0]["ticker"]
    sig = [{"ticker": t, "kind": "ny 52-ukers topp"}]
    paper.update(state, "2026-10-27", rows, sig)
    assert t in state["tact"]["open"]
    drop = copy.deepcopy(rows)
    for r in drop:
        if r["ticker"] == t:
            r["price"] = r["price"] * 0.9
    ev = paper.update(state, "2026-10-28", drop, [])
    assert any(e["type"] == "TACT_EXIT" and e["reason"] == "stopp" for e in ev)


def test_notification_only_when_something_happened():
    assert notify.build_message("2026-10-26", [], [], None) is None
    msg = notify.build_message("2026-10-26", [], ["feil"], None)
    assert "feil" in msg


def test_summary_marks_small_samples():
    assert paper.summary([])["enough"] is False
