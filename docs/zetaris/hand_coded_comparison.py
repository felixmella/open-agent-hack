"""The hand-coded approach, for comparison with the USL (docs/zetaris/README.md, reflection 2a).

It answers one question the USL answers in a single query (zetaris/07_usl_select.sql, query 3): how many Spanish
Wikipedia infobox figures are INE's Census 2024 count, and how many are something else. Here every step the USL does
is written by hand: three HTTP APIs with their own formats, batching, JSON flattening, the wikitext field extraction,
number parsing and the join on the comuna code. It is not used by FactSync.

Run:  .venv\\Scripts\\python docs\\zetaris\\hand_coded_comparison.py
"""
import os
import re
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
HEADERS = {"User-Agent": os.environ.get("ZETARIS_USER_AGENT", "FactSyncChile-comparison/0.1")}
ARCGIS = ("https://services5.arcgis.com/hUyD8u3TeZLKPe4T/arcgis/rest/services/CENSO2024_V2_gdb/FeatureServer/0/query"
          "?where=1%3D1&returnGeometry=false&f=json&outFields=CUT%2CInd_005_TPob")
SPARQL = """SELECT ?cut ?es_title WHERE { ?comuna wdt:P31 wd:Q1840161.
  FILTER NOT EXISTS { ?comuna wdt:P576 ?dissolved } ?comuna wdt:P6929 ?cut.
  ?es schema:about ?comuna; schema:isPartOf <https://es.wikipedia.org/>; schema:name ?es_title. }"""
FIELD = re.compile(r"^[ ]*\|[ ]*población[ ]*=[ ]*(.*)$", re.M)
NUMBER = re.compile(r"^[0-9]{1,3}([.,][0-9]{3})+$|^[0-9]+$")


def census_2024(client):
    """INE's ArcGIS layer: {cut: population}; the layer returns every comuna in one page (346 < its 2,000 limit)."""
    features = client.get(ARCGIS).raise_for_status().json()["features"]
    return {str(f["attributes"]["CUT"]).zfill(5): int(f["attributes"]["Ind_005_TPob"]) for f in features}


def eswiki_titles(client):
    """Wikidata SPARQL: {Spanish article title: cut}."""
    rows = client.get("https://query.wikidata.org/sparql", params={"query": SPARQL, "format": "json"}
                      ).raise_for_status().json()["results"]["bindings"]
    return {r["es_title"]["value"]: r["cut"]["value"] for r in rows}


def infobox_figures(client, titles):
    """MediaWiki API, 50 titles per request: {title: the infobox's población value, parsed, or None}."""
    figures, names = {}, sorted(titles)
    for start in range(0, len(names), 50):
        batch = names[start:start + 50]
        pages = client.get("https://es.wikipedia.org/w/api.php", params={
            "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "format": "json",
            "formatversion": "2", "titles": "|".join(batch)}).raise_for_status().json()["query"]["pages"]
        for page in pages:
            if "revisions" not in page:
                continue
            match = FIELD.search(page["revisions"][0]["slots"]["main"]["content"])
            raw = re.sub(r"[ ]", "", re.sub(r"&nbsp;", "", re.sub(r"<ref.*$", "", match.group(1)))) if match else ""
            figures[page["title"]] = int(re.sub(r"[.,]", "", raw)) if NUMBER.match(raw) else None
        time.sleep(1)  # be polite to the API
    return figures


def main():
    started = time.monotonic()
    with httpx.Client(headers=HEADERS, timeout=60) as client:
        census, titles = census_2024(client), eswiki_titles(client)
        figures = infobox_figures(client, titles)
    matched = [(titles[t], v) for t, v in figures.items() if titles.get(t) in census]
    same = sum(1 for cut, value in matched if value == census[cut])
    print(f"Wikipedia ES: {len(matched)} infobox figures, {same} are the Census 2024 count, "
          f"{len(matched) - same} something else ({time.monotonic() - started:.0f} s)")


if __name__ == "__main__":
    main()
