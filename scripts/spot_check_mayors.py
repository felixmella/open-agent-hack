"""Draw a random sample of a national mayor batch's verdicts for a person to check by hand against the pages and
SERVEL's results, and print each with its evidence.

Usage:  .venv\\Scripts\\python scripts\\spot_check_mayors.py --tag mayors-20261026 [--n 20] [--seed 1026]

The sample covers every infobox and Wikidata verdict on a page that names someone (consistent ones included), drawn
with a fixed seed so it can be redrawn. For each: the comuna, the page, the field as written, the class and
explanation, and every SERVEL winner and the candidates whose names fit. The judgment itself is made by whoever reads
the output; eval/mayors_spot_check.md records ours.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402

PAGES = {"es": "Wikipedia ES", "en": "Wikipedia EN", "wikidata": "Wikidata"}


def verdicts(result):
    for comuna in result["comunas"]:
        for finding in comuna["findings"]:
            if finding["claim"].get("name") and finding["aspect"] == "value":
                yield comuna, finding["claim"], finding["class"], finding["explanation"]
        for check in comuna["checks"]:
            if check["claim"].get("name"):
                yield comuna, check["claim"], check["result"], check["note"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1026)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    output = load_settings(sample_mode=False).output_dir
    pool = []
    for path in sorted(output.glob(f"national-{args.tag}-*/result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        pool += [(result["run_id"], *v) for v in verdicts(result)]
    sample = random.Random(args.seed).sample(pool, min(args.n, len(pool)))
    print(f"{len(pool)} verdicts on pages that name someone; sample of {len(sample)} (seed {args.seed})\n")
    for i, (run_id, comuna, claim, cls, why) in enumerate(sample, 1):
        winners = {y: e["elected"] for y, e in sorted(comuna["elections"].items())}
        print(f"{i}. {comuna['name']} ({comuna['cut']}), {PAGES[claim['target']]} {claim.get('location')}: "
              f"{claim.get('name')!r}" + (f" [field: {claim.get('name_raw')!r}]" if claim.get("name_raw") else ""))
        print(f"   verdict: {cls}: {why}")
        print(f"   SERVEL winners: {winners}")
        print(f"   run: {run_id}\n")


if __name__ == "__main__":
    main()
