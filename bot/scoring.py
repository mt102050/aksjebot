"""Rangering: verdi, kvalitet og momentum. Rent regnestykke uten nettverk, så alt kan testes."""
import pandas as pd

from .universe import MIN_MCAP

W_VALUE, W_QUALITY, W_MOM = 0.40, 0.35, 0.25
CYCLICAL_SECTORS = {"Energy", "Basic Materials"}
CYCLICAL_WORDS = ("shipping", "marine", "oil", "drilling", "tanker", "gas", "steel", "aluminum", "copper",
                  "farm products")  # sjømat (laks) og landbruk følger råvarepriser
MIN_GROUP = 8

VALUE_NONFIN = ["ey", "fcfy", "ebitda_y"]
QUAL_NONFIN = ["roe", "opm", "pm", "de_inv"]
VALUE_FIN = ["ey", "by"]
QUAL_FIN = ["roe", "pm"]


def is_financial(r):
    return (r.get("sector") or "") == "Financial Services"


def is_cyclical(r):
    if (r.get("sector") or "") in CYCLICAL_SECTORS:
        return True
    text = ((r.get("industry") or "") + " " + (r.get("sector") or "")).lower()
    return any(w in text for w in CYCLICAL_WORDS)


def features(r, fx=None):
    """Nøkkeltall som verdier. None betyr manglende eller upålitelig tall.
    fx: {(regnskapsvaluta, handelsvaluta): kurs}. Uten kurs droppes tall i annen valuta."""
    price = r.get("price")
    ccy, fin = r.get("ccy"), r.get("fin_ccy")
    rate = 1.0 if not (ccy and fin and ccy != fin) else (fx or {}).get((fin, ccy))
    f = {}
    eps, mcap, fcf = r.get("eps"), r.get("mcap"), r.get("fcf")
    f["ey"] = eps * rate / price if rate and eps is not None and price else None
    f["fcfy"] = fcf * rate / mcap if rate and fcf is not None and mcap else None
    ev = r.get("ev_ebitda")
    f["ebitda_y"] = 1 / ev if ev and ev > 0 else None
    pb = r.get("pb")
    f["by"] = 1 / pb if pb and pb > 0 else None
    # ROE med negativ egenkapital er meningsløst
    f["roe"] = None if (pb is not None and pb < 0) else r.get("roe")
    f["opm"] = r.get("opm")
    f["pm"] = r.get("pm")
    de = r.get("de")
    f["de_inv"] = -de if de is not None else None
    # for sykliske: snittresultat over flere år, og netto gjeld mot EBITDA
    ni, yrs = r.get("ni_avg"), r.get("ni_years") or 0
    f["ney"] = ni * rate / mcap if rate and ni is not None and mcap and yrs >= 3 else None
    debt, cash, ebitda = r.get("debt"), r.get("cash"), r.get("ebitda")
    nd = None
    if ebitda and ebitda > 0 and debt is not None:
        nd = (debt - (cash or 0)) / ebitda
    f["nd_ebitda"] = nd
    f["lev_inv"] = -nd if nd is not None else None
    return f


CYC_W = {"ney": 0.35, "by": 0.25, "lev_inv": 0.15, "mom": 0.25}
CYC_ENTER_MAX_LEVERAGE = 3.0


def cyclical_scores(df, feat):
    """Egen rangering for olje, shipping og råvarer. Bruker snittresultat over flere år
    i stedet for fjorårets resultat, fordi ett toppår gjør P/E misvisende lav."""
    df["cscore"] = float("nan")
    df["cpct"] = float("nan")
    cyc = df[df["cyc"]]
    if cyc.empty:
        return
    counts = cyc["market"].value_counts()
    grp = cyc["market"].where(cyc["market"].map(counts) >= MIN_GROUP, "alle")
    for g in grp.unique():
        idx = grp[grp == g].index
        ranks = pd.DataFrame({
            "ney": feat.loc[idx, "ney"], "by": feat.loc[idx, "by"], "lev_inv": feat.loc[idx, "lev_inv"],
            "mom": df.loc[idx, "ret_12_1"],
        }).astype(float).rank(pct=True) * 100
        w = pd.Series(CYC_W)
        avail = ranks.notna()
        score = (ranks.fillna(0) * w).sum(axis=1) / (avail * w).sum(axis=1)
        ok = avail["mom"] & (avail[["ney", "by", "lev_inv"]].sum(axis=1) >= 2)
        score[~ok] = float("nan")
        df.loc[idx, "cscore"] = score
        df.loc[idx, "cpct"] = score.rank(pct=True) * 100


