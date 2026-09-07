#!/usr/bin/env python3
import hashlib
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

SERIE_B_URL = "https://www.legab.it/seriebkt/calendario/2026-2027/stagione-regolare/palermo"
PALERMO_PAGE = "https://www.palermofc.com/it/2526/squadre/prima-squadra"

OUT = Path("palermo.ics")
TZ = ZoneInfo("Europe/Rome")

MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12
}

TEAMS = {
    "PAL": "Palermo", "JST": "Juve Stabia", "ARE": "Arezzo", "SAM": "Sampdoria",
    "AVE": "Avellino", "PAD": "Padova", "EMP": "Empoli", "MAN": "Mantova",
    "CAR": "Carrarese", "PIS": "Pisa", "VIC": "L.R. Vicenza", "ASC": "Ascoli",
    "CTZ": "Catanzaro", "SUD": "Südtirol", "BEN": "Benevento",
    "VER": "Hellas Verona", "CRE": "Cremonese", "CES": "Cesena",
    "VIR": "Virtus Entella", "MOD": "Modena"
}

# Amichevoli ufficiali 2026 già annunciate/disputate.
# Gli orari di Paradiso e Nürnberg sono quelli effettivamente comunicati
# dal Palermo il giorno della gara (17:15 e 16:30).
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

# Fallback sicuro: se il sito Palermo cambia struttura, queste gare di Coppa
# restano comunque nel feed invece di sparire.
KNOWN_COPPA = [
    ("2026-08-17", "21:15", "Palermo", "Lecce", "Coppa Italia Frecciarossa", "Stadio Renzo Barbera"),
    ("2026-09-03", "18:00", "Palermo", "Mantova", "Coppa Italia Frecciarossa", "Stadio Renzo Barbera"),
]

def esc(s):
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )

def stable_uid(competition, home, away):
    # Niente data/ora nell'UID: se una partita viene spostata, Apple aggiorna
    # l'evento invece di crearne uno nuovo.
    raw = f"2026-27|{competition}|{home}|{away}".lower().encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:24] + "@palermo-calendar"

def parse_date(text):
    m = re.search(
        r"(\d{1,2})\s+"
        r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)",
        text.lower()
    )
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS[m.group(2)]
    year = 2026 if month >= 7 else 2027
    return datetime(year, month, day)

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
        chrome, "--headless", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage",
        f"--virtual-time-budget={budget}",
        "--dump-dom", url
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
    if p.returncode != 0:
        raise RuntimeError("Chrome failed: " + p.stderr[-1200:])
    return p.stdout

def get_serie_b_matches():
    html = rendered_html(SERIE_B_URL, 10000)
    if "Palermo" not in html or "Giornata" not in html:
        raise RuntimeError("La pagina Lega B renderizzata non contiene il calendario atteso")

    soup = BeautifulSoup(html, "html.parser")
    lines = [
        re.sub(r"\s+", " ", x).strip()
        for x in soup.get_text("\n", strip=True).splitlines()
        if x.strip()
    ]

    starts = [i for i, x in enumerate(lines) if "Giornata" in x]
    matches = []

    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), start + 60)
        block = lines[start:end]

        d = next((parse_date(x) for x in block if parse_date(x)), None)
        if not d:
            continue

        codes = []
        for x in block:
            if x in TEAMS and x not in codes:
                codes.append(x)

        if len(codes) < 2:
            continue

        home_code, away_code = codes[0], codes[1]
        if "PAL" not in (home_code, away_code):
            continue

        kick = None
        for x in block:
            if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", x) and x not in {"01:00", "02:00"}:
                kick = x
                break

        matches.append({
            "date": d,
            "time": kick,
            "home": TEAMS[home_code],
            "away": TEAMS[away_code],
            "competition": "Serie BKT",
            "location": "",
        })

    if len(matches) != 38:
        raise RuntimeError(
            f"Parsing Serie B fallito: trovate {len(matches)} partite, attese 38. "
            "palermo.ics non viene sovrascritto."
        )

    return matches

def clean_team_line(line):
    # "Palermo 5" -> "Palermo"; "Mantova 2" -> "Mantova"
    s = re.sub(r"\s+\d+$", "", line).strip()
    return s

def looks_like_team(s):
    bad = (
        "partita precedente", "partita in programma", "prossima partita",
        "coppa italia", "serie b", "match center", "acquista",
        "stadio ", "calendario", "news", "scopri", "image", "ore "
    )
    low = s.lower()
    if not s or any(x in low for x in bad):
        return False
    if re.search(r"\d{1,2}:\d{2}", s):
        return False
    if parse_date(s):
        return False
    if s in {"/", "-", "Risultato"}:
        return False
    return 2 <= len(s) <= 40

