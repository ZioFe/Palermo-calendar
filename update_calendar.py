#!/usr/bin/env python3

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URL = "https://www.legab.it/seriebkt/calendario/2026-2027/stagione-regolare/palermo"
OUT = Path("palermo.ics")
TZ = ZoneInfo("Europe/Rome")

MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12
}

TEAMS = {
    "PAL": "Palermo",
    "JST": "Juve Stabia",
    "ARE": "Arezzo",
    "SAM": "Sampdoria",
    "AVE": "Avellino",
    "PAD": "Padova",
    "EMP": "Empoli",
    "MAN": "Mantova",
    "CAR": "Carrarese",
    "PIS": "Pisa",
    "VIC": "L.R. Vicenza",
    "ASC": "Ascoli",
    "CAT": "Catanzaro",
    "SUD": "Südtirol",
    "BEN": "Benevento",
    "VER": "Hellas Verona",
    "CRE": "Cremonese",
    "CES": "Cesena",
    "ENT": "Virtus Entella",
    "MOD": "Modena",
}

def esc(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )

def uid_for(day, home, away):
    raw = f"{day}|{home}|{away}|serie-b".encode()
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

def get_matches():
    r = requests.get(
        URL,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    lines = [x.strip() for x in text.splitlines() if x.strip()]

    matches = []

    for i, line in enumerate(lines):
        if not re.search(r"\d+[ªa]\s*Giornata", line, re.I):
            continue

        block = lines[i:i+18]

        date_obj = None
        for x in block:
            date_obj = parse_date(x)
            if date_obj:
                break

        if not date_obj:
            continue

        codes = [x for x in block if x in TEAMS]

        if len(codes) < 2:
            continue

        home_code = codes[0]
        away_code = codes[1]

        if "PAL" not in (home_code, away_code):
            continue

        time_value = None

        for x in block:
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", x)
            if m:
                time_value = x
                break

        matches.append({
            "date": date_obj,
            "time": time_value,
            "home": TEAMS[home_code],
            "away": TEAMS[away_code],
        })

    if len(matches) < 30:
        raise RuntimeError(
            f"Parsing failed: only {len(matches)} Serie B matches found"
        )

    return matches

def build_calendar(matches):
    now = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    lines = [
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

    for m in matches:
        d = m["date"]
        title = f"⚽ {m['home']} – {m['away']}"

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid_for(d.date(), m['home'], m['away'])}",
            f"DTSTAMP:{now}",
            f"SUMMARY:{esc(title)}",
            "DESCRIPTION:Serie BKT 2026/27\\nFonte: Lega Serie B",
            "TRANSP:TRANSPARENT",
        ])

        if m["time"]:
            hh, mm = map(int, m["time"].split(":"))

            start = datetime(
                d.year, d.month, d.day,
                hh, mm,
                tzinfo=TZ
            )

            end = start + timedelta(hours=2)

            lines.extend([
                f"DTSTART;TZID=Europe/Rome:{start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=Europe/Rome:{end.strftime('%Y%m%dT%H%M%S')}",
                "BEGIN:VALARM",
                "TRIGGER:-PT1H",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{esc(title)} tra 1 ora",
                "END:VALARM",
            ])

        else:
            lines.extend([
                f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            ])

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    return "\r\n".join(lines) + "\r\n"

def main():
    matches = get_matches()
    OUT.write_text(build_calendar(matches), encoding="utf-8")
    print(f"Creato calendario con {len(matches)} partite")

if __name__ == "__main__":
    main()
