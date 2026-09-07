#!/usr/bin/env python3
"""
Palermo FC -> iCalendar
- stagione calcolata automaticamente (es. 2026/27 -> 2027/28)
- Serie B: fonte Lega B, quando il Palermo partecipa alla Serie B
- tutte le competizioni: pagina ufficiale Palermo FC come fonte generale/fallback
- amichevoli 2026 già note: conservate nel feed
- UID stabili: gli spostamenti di data/ora aggiornano lo stesso evento
- nessuna sovrascrittura del feed se le fonti principali falliscono
"""

import hashlib
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

OUT = Path("palermo.ics")
TZ = ZoneInfo("Europe/Rome")

MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

TEAMS_B = {
    "PAL": "Palermo", "JST": "Juve Stabia", "ARE": "Arezzo", "SAM": "Sampdoria",
    "AVE": "Avellino", "PAD": "Padova", "EMP": "Empoli", "MAN": "Mantova",
    "CAR": "Carrarese", "PIS": "Pisa", "VIC": "L.R. Vicenza", "ASC": "Ascoli",
    "CTZ": "Catanzaro", "SUD": "Südtirol", "BEN": "Benevento",
    "VER": "Hellas Verona", "CRE": "Cremonese", "CES": "Cesena",
    "VIR": "Virtus Entella", "MOD": "Modena",
}

# Amichevoli ufficiali 2026 già note/disputate.
KNOWN_FRIENDLIES = [
    ("2026-07-15", "17:30", "Palermo", "FC Gherdëina",
     "Amichevole", "Centro Sportivo Mulin da Coi, Santa Cristina in Valgardena (BZ)"),
    ("2026-07-18", "16:00", "Palermo", "FC Ingolstadt 04",
     "Amichevole", "Centro Sportivo Mulin da Coi, Santa Cristina in Valgardena (BZ)"),
    ("2026-07-22", "17:15", "Palermo", "FC Paradiso",
     "Amichevole", "Centro Sportivo Mulin da Coi, Santa Cristina in Valgardena (BZ)"),
    ("2026-07-25", "16:30", "Palermo", "FC Nürnberg",
     "Amichevole", "Tennisverein Vahrn, Varna (BZ)"),
    ("2026-07-29", "17:00", "Palermo", "FC Iraklis 1908",
     "Amichevole", "Centro Sportivo Mulin da Coi, Santa Cristina in Valgardena (BZ)"),
    ("2026-08-07", "13:00", "Palermo", "Melbourne City",
     "Anglo-Palermitan Trophy", "Sam Kerr Football Centre, Perth"),
    ("2026-08-11", "12:00", "Juventus", "Palermo",
     "Amichevole", "HBF Park, Perth"),
]

# Fallback delle gare di Coppa già confermate nel 2026/27.
KNOWN_COPPA = [
    ("2026-08-17", "21:15", "Palermo", "Lecce",
     "Coppa Italia Frecciarossa", "Stadio Renzo Barbera"),
    ("2026-09-03", "18:00", "Palermo", "Mantova",
     "Coppa Italia Frecciarossa", "Stadio Renzo Barbera"),
]


def season_start_year(now=None):
    """La stagione italiana cambia a luglio: 2026-09 -> 2026/27, 2027-07 -> 2027/28."""
    now = now or datetime.now(TZ)
    return now.year if now.month >= 7 else now.year - 1


def season_label(start):
    return f"{start}/{str(start + 1)[-2:]}"


def season_path(start):
    return f"{start}-{start + 1}"


def compact_season(start):
    return f"{str(start)[-2:]}{str(start + 1)[-2:]}"


def esc(s):
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def normalize_competition(name):
    n = re.sub(r"\s+", " ", name.strip())
    low = n.lower()
    if "serie b" in low:
        return "Serie BKT"
    if "coppa italia" in low:
        return "Coppa Italia Frecciarossa"
    if "amichevol" in low:
        return "Amichevole"
    return n


