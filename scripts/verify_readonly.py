"""Check the app's read-only Zetaris user (zetaris/05_readonly_grants.sql): for each view the agents read, the app's
key (ZETARIS_API_KEY) must see as many rows as the admin key (ZETARIS_ADMIN_API_KEY); outside the views (a source
table under them) it must be refused; and the app's user (ZETARIS_APP_USER) must hold nothing beyond SELECT.

Usage:  .venv\\Scripts\\python scripts\\verify_readonly.py

Prints counts and privileges only: never a key, and the user's name is masked. Exits 1 if anything is off.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.zetaris import ZetarisClient, ZetarisError  # noqa: E402
from app.config import load_settings  # noqa: E402

VIEWS = ["factsync.ine_census2024", "factsync.official_population", "factsync.wikidata_population",
         "factsync.eswiki_infobox", "factsync.enwiki_infobox"]
OUTSIDE = "factsync_rest.ine_census2024_raw"  # a source table under the views: the app key must not read it


def masked(text, user):
    """Zetaris echoes user names (in capitals) in messages and grant lists: never print them."""
    return re.sub(re.escape(user), "<app user>", str(text), flags=re.I) if user else str(text)


def count(client, view):
    try:
        return int(client.query(f"SELECT count(*) AS n FROM {view}", limit=1).rows[0]["n"])
    except ZetarisError as exc:
        return f"refused ({exc.code}: {str(exc)[:160]})"


def main():
    settings = load_settings(sample_mode=False)
    admin_key = os.environ.get("ZETARIS_ADMIN_API_KEY", "")
    user = os.environ.get("ZETARIS_APP_USER", "").strip()
    if not admin_key:
        sys.exit("ZETARIS_ADMIN_API_KEY is not set: put the admin key there and the app user's key in ZETARIS_API_KEY")
    if admin_key == settings.zetaris_api_key:
        sys.exit("ZETARIS_API_KEY is still the admin key: put the read-only user's key there")
    app = ZetarisClient(settings.zetaris_rest_url, settings.zetaris_org_id, settings.zetaris_api_key, retries=0)
    admin = ZetarisClient(settings.zetaris_rest_url, settings.zetaris_org_id, admin_key, retries=0)
    problems = 0
    for view in VIEWS:
        seen, expected = count(app, view), count(admin, view)
        ok = isinstance(seen, int) and seen == expected
        problems += not ok
        print(masked(f"{'OK  ' if ok else 'FAIL'} {view}: app key {seen}, admin key {expected}", user))
    outside = count(app, OUTSIDE)
    refused = isinstance(outside, str)
    problems += not refused
    print(masked(f"{'OK  ' if refused else 'FAIL'} {OUTSIDE} (outside the views): app key {outside}", user))
    if user:
        try:
            grants = admin.query(f"SHOW GRANT USER '{user.replace(chr(39), '')}' ON ALL")
            print(f"Grants held by the app user ({len(grants.rows)}):")
            for row in grants.rows:
                print("   ", masked(row, user))
            beyond = [r for r in grants.rows if str(r.get("privilege", "")).upper() != "SELECT"
                      or str(r.get("grant_option", "")).lower() == "true"]
            if beyond:
                problems += 1
                print("FAIL the app user holds more than SELECT")
        except ZetarisError as exc:
            print(masked(f"(couldn't list the app user's grants: {exc.code})", user))
    else:
        print("(ZETARIS_APP_USER is not set: grants not listed)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