def get_coppa_matches():
    """
    Prova a leggere automaticamente le gare di Coppa Italia dalla pagina
    ufficiale del Palermo. Se la struttura cambia, il chiamante usa il fallback.
    """
    html = rendered_html(PALERMO_PAGE, 10000)
    soup = BeautifulSoup(html, "html.parser")
    lines = [
        re.sub(r"\s+", " ", x).strip()
        for x in soup.get_text("\n", strip=True).splitlines()
        if x.strip()
    ]

    found = []

    for i, line in enumerate(lines):
        if "Coppa Italia" not in line:
            continue

        block = lines[i:i + 18]
        d = next((parse_date(x) for x in block if parse_date(x)), None)
        if not d:
            continue

        kick = None
        location = ""
        for x in block:
            tm = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", x)
            if tm:
                candidate = f"{int(tm.group(1)):02d}:{tm.group(2)}"
                if candidate != "00:00":
                    kick = candidate
            if x.lower().startswith("stadio "):
                location = x

        # Cerca le due squadre nell'ordine visualizzato dalla pagina.
        candidates = []
        for x in block:
            y = clean_team_line(x)
            if looks_like_team(y) and y not in candidates:
                candidates.append(y)

        if "Palermo" not in candidates:
            continue

        pidx = candidates.index("Palermo")
        other = None
        if pidx > 0:
            other = candidates[pidx - 1]
            home, away = other, "Palermo"
        elif pidx + 1 < len(candidates):
            other = candidates[pidx + 1]
            home, away = "Palermo", other
        else:
            continue

        # Evita falsi positivi evidenti.
        if other.lower() in {"palermo fc", "prima squadra"}:
            continue

        item = {
            "date": d, "time": kick, "home": home, "away": away,
            "competition": "Coppa Italia Frecciarossa", "location": location
        }

        key = (home.lower(), away.lower())
        if not any((m["home"].lower(), m["away"].lower()) == key for m in found):
            found.append(item)

    return found

def static_matches(rows):
    out = []
    for date_s, time_s, home, away, competition, location in rows:
        out.append({
            "date": datetime.strptime(date_s, "%Y-%m-%d"),
            "time": time_s,
            "home": home,
            "away": away,
            "competition": competition,
            "location": location,
        })
    return out

def merge_unique(*groups):
    merged = {}
    for group in groups:
        for m in group:
            key = stable_uid(m["competition"], m["home"], m["away"])
            merged[key] = m
    return list(merged.values())

def build_calendar(matches):
    now = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
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
        uid = stable_uid(m["competition"], m["home"], m["away"])

        desc = f"{m['competition']} 2026/27"
        if m["competition"] == "Serie BKT":
            desc += "\\nFonte: Lega Serie B"
        else:
            desc += "\\nFonte: Palermo FC / fonte ufficiale"

        out += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"SUMMARY:{esc(title)}",
            f"DESCRIPTION:{esc(desc)}",
            "TRANSP:TRANSPARENT",
        ]

        if m.get("location"):
            out.append(f"LOCATION:{esc(m['location'])}")

        if m["time"]:
            hh, mm = map(int, m["time"].split(":"))
            start = datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)
            end = start + timedelta(hours=2)

            out += [
                f"DTSTART;TZID=Europe/Rome:{start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=Europe/Rome:{end.strftime('%Y%m%dT%H%M%S')}",
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
    # Serie B è la fonte critica: se fallisce non sovrascriviamo il calendario.
    serie_b = get_serie_b_matches()

    friendlies = static_matches(KNOWN_FRIENDLIES)
    coppa_fallback = static_matches(KNOWN_COPPA)

    # Coppa Italia è indipendente: se il sito Palermo cambia struttura,
    # manteniamo almeno le gare già note e la Serie B continua ad aggiornarsi.
    try:
        coppa_live = get_coppa_matches()
        if coppa_live:
            coppa = merge_unique(coppa_fallback, coppa_live)
            print(f"Coppa Italia: {len(coppa_live)} gare lette automaticamente dal sito Palermo")
        else:
            coppa = coppa_fallback
            print("Coppa Italia: parser live senza risultati; uso fallback noto")
    except Exception as e:
        coppa = coppa_fallback
        print(f"Coppa Italia: fallback attivato ({e})")

    matches = merge_unique(serie_b, friendlies, coppa)
    OUT.write_text(build_calendar(matches), encoding="utf-8")

    print(
        f"Creato calendario: {len(serie_b)} Serie B + "
        f"{len(coppa)} Coppa Italia + {len(friendlies)} amichevoli = "
        f"{len(matches)} eventi"
    )

if __name__ == "__main__":
    main()