def stable_uid(season, competition, home, away):
    # Data e ora non fanno parte dell'UID: se cambiano, Apple aggiorna lo stesso evento.
    raw = f"{season}|{normalize_competition(competition)}|{home}|{away}".lower().encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:24] + "@palermo-calendar"


def parse_date(text, season_start):
    m = re.search(
        r"(\d{1,2})\s+"
        r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)"
        r"(?:\s+(\d{4}))?",
        text.lower(),
    )
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS[m.group(2)]
    if m.group(3):
        year = int(m.group(3))
    else:
        year = season_start if month >= 7 else season_start + 1
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def chrome_path():
    return (
        shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )


def rendered_html(url, budget=10000):
    chrome = chrome_path()
    if not chrome:
        raise RuntimeError("Chrome/Chromium non trovato sul runner GitHub")

    cmd = [
        chrome,
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        f"--virtual-time-budget={budget}",
        "--dump-dom",
        url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
    if p.returncode != 0:
        raise RuntimeError("Chrome failed: " + p.stderr[-1200:])
    return p.stdout


def get_serie_b_matches(start):
    """
    Fonte prioritaria quando Palermo è in Serie B.
    L'URL cambia automaticamente: 2026-2027 -> 2027-2028 -> ...
    """
    url = (
        "https://www.legab.it/seriebkt/calendario/"
        f"{season_path(start)}/stagione-regolare/palermo"
    )

    html = rendered_html(url, 10000)
    if "Palermo" not in html or "Giornata" not in html:
        raise RuntimeError("pagina Lega B non valida per questa stagione")

    soup = BeautifulSoup(html, "html.parser")
    lines = [
        re.sub(r"\s+", " ", x).strip()
        for x in soup.get_text("\n", strip=True).splitlines()
        if x.strip()
    ]

    starts = [i for i, x in enumerate(lines) if "Giornata" in x]
    matches = []

    for pos, i in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), i + 60)
        block = lines[i:end]

        d = next((parse_date(x, start) for x in block if parse_date(x, start)), None)
        if not d:
            continue

        codes = []
        for x in block:
            if x in TEAMS_B and x not in codes:
                codes.append(x)

        if len(codes) < 2:
            continue

        home_code, away_code = codes[0], codes[1]
        if "PAL" not in (home_code, away_code):
            continue

        kick = None
        for x in block:
            if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", x):
                # 01:00 / 02:00 sono stati usati come placeholder tecnici.
                if x not in {"00:00", "01:00", "02:00"}:
                    kick = x
                break

        matches.append({
            "season": season_label(start),
            "date": d,
            "time": kick,
            "home": TEAMS_B[home_code],
            "away": TEAMS_B[away_code],
            "competition": "Serie BKT",
            "location": "",
            "source": "Lega Serie B",
        })

    # La Serie B ha 38 gare. Se il formato cambia non fidarsi di un risultato parziale.
    if len(matches) != 38:
        raise RuntimeError(f"Lega B: trovate {len(matches)} partite, attese 38")

    return matches


def official_page_candidates(start):
    """
    URL ufficiali costruiti automaticamente dalla stagione:
    2026/27 -> /it/2627/stagione
    2027/28 -> /it/2728/stagione
    ecc.
    """
    c = compact_season(start)
    return [
        f"https://www.palermofc.com/it/{c}/stagione",
        f"https://www.palermofc.com/it/{c}/squadre/prima-squadra",
        "https://www.palermofc.com/it",
    ]


def clean_team_line(line):
    # Rimuove risultato finale: "Palermo 5" -> "Palermo"
    return re.sub(r"\s+\d+$", "", line.strip())


def team_candidate(line, season_start):
    s = clean_team_line(line)
    low = s.lower()

    if not s or s.startswith("Image"):
        return None
    if s in {"/", "-", "Risultato"}:
        return None
    if parse_date(s, season_start):
        return None
    if re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", s):
        return None

    bad = (
        "match center", "acquista", "partita precedente", "partita in programma",
        "prossima partita", "stadio ", "calendario", "classifica", "scopri",
        "serie bkt", "coppa italia", "news", "next matches", "partite",
    )
    if any(x in low for x in bad):
        return None
    if not (2 <= len(s) <= 45):
        return None
    return s


