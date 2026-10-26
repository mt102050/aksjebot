# Aksjebot

Daglig analyse av Oslo Børs og S&P 500. Rangerer aksjer på verdi, kvalitet og momentum. Logger alle anbefalinger som papirhandel og måler dem mot indeks. Appen ligger på GitHub Pages. Varsler går til Telegram.

Dette er et analyseverktøy, ikke investeringsråd. Papirhandel inkluderer ikke kurtasje, spread, utbytte eller skatt.

## Oppsett (engangsjobb)

1. Repo: Settings, Pages, Source "Deploy from a branch", Branch main, mappe /docs.
2. Telegram: send en melding til boten din. Åpne `https://api.telegram.org/bot<TOKEN>/getUpdates` i nettleseren og finn `chat` og `id`. Ikke del token.
3. Repo: Settings, Secrets and variables, Actions, New repository secret. Lag `TELEGRAM_TOKEN` og `TELEGRAM_CHAT_ID`.
4. Actions, workflow "daily", Run workflow. Første kjøring tar noen minutter.
5. Åpne appen på `https://<brukernavn>.github.io/aksjebot/` og legg den til på hjemskjermen.

## Regler

- Rangering: 40 % verdi, 35 % kvalitet, 25 % momentum. Syklisk bransje får halv vekt på verdi. Banker rangeres for seg.
- Langsiktig kjøpsliste: inn ved øverste 10 prosent, over 200-dagers snitt og kvalitet over median. Ut under øverste 30 prosent. Vurderes første kjøring hver måned.
- Taktisk: tilbakegang i opptrend eller ny 52-ukers topp. Ut ved +15 %, -8 % eller 40 dager. Bare papir.
- Ingen anbefalinger gis hvis datadekningen er for lav. Du får da en feilmelding på Telegram.

## Kjente svakheter

- Yahoo-data er gratis og kan være feil eller mangle. Oslo Børs er dårligst dekket.
- Oslo-listen i `bot/universe.py` er skrevet for hånd. Tickere som ikke finnes gir advarsel. Sjekk listen.
- Ingen Piotroski F-score ennå. Kvalitet bruker ROE, marginer og gjeld.
- Papirboken har overlevelsesskjevhet bare hvis listen over aksjer endres. Hold listen stabil.
- GitHub kan stoppe planlagte kjøringer i offentlige repoer uten aktivitet i 60 dager. Daglige commits holder det i gang, men sjekk Actions hvis varslene uteblir.
- Under 30 lukkede papirhandler sier resultatene nesten ingenting.
