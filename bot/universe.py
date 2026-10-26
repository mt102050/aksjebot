"""Aksjeunivers. Oslo Børs er en håndlaget liste. Tickere som Yahoo ikke kjenner hoppes over og logges."""
import io

import pandas as pd
import requests

SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"

# (Yahoo-ticker, navn). Sjekk listen jevnlig. Feil tickere gir bare en advarsel i rapporten.
OSLO = [
    ("EQNR.OL", "Equinor"), ("DNB.OL", "DNB Bank"), ("MOWI.OL", "Mowi"), ("TEL.OL", "Telenor"),
    ("NHY.OL", "Norsk Hydro"), ("ORK.OL", "Orkla"), ("YAR.OL", "Yara"), ("AKRBP.OL", "Aker BP"),
    ("SALM.OL", "SalMar"), ("GJF.OL", "Gjensidige"), ("STB.OL", "Storebrand"), ("SUBC.OL", "Subsea 7"),
    ("TOM.OL", "Tomra"), ("KOG.OL", "Kongsberg Gruppen"), ("SCATC.OL", "Scatec"), ("AUTO.OL", "Autostore"),
    ("BAKKA.OL", "Bakkafrost"), ("LSG.OL", "Lerøy Seafood"), ("NAS.OL", "Norwegian Air Shuttle"),
    ("MPCC.OL", "MPC Container Ships"), ("FRO.OL", "Frontline"), ("AKER.OL", "Aker"),
    ("SRBNK.OL", "Sparebanken Norge"), ("SB1NO.OL", "SpareBank 1 Sør-Norge"), ("MING.OL", "SpareBank 1 SMN"),
    ("SBNOR.OL", "Sbanken"), ("PROT.OL", "Protector Forsikring"), ("WWI.OL", "Wallenius Wilhelmsen"),
    ("HAFNI.OL", "Hafnia"), ("BWLPG.OL", "BW LPG"), ("BWO.OL", "BW Offshore"), ("VAR.OL", "Vår Energi"),
    ("ODL.OL", "Odfjell Drilling"), ("AKSO.OL", "Aker Solutions"), ("TGS.OL", "TGS"),
    ("PGS.OL", "PGS"), ("NOD.OL", "Nordic Semiconductor"), ("ELK.OL", "Elkem"), ("BORR.OL", "Borr Drilling"),
    ("ENTRA.OL", "Entra"), ("SCHA.OL", "Schibsted A"), ("ATEA.OL", "Atea"), ("KIT.OL", "Kitron"),
    ("VEI.OL", "Veidekke"), ("AFG.OL", "AF Gruppen"), ("MULTI.OL", "Multiconsult"), ("NRC.OL", "NRC Group"),
    ("HEX.OL", "Hexagon Composites"), ("ARCH.OL", "Archer"), ("GOGL.OL", "Golden Ocean"),
    ("DOFG.OL", "DOF Group"), ("SATS.OL", "SATS"), ("AUSS.OL", "Austevoll Seafood"), ("GSF.OL", "Grieg Seafood"),
    ("BNOR.OL", "Bluenord"), ("OTL.OL", "Otello"), ("NEXT.OL", "NEXT Biometrics"), ("SOFF.OL", "Solstad Offshore"),
    ("EPR.OL", "Europris"), ("XXL.OL", "XXL"), ("RECSI.OL", "REC Silicon"), ("NEL.OL", "Nel"),
    ("BELCO.OL", "Belships"), ("KID.OL", "Kid"), ("ADE.OL", "Adevinta"), ("CADLR.OL", "Cadeler"),
]

INDICES = [
    ("^GSPC", "S&P 500"),
    ("^OSEAX", "Oslo Børs All-Share"),
    ("^STOXX", "STOXX Europe 600"),
    ("^IXIC", "Nasdaq Composite"),
]

# Første indeks som gir data brukes som reell referanse per marked.
REAL_BENCH = {"US": ["^GSPC"], "NO": ["^OSEAX", "OSEBX.OL"]}

MIN_MCAP = {"US": 2e9, "NO": 1e9}  # i handelsvaluta (USD / NOK)


def sp500():
    resp = requests.get(SP500_CSV, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    out = []
    for _, r in df.iterrows():
        out.append((str(r["Symbol"]).replace(".", "-"), str(r["Security"])))
    return out


def load():
    """Returnerer liste med dict(ticker, name, market)."""
    uni = [{"ticker": t, "name": n, "market": "NO"} for t, n in OSLO]
    uni += [{"ticker": t, "name": n, "market": "US"} for t, n in sp500()]
    return uni
