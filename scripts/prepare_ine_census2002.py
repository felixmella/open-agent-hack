"""Download INE's Census 2002 population count for every comuna, on today's comuna boundaries and codes.

Usage:  .venv\\Scripts\\python scripts\\prepare_ine_census2002.py [--html PATH]
Writes data/official/ine_census2002_comunas.csv (cut, comuna, population).

INE publishes the 2002 census as a database on its REDATAM server, not as a comuna table. The server counts the
persons in each comuna ("Conteos", Personas by Comuna, the whole database) and shows the result as an HTML table:
this script asks for that count, reads the table, and checks it before writing anything: 346 comunas, and a total
equal to the census's official national count, 15,116,435. The database uses today's comuna codes (CUT), so
comunas created after 2002 (Alto Hospicio, Alto Biobío, Cholchol, Hualpén) have their own 2002 count, and the
comunas they were split from have their 2002 count on today's boundaries.
"""
import argparse
import csv
import html
import re
from pathlib import Path

import httpx

SERVER = "https://redatam-ine.ine.cl/redbin"
FORM = {"MAIN": "WebServerMain.inl", "BASE": "CENSO_2002", "LANG": "esp", "CODIGO": "XXUSUARIOXX", "ITEM": "COUNTS",
        "MODE": "RUN", "inputTitle": "", "VARIABLE": "PERSONA", "OUTPUT": "COMUNA", "SELECTION": "ALL",
        "INLINESELECTION": "", "FORMAT": "HTML", "TOTCOL": "on", "UNIVERSE": "", "FILTER": "", "TEXT_FILTER": "",
        "Submit": "Ejecutar"}
NATIONAL_TOTAL = 15_116_435
COMUNAS = 346
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "official" / "ine_census2002_comunas.csv"
USER_AGENT = "FactSyncChile/0.1 (https://github.com/felixmella/open-agent-hack)"


def fetch_table():
    """Run the count on INE's REDATAM server; the answer page frames the result table, which is fetched next."""
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=300, follow_redirects=True) as client:
        page = client.post(f"{SERVER}/RpWebStats.exe/AreaList?", data=FORM)
        page.raise_for_status()
        frame = re.search(r'<iframe src="([^"]+)"', page.text)
        if not frame:
            raise SystemExit("REDATAM answered without a result table; try again later")
        table = client.get(html.unescape(frame.group(1)))
        table.raise_for_status()
        return table.text


def parse(page):
    """(cut, comuna, persons) for each comuna row of the result table."""
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        if len(cells) > 3 and re.fullmatch(r"\d{5}", cells[1]) and re.fullmatch(r"[\d\s]+", cells[3]):
            rows.append((cells[1], cells[2], int(re.sub(r"\s", "", cells[3]))))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", help="parse a saved REDATAM result table instead of asking the server")
    args = parser.parse_args()
    rows = parse(Path(args.html).read_text(encoding="utf-8") if args.html else fetch_table())
    total = sum(r[2] for r in rows)
    if len(rows) != COMUNAS or total != NATIONAL_TOTAL:
        raise SystemExit(f"unexpected count: {len(rows)} comunas, {total:,} persons "
                         f"(expected {COMUNAS} and {NATIONAL_TOTAL:,}); nothing written")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["cut", "comuna", "population"])
        writer.writerows(sorted(rows))
    print(f"wrote {OUTPUT} ({len(rows)} comunas, {total:,} persons: the official 2002 national count)")


if __name__ == "__main__":
    main()
