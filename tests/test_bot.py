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


def test_fx_conversion_makes_foreign_reporters_scorable():
    r = rec("EQNR.OL", mkt="NO", ccy="NOK", fin_ccy="USD", eps=2.0, price=100.0, fcf=1e9, mcap=1e10)
    assert scoring.features(r, None)["ey"] is None
    f = scoring.features(r, {("USD", "NOK"): 10.0})
    assert abs(f["ey"] - 0.2) < 1e-9 and abs(f["fcfy"] - 1.0) < 1e-9


def test_cyclicals_and_sector_cap_keep_book_diverse():
    recs = universe(40)
    for i in range(12):
        recs.append(rec(f"E{i}", sector="Energy", industry="Oil & Gas E&P", eps=15, fcf=9e8, ev_ebitda=3,
                        roe=0.5, opm=0.5, pm=0.4, de=5, ret_12_1=0.9))
    for i in range(12):
        recs.append(rec(f"S{i}", sector="Healthcare", industry="Drug", eps=14, fcf=9e8, ev_ebitda=3.5,
                        roe=0.5, opm=0.5, pm=0.4, de=5, ret_12_1=0.8))
    state = paper.new_state()
    paper.update_ew(state, recs)
    rows = _scored(recs)
    paper.update(state, "2026-10-26", rows, [])
    held = state["long"]["open"]
    assert not any(t.startswith("E") for t in held)
    health = [t for t in held if t.startswith("S")]
    assert len(health) <= paper.MAX_PER_SECTOR


def test_stale_prices_are_rejected():
    from bot import data
    recs = [rec("A"), rec("B", date="2022-05-01"), rec("C")]
    out = data.mark_stale(recs)
    assert "error" in next(r for r in out if r["ticker"] == "B")
    assert "error" not in next(r for r in out if r["ticker"] == "A")


def test_intraday_bar_is_dropped_before_us_close():
    import datetime as dt
    import pandas as pd
    from bot import data
    idx = pd.to_datetime(["2026-10-26", "2026-10-27"])
    s = pd.Series([100.0, 101.0], index=idx)
    morning = dt.datetime(2026, 10, 27, 8, 0, tzinfo=dt.timezone.utc)
    night = dt.datetime(2026, 10, 27, 22, 0, tzinfo=dt.timezone.utc)
    assert len(data.drop_intraday(s, morning)) == 1
    assert len(data.drop_intraday(s, night)) == 2


def test_output_json_never_contains_nan():
    import json
    from bot import run
    txt = run.dump({"a": float("nan"), "b": [float("inf"), 1.5], "c": {"d": None}})
    assert "NaN" not in txt and "Infinity" not in txt
    assert json.loads(txt) == {"a": None, "b": [None, 1.5], "c": {"d": None}}


def _cyc_universe():
    recs = universe(30)
    for i in range(12):
        recs.append(rec(f"C{i}", sector="Energy", industry="Oil & Gas E&P", ni_avg=1e8 * (i + 1), ni_years=4,
                        mcap=5e9, pb=1.0 + i * 0.1, debt=1e9, cash=5e8, ebitda=1e9, ret_12_1=0.05 * i))
    return recs


def test_cyclicals_get_own_score_from_normalised_earnings():
    rows = _scored(_cyc_universe())
    c = {r["ticker"]: r for r in rows if r["cyc"]}
    assert len(c) == 12 and all(r["cscore"] == r["cscore"] for r in c.values())
    assert c["C11"]["cpct"] > c["C0"]["cpct"]
    assert all(r["cscore"] != r["cscore"] for r in rows if not r["cyc"])  # NaN for ikke-sykliske


def test_cyclical_book_holds_only_cyclicals_and_respects_leverage():
    recs = _cyc_universe()
    recs[-1]["debt"] = 9e9  # C11: netto gjeld / EBITDA over 8
    state = paper.new_state()
    paper.update_ew(state, recs)
    paper.update(state, "2026-10-26", _scored(recs), [])
    held = state["cyc"]["open"]
    assert held and all(t.startswith("C") for t in held)
    assert "C11" not in held
    assert not any(t.startswith("C") for t in state["long"]["open"])


def test_new_market_gets_start_list_mid_month():
    us = universe(40)
    state = paper.new_state()
    paper.update_ew(state, us)
    paper.update(state, "2026-10-26", _scored(us), [])
    eu = [dict(r, ticker="E" + r["ticker"], market="EU", ccy="EUR", fin_ccy="EUR") for r in universe(40, seed=3)]
    both = us + eu
    paper.update_ew(state, both)
    ev = paper.update(state, "2026-10-27", _scored(both), [])
    longs = [e for e in ev if e["type"].startswith("LONG")]
    assert longs and all(e["type"] == "LONG_INIT" and e["market"] == "EU" for e in longs)


def test_migrate_old_state_keeps_existing_markets():
    old = paper.new_state()
    del old["cyc"], old["inited"]
    old["last_review"] = "2026-10"
    old["ew"] = {"US": {"level": 100, "date": "2026-10-26"}, "NO": {"level": 100, "date": "2026-10-26"}}
    s = paper.migrate(old)
    assert s["inited"]["long"] == ["NO", "US"] and s["inited"]["cyc"] == [] and "cyc" in s


def test_new_book_starts_even_without_new_trading_day():
    recs = _cyc_universe()
    state = paper.new_state()
    paper.update_ew(state, recs)
    rows = _scored(recs)
    paper.update(state, "2026-10-26", rows, [])
    state["cyc"] = {"open": {}, "closed": []}
    state["inited"]["cyc"] = []
    ev = paper.update(state, "2026-10-26", rows, [])
    assert ev and all(e["type"] == "CYC_INIT" for e in ev)
    assert paper.update(state, "2026-10-26", rows, []) == []


def test_position_closes_at_last_price_when_ticker_disappears():
    recs = universe(40)
    state = paper.new_state()
    paper.update_ew(state, recs)
    rows = _scored(recs)
    paper.update(state, "2026-10-26", rows, [])
    gone = next(iter(state["long"]["open"]))
    paper.update(state, "2026-10-27", rows, [])
    left = [r for r in rows if r["ticker"] != gone]
    ev = paper.update(state, "2026-11-02", left, [])
    ex = [e for e in ev if e["type"] == "LONG_EXIT" and e["ticker"] == gone]
    assert ex and ex[0]["reason"] == "ikke lenger i universet"


def test_seafood_counts_as_cyclical_and_mcap_fallback():
    from bot import data
    assert scoring.is_cyclical({"sector": "Consumer Defensive", "industry": "Farm Products"})
    assert data._mcap_fallback({"sharesOutstanding": 1e6}, 50.0) == 5e7
    assert data._mcap_fallback({}, 50.0) is None