def get_official_matches(start):
    """
    Legge la pagina ufficiale della stagione Palermo FC.
    Gestisce sia:
      "Partita precedente Coppa Italia"
    sulla stessa riga, sia:
      "Partita precedente"
      "Coppa Italia"
    su due righe.
    """
    html = None
    used_url = None

    for url in official_page_candidates(start):
        try:
            candidate = rendered_html(url, 12000)
            text = BeautifulSoup(candidate, "html.parser").get_text("\n", strip=True)
            if "Palermo" in text and (
                "Partita precedente" in text
                or "Partita in programma" in text
                or "Prossima Partita" in text
                or "Prossima partita" in text
            ):
                html = candidate
                used_url = url
                break
        except Exception as e:
            print(f"Palermo FC: tentativo {url} fallito ({e})")

    if not html:
        raise RuntimeError("nessuna pagina ufficiale Palermo valida trovata")

    soup = BeautifulSoup(html, "html.parser")
    lines = [
        re.sub(r"\s+", " ", x).strip()
        for x in soup.get_text("\n", strip=True).splitlines()
        if x.strip()
    ]

    marker_words = (
        "Partita precedente",
        "Partita in programma",
        "Prossima Partita",
        "Prossima partita",
    )

    markers = []
    for i, line in enumerate(lines):
        marker = next((m for m in marker_words if line.startswith(m)), None)
        if not marker:
            continue

        competition = line[len(marker):].strip(" :-")
        if not competition and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if (
                len(nxt) <= 50
                and not parse_date(nxt, start)
                and not re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", nxt)
            ):
                competition = nxt

        competition = normalize_competition(competition or "Palermo FC")
        markers.append((i, competition))

    matches = []

    for pos, (i, competition) in enumerate(markers):
        end_i = markers[pos + 1][0] if pos + 1 < len(markers) else min(len(lines), i + 30)
        block = lines[i + 1:end_i]

        d = None
        date_index = None
        for j, x in enumerate(block):
            parsed = parse_date(x, start)
            if parsed:
                d = parsed
                date_index = j
                break
        if not d:
            continue

        kick = None
        location = ""

        for x in block[date_index + 1:]:
            tm = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", x)
            if not tm:
                continue
            candidate = f"{int(tm.group(1)):02d}:{tm.group(2)}"
            # Sul sito Palermo 00:00 indica normalmente orario non ancora ufficiale.
            if candidate != "00:00":
                kick = candidate

            # "20:30 - Stadio Renzo Barbera" oppure "Ore 20:30"
            if " - " in x:
                loc = x.split(" - ", 1)[1].strip()
                if loc:
                    location = loc
            break

        # Le squadre sono cercate dopo data/orario, ignorando "/" e risultati.
        search_block = block[date_index + 1:]
        teams = []
        for x in search_block:
            t = team_candidate(x, start)
            if not t:
                continue

            low = t.lower()
            # Evita etichette/accessori della pagina che possono comparire nel blocco.
            if any(k in low for k in (
                "full time", "storico", "formazioni", "acquista il biglietto",
                "ore ", "match preview", "match center"
            )):
                continue

            if t not in teams:
                teams.append(t)

            # Appena abbiamo Palermo + un avversario possiamo fermarci.
            if len(teams) >= 2 and any(x.lower() == "palermo" for x in teams[:2]):
                break

        if len(teams) < 2:
            continue

        home, away = teams[0], teams[1]
        if "palermo" not in {home.lower(), away.lower()}:
            continue

        matches.append({
            "season": season_label(start),
            "date": d,
            "time": kick,
            "home": home,
            "away": away,
            "competition": competition,
            "location": location,
            "source": f"Palermo FC ({used_url})",
        })

    # Deduplica: la homepage/pagina stagione può ripetere alcune gare.
    dedup = {}
    for m in matches:
        dedup[match_key(m)] = m
    matches = list(dedup.values())

    if not matches:
        raise RuntimeError("pagina Palermo letta ma nessuna partita riconosciuta")

    print(f"Palermo FC: pagina usata {used_url}")
    return matches


