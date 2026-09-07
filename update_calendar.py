#!/usr/bin/env python3
import hashlib, re, shutil, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

URL = "https://www.legab.it/seriebkt/calendario/2026-2027/stagione-regolare/palermo"
OUT = Path("palermo.ics")
TZ = ZoneInfo("Europe/Rome")

MONTHS = {"gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
          "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12}

TEAMS = {
    "PAL":"Palermo","JST":"Juve Stabia","ARE":"Arezzo","SAM":"Sampdoria","AVE":"Avellino",
    "PAD":"Padova","EMP":"Empoli","MAN":"Mantova","CAR":"Carrarese","PIS":"Pisa",
    "VIC":"L.R. Vicenza","ASC":"Ascoli","CTZ":"Catanzaro","SUD":"Südtirol","BEN":"Benevento",
    "VER":"Hellas Verona","CRE":"Cremonese","CES":"Cesena","VIR":"Virtus Entella","MOD":"Modena"
}

def esc(s):
    return str(s).replace("\\","\\\\").replace("\n","\\n").replace(",","\\,").replace(";","\\;")

def uid_for(home, away):
    raw = f"serie-b-2026-27|{home}|{away}".lower().encode()
    return hashlib.sha1(raw).hexdigest()[:24] + "@palermo-calendar"

def parse_date(text):
    m = re.search(r"(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)", text.lower())
    if not m: return None
    day, month = int(m.group(1)), MONTHS[m.group(2)]
    year = 2026 if month >= 7 else 2027
    return datetime(year, month, day)

def rendered_html():
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        raise RuntimeError("Chrome/Chromium non trovato sul runner GitHub")
    cmd = [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
           "--virtual-time-budget=10000", "--dump-dom", URL]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if p.returncode != 0:
        raise RuntimeError("Chrome failed: " + p.stderr[-1200:])
    if "Palermo" not in p.stdout or "Giornata" not in p.stdout:
        raise RuntimeError("La pagina renderizzata non contiene il calendario atteso")
    return p.stdout

def get_matches():
    soup = BeautifulSoup(rendered_html(), "html.parser")
    lines = [re.sub(r"\s+", " ", x).strip() for x in soup.get_text("\n", strip=True).splitlines() if x.strip()]
    starts = [i for i, x in enumerate(lines) if "Giornata" in x]
    matches = []

    for pos, start in enumerate(starts):
        end = starts[pos+1] if pos+1 < len(starts) else min(len(lines), start+60)
        block = lines[start:end]

        d = next((parse_date(x) for x in block if parse_date(x)), None)
        if not d: continue

        codes = []
        for x in block:
            if x in TEAMS and x not in codes:
                codes.append(x)
        if len(codes) < 2: continue

        home_code, away_code = codes[0], codes[1]
        if "PAL" not in (home_code, away_code): continue

        kick = None
        for x in block:
            if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", x) and x not in {"01:00","02:00"}:
                kick = x
                break

        matches.append({"date":d, "time":kick, "home":TEAMS[home_code], "away":TEAMS[away_code]})

    if len(matches) != 38:
        raise RuntimeError(f"Parsing failed: trovate {len(matches)} partite Serie B, attese 38")
    return matches

def build_calendar(matches):
    now = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Palermo Calendar//IT","CALSCALE:GREGORIAN",
           "METHOD:PUBLISH","X-WR-CALNAME:Palermo FC","X-WR-TIMEZONE:Europe/Rome",
           "REFRESH-INTERVAL;VALUE=DURATION:PT6H","X-PUBLISHED-TTL:PT6H"]
    for m in matches:
        d, title = m["date"], f"⚽ {m['home']} – {m['away']}"
        out += ["BEGIN:VEVENT",f"UID:{uid_for(m['home'],m['away'])}",f"DTSTAMP:{now}",
                f"SUMMARY:{esc(title)}","DESCRIPTION:Serie BKT 2026/27\\nFonte: Lega Serie B","TRANSP:TRANSPARENT"]
        if m["time"]:
            hh, mm = map(int, m["time"].split(":"))
            start = datetime(d.year,d.month,d.day,hh,mm,tzinfo=TZ)
            end = start + timedelta(hours=2)
            out += [f"DTSTART;TZID=Europe/Rome:{start.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND;TZID=Europe/Rome:{end.strftime('%Y%m%dT%H%M%S')}",
                    "BEGIN:VALARM","TRIGGER:-PT1H","ACTION:DISPLAY",
                    f"DESCRIPTION:{esc(title)} tra 1 ora","END:VALARM"]
        else:
            out += [f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                    f"DTEND;VALUE=DATE:{(d+timedelta(days=1)).strftime('%Y%m%d')}",
                    "X-PALERMO-KICKOFF:TBD"]
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"

def main():
    matches = get_matches()
    OUT.write_text(build_calendar(matches), encoding="utf-8")
    print(f"Creato calendario con {len(matches)} partite di Serie B")

if __name__ == "__main__":
    main()
