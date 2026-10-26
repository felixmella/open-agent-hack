"""Turn SERVEL's mayoral election workbooks (2012, 2016, 2021, 2024) into one CSV keyed by comuna code (CUT).

Usage:  .venv\\Scripts\\python -I scripts\\prepare_servel_mayors.py FOLDER
Writes data/official/servel_alcaldes_2012_2024.csv: one row per candidate per election (year, election_date, cut,
comuna, comuna_servel, region, lista, pacto, partido, nombres, primer_apellido, segundo_apellido, votos, elected).

FOLDER holds SERVEL's four workbooks (YYYY_MM_Alcaldes_*.xlsx); only their sheet "Votación por comuna" is read. Its
header is on row 7, and columns are taken by name: 2024's sheet has no Nro.voto column. Rows for blank and null votes
(no surname) are dropped. `elected` is SERVEL's Cargo = ALCALDE.

SERVEL names comunas in upper case without accents, and not always like INE (LLAILLAY in 2021, LLAY-LLAY in the other
years): each name is resolved to its CUT against INE's 346 comunas (data/official/ine_census2002_comunas.csv, today's
codes) by comparing letters only, with ALIASES for the names that differ. Nothing is written unless every comuna of
every election resolves, and each election has 346 comunas with exactly one winner each.
"""
import argparse
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
INE = ROOT / "data" / "official" / "ine_census2002_comunas.csv"
OUTPUT = ROOT / "data" / "official" / "servel_alcaldes_2012_2024.csv"
SHEET = "Votación por comuna"
HEADER_ROW = 7
ELECTION_DATES = {2012: "2012-10-28", 2016: "2016-10-23", 2021: "2021-05-16", 2024: "2024-10-27"}  # the (last) day
COMUNAS = 346
# SERVEL's name (letters only) -> INE's name (letters only), where they differ
ALIASES = {"LLAYLLAY": "LLAILLAY", "MARCHIGUE": "MARCHIHUE", "PAIHUANO": "PAIGUANO", "TREHUACO": "TREGUACO",
           "CABODEHORNOSEXNAVARINO": "CABODEHORNOS"}
COLUMNS = ("year", "election_date", "cut", "comuna", "comuna_servel", "region", "lista", "pacto", "partido", "nombres",
           "primer_apellido", "segundo_apellido", "votos", "elected")


def letters(name):
    """A comuna name reduced to its letters, upper case, without accents: 'Llay-Llay' and 'LLAILLAY' differ, 'Ñuñoa'
    and 'NUNOA' don't."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z]", "", text)


def ine_comunas():
    with INE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {letters(r["comuna"]): (r["cut"].zfill(5), r["comuna"]) for r in rows}


def text(value):
    return " ".join(str(value).split()) if value is not None else ""


def read_workbook(path):
    """The candidate rows of one workbook's 'Votación por comuna' sheet, as dicts keyed by header name."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook[SHEET].iter_rows(values_only=True)
        for _ in range(HEADER_ROW - 1):
            next(rows)
        header = [text(c) for c in next(rows)]
        return [dict(zip(header, r)) for r in rows if any(c is not None for c in r)]
    finally:
        workbook.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    ine = ine_comunas()
    written, problems = [], []
    for year, date in ELECTION_DATES.items():
        found = sorted(args.folder.glob(f"{year}_*Alcaldes*.xlsx"))
        if len(found) != 1:
            raise SystemExit(f"expected one {year} workbook in {args.folder}, found {[p.name for p in found]}")
        rows = [r for r in read_workbook(found[0]) if text(r.get("Primer apellido"))]  # drops blank and null votes
        unresolved = sorted({text(r["Comuna"]) for r in rows
                             if ALIASES.get(letters(r["Comuna"]), letters(r["Comuna"])) not in ine})
        if unresolved:
            problems.append(f"{year}: comunas not in INE's list: {unresolved}")
            continue
        winners = Counter(text(r["Comuna"]) for r in rows if text(r.get("Cargo")) == "ALCALDE")
        comunas = {text(r["Comuna"]) for r in rows}
        if len(comunas) != COMUNAS or any(winners[c] != 1 for c in comunas):
            problems.append(f"{year}: {len(comunas)} comunas, winners per comuna {sorted(set(winners.values()))}")
            continue
        for r in rows:
            cut, comuna = ine[ALIASES.get(letters(r["Comuna"]), letters(r["Comuna"]))]
            written.append({"year": year, "election_date": date, "cut": cut, "comuna": comuna,
                            "comuna_servel": text(r["Comuna"]), "region": text(r["Región"]), "lista": text(r["Lista"]),
                            "pacto": text(r["Pacto"]), "partido": text(r["Partido"]), "nombres": text(r["Nombres"]),
                            "primer_apellido": text(r["Primer apellido"]),
                            "segundo_apellido": text(r["Segundo apellido"]), "votos": int(r["Votos"]),
                            "elected": str(text(r.get("Cargo")) == "ALCALDE").lower()})
        cuts = {w["cut"] for w in written if w["year"] == year}
        if len(cuts) != COMUNAS:
            problems.append(f"{year}: {len(comunas)} SERVEL comunas resolve to {len(cuts)} codes")
        print(f"{year}: {len(rows)} candidates in {len(comunas)} comunas, {sum(winners.values())} elected")
    if problems:
        raise SystemExit("nothing written:\n  " + "\n  ".join(problems))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(written, key=lambda w: (w["year"], w["cut"], -w["votos"])))
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(written)} rows)")


if __name__ == "__main__":
    main()
