#!/usr/bin/env python3
import re
import hashlib
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Europe/Rome")
OUT = Path("palermo.ics")
TEAM_PAGE = "https://www.palermofc.com/it/2627/stagione"

MONTHS = {
    "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
    "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12
}

KNOWN_FRIENDLIES = [
    ("2026-07-15","17:30","Palermo FC","FC Gherdëina","Amichevole","Centro Sportivo Mulin da Coi, Santa Cristina Valgardena"),
    ("2026-07-18","16:00","Palermo FC","FC Ingolstadt 04","Amichevole","Centro Sportivo Mulin da Coi, Santa Cristina Valgardena"),
    ("2026-07-22","17:00","Palermo FC","FC Paradiso","Amichevole","Centro Sportivo Mulin da Coi, Santa Cristina Valgardena"),
    ("2026-07-25","16:30","Palermo FC","FC Nürnberg","Amichevole","Tennisverein Vahrn, Varna (BZ)"),
    ("2026-07-29","17:00","Palermo FC","FC Iraklis 1908","Amichevole","Centro Sportivo Mulin da Coi, Santa Cristina Valgardena"),
    ("2026-08-07","13:00","Melbourne City","Palermo FC","Anglo-Palermitan Trophy","Sam Kerr Football Centre, Perth"),
    ("2026-08-11","12:00","Palermo FC","Juventus","Amichevole","HBF Park, Perth"),
]

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def esc(s):
    return str(s).replace("\\","\\\\").replace("\n","\\n").replace(",","\\,").replace(";","\\;")

def fold(line):
    # RFC 5545 folding, safe enough for UTF-8 consumers such as Apple Calendar.
    out = []
    while len(line.encode("utf-8")) > 73:
        cut = 65
        while len(line[:cut].encode("utf-8")) > 73:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)

def uid_for(day, home, away, comp):
    raw = f"{day}|{home}|{away}|{comp}".lower().encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:24] + "@palermo-calendar"

def parse_date_it(s):
    m = re.search(r"(\d{1,2})\s+([a-zà]+)\s+(\d{4})", s.lower())
    if not m:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))

def get_official_matches():
    r = requests.get(TEAM_PAGE, timeout=30, headers={"User-Agent":"Mozilla/5.0 PalermoCalendar/1.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    # The official page renders match cards in a very regular text order.
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    matches = []
    statuses = ("Partita precedente","Partita in programma","Prossima Partita")

    i = 0
    while i < len(lines):
        line = lines[i]
        if any(line.startswith(s) for s in statuses):
            comp = line
            for s in statuses:
                comp = comp.replace(s, "").strip()
            # date should be shortly after the heading
            block = lines[i:i+14]
            d = next((parse_date_it(x) for x in block if parse_date_it(x)), None)
            if not d:
                i += 1
                continue

            # time/location line
            t = None
            location = ""
            ti = None
            for j, x in enumerate(block):
                m = re.match(r"^(\d{1,2}:\d{2})\s*-\s*(.+)$", x)
                if m:
                    t, location, ti = m.group(1), m.group(2), j
                    break
            if ti is None:
                i += 1
                continue

            # Team names are the next meaningful items after time/location.
            candidates = []
            ignore = {"Match Center","Acquista il biglietto","/","Image: Palermo","Image: Sampdoria"}
            for x in block[ti+1:]:
                if x in ignore or x.startswith("Image:") or re.fullmatch(r"\d+", x):
                    continue
                if parse_date_it(x):
                    break
                if any(x.startswith(s) for s in statuses):
                    break
                # Strip result trailing number from completed games.
                x = re.sub(r"\s+\d+$", "", x).strip()
                if x and x not in candidates:
                    candidates.append(x)
                if len(candidates) == 2:
                    break
            if len(candidates) == 2 and ("Palermo" in candidates[0] or "Palermo" in candidates[1]):
                # 00:00 on the Palermo site means kickoff not yet defined.
                matches.append({
                    "date": d.isoformat(), "time": None if t == "00:00" else t,
                    "home": candidates[0], "away": candidates[1],
                    "competition": comp or "Palermo FC", "location": location,
                    "source": TEAM_PAGE
                })
        i += 1
    return matches

def initial_friendlies():
    return [
        {"date":d,"time":t,"home":h,"away":a,"competition":c,"location":loc,
         "source":"https://www.palermofc.com/it/news/ritiro-2026-il-programma-delle-amichevoli"}
        for d,t,h,a,c,loc in KNOWN_FRIENDLIES
    ]

def dedupe(items):
    out = {}
    for x in items:
        key = (x["date"], x["home"].lower(), x["away"].lower())
        # Prefer an official competition card over seeded friendly data.
        out[key] = x
    return sorted(out.values(), key=lambda x: (x["date"], x.get("time") or "00:00"))

def event_lines(m, stamp):
    d = date.fromisoformat(m["date"])
    title = f"⚽ {m['home']} – {m['away']}"
    uid = uid_for(m["date"], m["home"], m["away"], m["competition"])
    desc = f"{m['competition']}\\nFonte ufficiale: {m['source']}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"SUMMARY:{esc(title)}",
        f"DESCRIPTION:{esc(desc)}",
        f"LOCATION:{esc(m.get('location',''))}",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
    ]
    if m.get("time"):
        hh, mm = map(int, m["time"].split(":"))
        start = datetime(d.year,d.month,d.day,hh,mm,tzinfo=TZ)
        end = start + timedelta(hours=2)
        lines += [
            f"DTSTART;TZID=Europe/Rome:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Europe/Rome:{end.strftime('%Y%m%dT%H%M%S')}",
            "BEGIN:VALARM","TRIGGER:-PT1H","ACTION:DISPLAY",
            f"DESCRIPTION:{esc(title)} tra 1 ora","END:VALARM",
        ]
    else:
        # Unknown kickoff: all-day event until the official time is published.
        lines += [
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(d+timedelta(days=1)).strftime('%Y%m%d')}",
            "X-PALERMO-KICKOFF:TBD",
        ]
    lines.append("END:VEVENT")
    return lines

def main():
    official = get_official_matches()
    if len(official) < 10:
        raise RuntimeError(f"Parsing failed: only {len(official)} official matches found; refusing to overwrite calendar.")
    matches = dedupe(initial_friendlies() + official)
    stamp = datetime.now(tz=ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    cal = [
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
        cal.extend(event_lines(m, stamp))
    cal.append("END:VCALENDAR")
    OUT.write_text("\r\n".join(fold(x) for x in cal) + "\r\n", encoding="utf-8")
    print(f"Wrote {OUT} with {len(matches)} events")

if __name__ == "__main__":
    main()