def _group_score(df, cols, min_n):
    ranks = df[cols].rank(pct=True) * 100
    n = ranks.notna().sum(axis=1)
    score = ranks.mean(axis=1, skipna=True)
    score[n < min_n] = float("nan")
    return score, n


def score_universe(records, fx=None):
    """records: liste med dict (fra data.build_record + market + name).
    Returnerer (rader, ekskluderte). Hver rad får score, pct og flagg."""
    rows, dropped = [], []
    for r in records:
        if "error" in r:
            dropped.append({"ticker": r["ticker"], "reason": "datafeil: " + r["error"]})
            continue
        if r.get("mcap") is None or r["mcap"] < MIN_MCAP.get(r["market"], 1e9):
            dropped.append({"ticker": r["ticker"], "reason": "for lav markedsverdi eller mangler"})
            continue
        row = dict(r)
        row["fin"] = is_financial(r)
        row["cyc"] = is_cyclical(r)
        row["f"] = features(r, fx)
        rows.append(row)
    if not rows:
        return [], dropped

    df = pd.DataFrame(rows)
    # gruppering: (marked, bank/ikke-bank). Små grupper slås sammen per marked.
    df["grp"] = df["market"] + "|" + df["fin"].map({True: "fin", False: "ind"})
    counts = df["grp"].value_counts()
    small = df["grp"].map(counts) < MIN_GROUP
    df.loc[small, "grp"] = df.loc[small, "market"] + "|alle"

    feat = pd.DataFrame(list(df["f"]), index=df.index)
    df["value"] = float("nan")
    df["quality"] = float("nan")
    df["mom"] = float("nan")
    df["nval"] = 0
    df["nqual"] = 0
    for g, idx in df.groupby("grp").groups.items():
        sub = feat.loc[idx]
        fin_mask = df.loc[idx, "fin"]
        for is_fin, vcols, qcols, vmin, qmin in (
            (True, VALUE_FIN, QUAL_FIN, 2, 1),
            (False, VALUE_NONFIN, QUAL_NONFIN, 2, 2),
        ):
            sel = fin_mask[fin_mask == is_fin].index
            if len(sel) == 0:
                continue
            s = sub.loc[sel]
            v, nv = _group_score(s, vcols, vmin)
            q, nq = _group_score(s, qcols, qmin)
            df.loc[sel, "value"], df.loc[sel, "nval"] = v, nv
            df.loc[sel, "quality"], df.loc[sel, "nqual"] = q, nq
        df.loc[idx, "mom"] = df.loc[idx, "ret_12_1"].rank(pct=True) * 100

    wv = df["cyc"].map({True: W_VALUE / 2, False: W_VALUE})
    df["score"] = (wv * df["value"] + W_QUALITY * df["quality"] + W_MOM * df["mom"]) / (wv + W_QUALITY + W_MOM)
    ok = df[["value", "quality", "mom"]].notna().all(axis=1)
    df.loc[~ok, "score"] = float("nan")
    df["pct"] = df.groupby("grp")["score"].rank(pct=True) * 100
    cyclical_scores(df, feat)

    out = []
    for i, r in df.iterrows():
        if pd.isna(r["score"]):
            dropped.append({"ticker": r["ticker"], "reason":
                            f"mangler nok nøkkeltall (verdi {int(r['nval'])}, kvalitet {int(r['nqual'])}, momentum {'ok' if pd.notna(r['mom']) else 'mangler'})"})
            continue
        flags = []
        if r["cyc"]:
            flags.append("syklisk: lav P/E kan bety toppen av syklusen")
        if not r["above200"]:
            flags.append("under 200-dagers snitt")
        d = r.to_dict()
        d["flags"] = flags
        out.append(d)
    return out, dropped


def tactical_signals(rows, max_per_day=5):
    """Daglige signaler. Ingen dokumentert fordel, så dette brukes bare i papirhandel."""
    sig = []
    for r in rows:
        kind = None
        rsi = r.get("rsi")
        if r["above200"] and rsi is not None and rsi < 35 and r["quality"] >= 60:
            kind = "tilbakegang i opptrend"
        elif r["price"] >= 0.995 * r["high52"] and r["quality"] >= 50 and (r.get("ret_1m") or 0) > 0:
            kind = "ny 52-ukers topp"
        if kind:
            sig.append({"ticker": r["ticker"], "name": r["name"], "market": r["market"], "kind": kind,
                        "price": r["price"], "quality": r["quality"], "rsi": rsi})
    sig.sort(key=lambda s: -s["quality"])
    return sig[:max_per_day]
