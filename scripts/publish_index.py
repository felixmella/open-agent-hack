"""Write output_examples/index.html: a page linking every recorded run in output_examples/ (the live examples and the
national batches, population and mayors), with each run's headline numbers, read from its own files. With GitHub Pages serving the repository,
readers can open the review queues without running anything. FactSync never reads output_examples/.

Usage:  .venv\\Scripts\\python scripts\\publish_index.py
"""
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT  # noqa: E402
from app.report.html import SOURCES, title_case  # noqa: E402

OUT = ROOT / "output_examples"
REPO = "https://github.com/felixmella/open-agent-hack/blob/main"  # Markdown reads best on GitHub
REGIONS = {"tarapaca": "Tarapacá", "antofagasta": "Antofagasta", "atacama": "Atacama", "coquimbo": "Coquimbo",
           "valparaiso": "Valparaíso", "libertador-general-bernardo-o-higgins": "O'Higgins", "maule": "Maule",
           "biobio": "Biobío", "la-araucania": "La Araucanía", "los-lagos": "Los Lagos",
           "aysen-del-general-carlos-ibanez-del-camp": "Aysén", "magallanes-y-de-la-antartica-chilena": "Magallanes",
           "metropolitana-de-santiago": "Metropolitana de Santiago", "los-rios": "Los Ríos",
           "arica-y-parinacota": "Arica y Parinacota", "nuble": "Ñuble"}
STYLE = """
:root { --bg: #f5f6f8; --panel: #fff; --ink: #18202b; --muted: #5a6473; --line: #e2e6ec; --accent: #0b5fbf; }
@media (prefers-color-scheme: dark) { :root { --bg: #0e1217; --panel: #151b23; --ink: #e5e9ef; --muted: #98a2b3;
  --line: #252f3c; --accent: #6aa8ff; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--accent); }
.wrap { max-width: 1000px; margin: 0 auto; padding: 28px 16px 40px; }
h1 { font-size: 26px; margin: 0 0 8px; } h2 { font-size: 18px; margin: 28px 0 10px; }
p { margin: 0 0 10px; max-width: 760px; } .muted { color: var(--muted); }
.table { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-top: 1px solid var(--line); vertical-align: top; }
thead th { border-top: 0; color: var(--muted); font-weight: 600; }
td.num { font-variant-numeric: tabular-nums; }
"""


def esc(value):
    return html.escape(str(value))


def row(name, about, folder):
    summary, usage = about["summary"], about["model_usage"]
    served = ", ".join(f"{m} ({n})" for m, n in usage.get("served_model", {}).items()) or "none"
    files = " · ".join(f'<a href="{folder}/{f}">{label}</a>' for f, label in (
        ("report.html", "review queue"), ("result.json", "result"), ("trace.jsonl", "trace"),
        ("world-model-audit.jsonl", "World Model audit")) if (OUT / folder / f).exists())
    result = json.loads((OUT / folder / "result.json").read_text(encoding="utf-8"))
    described = ", ".join(title_case(c["name"]) for c in result["comunas"])
    return (f"<tr><td><b>{esc(name)}</b><br><span class=muted>{esc(described)}</span></td>"
            f"<td class=num>{summary['comunas']}</td><td class=num>{summary['findings']}</td>"
            f"<td class=num>{summary['drafts']}</td><td class=num>{summary['critic_rejections']}</td>"
            f"<td>{esc(', '.join(SOURCES.get(s, s) for s in summary.get('discoveries') or []) or '—')}</td>"
            f"<td class=num>{usage['calls']}<br><span class=muted>{esc(served)}</span></td>"
            f"<td class=num>{round(about['seconds'] / 60, 1)} min</td><td>{files}</td></tr>")


def national_section(folder, title):
    """A national batch's headline and one row per region, or '' when the batch isn't kept."""
    path = OUT / folder / "summary.json"
    if not path.exists():
        return ""
    summary = json.loads(path.read_text(encoding="utf-8"))
    regions = []
    for run in summary["runs"]:
        slug = re.search(r"-\d{2}-(.+)$", run["run_id"]).group(1)
        name = REGIONS.get(slug, slug.replace("-", " ").title())
        regions.append(f'<tr><td><a href="{folder}/{esc(run["run_id"])}/report.html">{esc(name)}</a></td>'
                       f"<td class=num>{run['comunas']}</td><td class=num>{run['findings']}</td>"
                       f"<td class=num>{run['drafts']}</td></tr>")
    if summary.get("fact") == "mayor":
        headline = (f"<p>Of <b>{summary['pages_naming_a_mayor']}</b> pages that name a mayor across Spanish and English "
                    f"Wikipedia and Wikidata, <b>{summary['naming_someone_else']} ({summary['share_someone_else']:.0%})"
                    f"</b> don't name the mayor SERVEL says was elected in October 2024.")
    else:
        headline = (f"<p>Of <b>{summary['current_figures']}</b> current population figures shown across Spanish and "
                    f"English Wikipedia and Wikidata, <b>{summary['differing_from_census_2024']} "
                    f"({summary['share_differing']:.0%})</b> are not INE's Census 2024 count.")
    headline += (f" Run with the {esc(summary['method'])}. "
                 f'<a href="{REPO}/output_examples/{folder}/summary.md">Summary</a>.</p>')
    return (f'<h2>{title}</h2>{headline}<div class="table"><table><thead><tr><th>Region</th><th>Comunas</th>'
            f'<th>Findings</th><th>Drafts</th></tr></thead><tbody>{"".join(regions)}</tbody></table></div>')


def main():
    examples = sorted(p for p in OUT.iterdir() if (p / "about.json").exists())
    rows = [row(p.name.replace("_", " ").capitalize(), json.loads((p / "about.json").read_text(encoding="utf-8")),
                p.name) for p in examples]
    sections = [national_section("national", "All 346 comunas, region by region: population"),
                national_section("national_mayors", "All 346 comunas, region by region: mayors")]
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FactSync Chile runs</title><style>{STYLE}</style></head>
<body><div class="wrap">
<p class="muted">FactSync Chile · Open Agent Hackathon 2026</p>
<h1>Recorded runs</h1>
<p>Real runs of FactSync Chile, kept as evidence: each one's review queue, result, agent trace and World Model audit
log, as the run wrote them. Every source was read live through Zetaris, and every model call went through Meterless
Nightshift to NVIDIA Nemotron. FactSync never reads these files. <a href="{REPO}/README.md">About the project</a>.</p>
<h2>Live runs with the model</h2>
<div class="table"><table><thead><tr><th>Run</th><th>Comunas</th><th>Findings</th><th>Drafts</th><th>Critic rejections</th>
<th>Sources discovered</th><th>Model calls</th><th>Time</th><th>Files</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{''.join(sections)}
<h2>What the model adds</h2>
<p>The same comunas from the same recorded rows, with and without the model, every difference adjudicated:
<a href="{REPO}/eval/results.md">eval/results.md</a>.</p>
</div></body></html>
"""
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(f"wrote {OUT / 'index.html'}: {len(rows)} runs, {sum(1 for s in sections if s)} national batches")


if __name__ == "__main__":
    main()