def static_matches(rows, season):
    result = []
    for date_s, time_s, home, away, competition, location in rows:
        result.append({
            "season": season,
            "date": datetime.strptime(date_s, "%Y-%m-%d"),
            "time": time_s,
            "home": home,
            "away": away,
            "competition": competition,
            "location": location,
            "source": "dato ufficiale già confermato",
        })
    return result


def match_key(m):
    return stable_uid(m["season"], m["competition"], m["home"], m["away"])


def merge_prefer_later(*groups):
    """
    I gruppi successivi hanno precedenza.
    Esempio: Palermo ufficiale -> Lega B, così gli orari Lega B più aggiornati
    sovrascrivono lo stesso incontro senza duplicarlo.
    """
    merged = {}
    for group in groups:
        for m in group:
            merged[match_key(m)] = m
    return list(merged.values())


def build_calendar(matches):
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Palermo Calendar//IT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Palermo FC",
        "X-WR-TIMEZONE:Europe/Rome",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    matches = sorted(matches, key=lambda m: (m["date"], m["time"] or "99:99"))

    for m in matches:
        d = m["date"]
        title = f"⚽ {m['home']} – {m['away']}"
        uid = match_key(m)

        # DTSTAMP stabile: evita un commit GitHub inutile ogni 6 ore.
        stamp = f"{d.strftime('%Y%m%d')}T000000Z"

        desc = f"{m['competition']} {m['season']}\\nFonte: {m['source']}"

        out += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"SUMMARY:{esc(title)}",
            f"DESCRIPTION:{esc(desc)}",
            "TRANSP:TRANSPARENT",
        ]

        if m.get("location"):
            out.append(f"LOCATION:{esc(m['location'])}")

        if m["time"]:
            hh, mm = map(int, m["time"].split(":"))
            start_dt = datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)
            end_dt = start_dt + timedelta(hours=2)

            out += [
                f"DTSTART;TZID=Europe/Rome:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=Europe/Rome:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                "BEGIN:VALARM",
                "TRIGGER:-PT1H",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{esc(title)} tra 1 ora",
                "END:VALARM",
            ]
        else:
            out += [
                f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
                "X-PALERMO-KICKOFF:TBD",
            ]

        out.append("END:VEVENT")

    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def main():
    current_start = season_start_year()
    current_season = season_label(current_start)

    print(f"Stagione rilevata automaticamente: {current_season}")

    official = []
    serie_b = []

    try:
        official = get_official_matches(current_start)
        print(f"Palermo FC: {len(official)} partite lette dalla pagina ufficiale")
    except Exception as e:
        print(f"Palermo FC: fonte ufficiale non disponibile ({e})")

    try:
        serie_b = get_serie_b_matches(current_start)
        print(f"Lega B: {len(serie_b)} partite lette")
    except Exception as e:
        # Non è necessariamente un errore: il Palermo potrebbe essere in un'altra categoria.
        print(f"Lega B: non usata ({e})")

    # Protezione fondamentale: non cancellare il feed se entrambe le fonti vive falliscono.
    if not official and not serie_b:
        raise RuntimeError(
            "Nessuna fonte viva ha prodotto partite: palermo.ics non viene sovrascritto."
        )

    # Storico 2026/27 conservato.
    historical = static_matches(KNOWN_FRIENDLIES, "2026/27")
    historical += static_matches(KNOWN_COPPA, "2026/27")

    # Il parser Palermo è generico (campionato/coppa/amichevoli se presenti);
    # Lega B ha precedenza per le gare di campionato perché è la fonte specifica.
    matches = merge_prefer_later(historical, official, serie_b)

    OUT.write_text(build_calendar(matches), encoding="utf-8")

    competitions = {}
    for m in matches:
        competitions[m["competition"]] = competitions.get(m["competition"], 0) + 1

    detail = " + ".join(f"{n} {c}" for c, n in sorted(competitions.items()))
    print(f"Creato calendario: {detail} = {len(matches)} eventi")


if __name__ == "__main__":
    main()
