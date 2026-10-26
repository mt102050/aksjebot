"""Telegram-varsler. Token og chat-id kommer fra miljøvariabler (GitHub secrets). Aldri skriv dem i koden."""
import os

import requests

LABEL = {"US": "USA", "NO": "Oslo"}


def send(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[Telegram ikke satt opp] " + text)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        return r.ok
    except requests.RequestException as e:
        print("Telegram feilet:", type(e).__name__)  # ikke skriv ut URL, den inneholder token
        return False


def _line(e):
    return f"{e['ticker']} ({LABEL.get(e['market'], e['market'])}) kurs {e['entry_price'] if 'entry_price' in e else ''}"


def build_message(as_of, events, warnings, weekly=None):
    """Returnerer tekst, eller None når det ikke er noe å melde."""
    parts = []
    init = [e for e in events if e["type"] == "LONG_INIT"]
    if init:
        names = ", ".join(e["ticker"] for e in init)
        parts.append(f"Startliste langsiktig ({len(init)}): {names}")
    for e in events:
        if e["type"] == "LONG_ENTER":
            parts.append(f"Ny på kjøpslisten: {e['ticker']} ({e['name']}), toppscore {e['pct']:.0f}. Kurs {e['entry_price']:.2f}")
        elif e["type"] == "LONG_EXIT":
            parts.append(f"Ut av listen: {e['ticker']} ({e['name']}). {e['reason']}. Avkastning siden inn {e['ret']*100:+.1f} prosent")
        elif e["type"] == "TACT_ENTER":
            parts.append(f"Taktisk papirsignal: {e['ticker']} ({e['kind']}). Kurs {e['entry_price']:.2f}")
        elif e["type"] == "TACT_EXIT":
            parts.append(f"Taktisk ut: {e['ticker']} ({e['reason']}). {e['ret']*100:+.1f} prosent")
    for w in warnings:
        parts.append("Advarsel: " + w)
    if weekly:
        parts.append(weekly)
    if not parts:
        return None
    return f"Aksjebot {as_of}\n" + "\n".join(parts)
