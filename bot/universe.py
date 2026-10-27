"""Aksjeunivers. Oslo Børs er en håndlaget liste. Tickere som Yahoo ikke kjenner hoppes over og logges."""
import csv
import io
import pathlib

import pandas as pd
import requests

SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"

# (Yahoo-ticker, navn). Sjekk listen jevnlig. Feil tickere gir bare en advarsel i rapporten.
OSLO_CSV = pathlib.Path(__file__).with_name("universe_oslo.csv")


def _read(path):
    with path.open(encoding="utf-8") as f:
        return [(r["ticker"], r["name"]) for r in csv.DictReader(f)]


OSLO = _read(OSLO_CSV)

INDICES = [
    ("^GSPC", "S&P 500"),
    ("^OSEAX", "Oslo Børs All-Share"),
    ("^STOXX", "STOXX Europe 600"),
    ("^IXIC", "Nasdaq Composite"),
]

# Første indeks som gir data brukes som reell referanse per marked.
REAL_BENCH = {"US": ["^GSPC"], "NO": ["^OSEAX", "OSEBX.OL"], "EU": ["^STOXX"]}

MIN_MCAP = {"US": 2e9, "NO": 5e8, "EU": 1e9}  # i handelsvaluta (USD / NOK / EUR, SEK, DKK)

EU_CSV = pathlib.Path(__file__).with_name("universe_eu.csv")

# minste snittomsetning per dag (kurs x volum, 20 dager) i handelsvaluta. Hindrer illikvide småaksjer.
MIN_TURNOVER = {"NO": 2e6}


def sp500():
    resp = requests.get(SP500_CSV, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    out = []
    for _, r in df.iterrows():
        out.append((str(r["Symbol"]).replace(".", "-"), str(r["Security"])))
    return out


def europe():
    """EØS-selskaper fra nasjonale hovedindekser. Britiske og sveitsiske er utelatt (ikke ASK)."""
    return _read(EU_CSV)


def load():
    """Returnerer liste med dict(ticker, name, market)."""
    uni = [{"ticker": t, "name": n, "market": "NO"} for t, n in OSLO]
    uni += [{"ticker": t, "name": n, "market": "US"} for t, n in sp500()]
    uni += [{"ticker": t, "name": n, "market": "EU"} for t, n in europe()]
    return uni
