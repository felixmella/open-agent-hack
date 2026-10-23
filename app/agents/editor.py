"""Editor: drafts the corrections a human editor can review and apply. FactSync never edits Wikipedia or Wikidata.

Wikitext, citations and QuickStatements come from templates, so every figure and source in a draft is exactly the
approved one. The model writes the edit summaries and the explanation for the reviewer, which the Critic checks.
"""
import re
from datetime import datetime, timezone

from app.agents.llm import fits, model_note
from app.knowledge.matcher import fmt, latest_census
from app.knowledge.taxonomy import census_facts, official_source
from app.knowledge.wikitext import BREAK, parse_population, visible_text

ES_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
REASON_ES = {"outdated_vintage": "cifra de un censo anterior", "different_definition": "proyección del INE, no un conteo censal",
             "discredited_source": "censo de 2012, cuyos resultados el INE retiró", "nonexistent_census": "censo inexistente",
             "mislabelled_vintage": "año o censo mal indicado", "genuine_error": "error de tipeo",
             "internal_inconsistency": "contradecía el texto del artículo", "unsourced": "sin referencia",
             "cross_source_mismatch": "cifra sin respaldo oficial", "missing_value": "sin cifra"}
REASON_EN = {"outdated_vintage": "an older census count", "different_definition": "an INE projection, not a census count",
             "discredited_source": "the withdrawn 2012 census", "nonexistent_census": "a census that never took place",
             "mislabelled_vintage": "mislabelled year or census", "genuine_error": "a typo",
             "internal_inconsistency": "contradicted the article text", "unsourced": "unsourced",
             "cross_source_mismatch": "no official source", "missing_value": "no figure"}

PROMPT = """FactSync Chile - Editor.
You write the wording for draft corrections of population figures for a Chilean comuna. A human editor will review
the drafts; nothing is published automatically. Write:
- es_summary: a Spanish Wikipedia edit summary (at most 250 characters) for the eswiki draft, if there is one
- en_summary: an English Wikipedia edit summary (at most 250 characters) for the enwiki draft, if there is one
- explanation: 2 to 4 plain English sentences for the reviewer: why the figures for this comuna differ, and what the
  drafts change
Each summary must give the new figure and say it comes from INE. Use only the figures given; never compute new ones.
If a critic_instruction is given, follow it.
JSON: {"es_summary": "...", "en_summary": "...", "explanation": "..."}"""


def format_like(value, raw):
    """A figure in the article's own style: 25.795, 25,795, 25&nbsp;795, 25 795 or 25795."""
    for separator in ("&nbsp;", ".", ",", " "):
        if re.search(r"\d" + re.escape(separator) + r"\d{3}(?!\d)", raw or ""):
            return f"{value:,}".replace(",", separator)
    return str(value)


def es_date(day):
    return f"{day.day} de {ES_MONTHS[day.month - 1]} de {day.year}"


def en_date(day):
    return f"{day.day} {EN_MONTHS[day.month - 1]} {day.year}"


def qid(item):
    return str(item or "").rstrip("/").rsplit("/", 1)[-1]


class Editor:
    name = "Editor"

    def __init__(self, world, tracer, llm, run_id, today=None):
        self.world = world
        self.tracer = tracer
        self.llm = llm
        self.run_id = run_id
        self.today = today or datetime.now(timezone.utc).date()

    def draft(self, comuna, findings, table, round_no, instruction=None):
        """Drafts for each target with approved findings, plus the reviewer's explanation. Returns a dict keyed
        eswiki / enwiki / wikidata, and 'explanation'."""
        latest = latest_census(table)
        key = f"census_{latest['year']}"
        source = official_source(key)
        correction = {"value": latest["value"], "year": latest["year"], "definition": "census", "source_key": key,
                      "url": source["url"], "obs_id": latest["obs_id"]}
        drafts = {}
        for language, target in (("es", "eswiki"), ("en", "enwiki")):
            mine = [f for f in findings if f["target"] == language]
            if mine:
                drafts[target] = self.article_draft(language, mine, correction, source)
        mine = [f for f in findings if f["target"] == "wikidata"]
        if mine:
            drafts["wikidata"] = self.wikidata_draft(mine, correction)
        if not drafts:
            return {}
        targets = list(drafts)
        self.word(comuna, drafts, findings, correction, round_no, instruction)
        for name in targets:
            anchor = drafts[name].pop("anchor")
            self.world.assess(anchor, agent=self.name, run_id=self.run_id, round_no=round_no,
                              data={"status": "drafted", "draft": name, **drafts[name]})
        self.tracer.event(self.name, "draft_corrections", input_summary=f"{comuna.name}: {len(findings)} approved findings",
                          output_summary=", ".join(f"{k} ({len(drafts[k]['findings'])} findings)" for k in targets)
                                         + f"; wording: {drafts['explanation_by']['method']}",
                          target_agent="Critic", round_no=round_no)
        return drafts

    def article_draft(self, language, findings, correction, source):
        infobox = next((f["claim"] for f in findings if f["claim"]["location"] == "infobox"), None)
        draft = {"target": f"{language}wiki", "page": findings[0]["claim"].get("title"),
                 "revid": findings[0]["claim"].get("revid"), "correction": correction,
                 "findings": [f["id"] for f in findings], "anchor": findings[0]["claim"]["id"]}
        draft["url"] = f"https://{language}.wikipedia.org/wiki/" + str(draft["page"] or "").replace(" ", "_")
        year, value = correction["year"], correction["value"]
        if infobox:
            figure = format_like(value, infobox.get("value_raw"))
            if language == "es":
                draft["wikitext"] = "\n".join([
                    f"| población = {figure}",
                    f"| población_año = [[Censo chileno de {year}|{year}]]",
                    f"| población_post = <ref name=\"censo{year}\">{{{{cita web |url={source['url']} |título={source['title']} "
                    f"|editorial={source['publisher']} |fechaacceso={es_date(self.today)}}}}}</ref>"])
            else:
                draft["wikitext"] = "\n".join([
                    f"| population_total = {figure}",
                    f"| population_as_of = [[{year} Chilean census|{year} Census]]",
                    f"| population_footnotes = <ref name=\"Censo{year}\">{{{{cite web |url={source['url']} |title={source['title']} "
                    f"|publisher={source['publisher']} |language=es |access-date={en_date(self.today)}}}}}</ref>"])
            draft["replaces"] = {"value": infobox.get("value_raw"), "year": infobox.get("label"),
                                 "reference": infobox.get("reference_raw") or ""}
            draft["anchor"] = infobox["id"]
            field = infobox.get("field") or ("población" if language == "es" else "population_total")
            if infobox.get("value_from") == "wikidata" and infobox.get("value") is not None:
                draft["notes"] = [f"The infobox's {field} field is empty, so it shows Wikidata's figure, "
                                  f"{fmt(infobox['value'])}. The lines below give the article a figure of its own; "
                                  f"correcting Wikidata's statement (see the Wikidata draft) updates this infobox too."]
            elif infobox.get("missing"):
                draft["notes"] = [f"The infobox's {field} field is empty and it shows no population: the lines below "
                                  f"add one."]
        changes = []
        for finding in findings:
            claim, proposal = finding["claim"], finding.get("proposal") or {}
            if claim["location"] not in ("lead", "body"):
                continue
            change = {"quote": claim.get("quote"), "finding": finding["id"], "why": finding["explanation"]}
            if proposal.get("action") in ("fix_figure", "update"):
                change.update(replace=claim.get("value_raw"), by=format_like(proposal["value"], claim.get("value_raw")))
                if proposal.get("action") == "update":
                    change["note"] = f"state the Census {year} figure and cite INE"
            elif proposal.get("action") == "relabel":
                change["note"] = f"the figure is the {proposal['year']} {proposal.get('definition', 'census')} figure: correct the year"
            else:
                change["note"] = "remove the figure or give its source"
            changes.append(change)
        if changes:
            draft["text_changes"] = changes
        if "wikitext" not in draft:  # text changes only: offer a sourced sentence with the current figure
            figure = format_like(value, changes[0].get("replace"))
            if language == "es":
                draft["wikitext"] = (f"Según el [[Censo chileno de {year}|censo de {year}]], la comuna tiene una población "
                                     f"de {figure} habitantes.<ref name=\"censo{year}\">{{{{cita web |url={source['url']} "
                                     f"|título={source['title']} |editorial={source['publisher']} "
                                     f"|fechaacceso={es_date(self.today)}}}}}</ref>")
            else:
                draft["wikitext"] = (f"According to the [[{year} Chilean census|{year} census]], the commune had a "
                                     f"population of {figure}.<ref name=\"Censo{year}\">{{{{cite web |url={source['url']} "
                                     f"|title={source['title']} |publisher={source['publisher']} |language=es "
                                     f"|access-date={en_date(self.today)}}}}}</ref>")
        return draft

    def wikidata_draft(self, findings, correction):
        ids = census_facts()["wikidata"]
        item = next((f["claim"].get("item") for f in findings if f["claim"].get("item")), None)
        draft = {"target": "wikidata", "page": qid(item), "url": f"https://www.wikidata.org/wiki/{qid(item)}",
                 "correction": correction, "findings": [f["id"] for f in findings], "anchor": findings[0]["claim"]["id"]}
        draft["quickstatements"] = (
            f"{qid(item)}|{ids['population']}|{correction['value']}|{ids['point_in_time']}|+{correction['year']}-00-00T00:00:00Z/9"
            f"|{ids['determination_method']}|{ids['census']}|{ids['reference_url']}|\"{correction['url']}\""
            f"|{ids['retrieved']}|+{self.today.isoformat()}T00:00:00Z/11")
        notes = [f"QuickStatements can't set ranks: after adding the Census {correction['year']} statement, set it to "
                 f"preferred rank so it is used as the current population; leave older statements at normal rank."]
        for finding in findings:
            claim, proposal = finding["claim"], finding.get("proposal") or {}
            if claim["location"] != "statement" or finding["aspect"] != "value":
                continue
            shown = f"{fmt(claim['value'])} statement ({claim.get('label')})"
            if proposal.get("action") == "relabel":
                notes.append(f"The {shown} is the {proposal['year']} {proposal.get('definition', 'census')} figure: set its "
                             f"point in time to {proposal['year']}" + (f" and its determination method to census "
                                                                       f"({ids['census']})." if proposal.get('definition') == 'census' else "."))
            elif proposal.get("action") == "deprecate":
                notes.append(f"Set the {shown} to deprecated rank: {finding['explanation']}")
            else:
                notes.append(f"Check the {shown}: {finding['explanation']}")
        draft["notes"] = notes
        return draft

    def word(self, comuna, drafts, findings, correction, round_no, instruction):
        """Edit summaries and the reviewer's explanation: from the model, or from templates."""
        def first(fs):  # the finding a page's wording leads with: the infobox figure's, then any figure's
            return min(fs, key=lambda f: (f["aspect"] != "value", f["claim"].get("location") != "infobox")) if fs else None
        lead = {target: first([f for f in findings if f["target"] == target[:2]]) for target in ("eswiki", "enwiki")}

        mine = {k: [f for f in findings if f["id"] in v["findings"]] for k, v in drafts.items()}
        main = {k: first(fs)["id"] for k, fs in mine.items()}

        def payload(main_length, other_length):  # explanations cut to these lengths (left out at 0)
            def replaced(draft):
                old = dict(draft.get("replaces") or {})
                if other_length < 600:
                    old.pop("reference", None)
                return old or None

            def entry(key, finding):
                length = main_length if finding["id"] == main[key] else other_length
                return {"class": finding["class"], **({"explanation": finding["explanation"][:length]} if length else {})}
            body = {"comuna": comuna.name, "new_figure": {"value": correction["value"], "year": correction["year"],
                                                          "source": "INE, Censo de Población y Vivienda 2024"},
                    "drafts": {k: {"replaces": replaced(v), "findings": [entry(k, f) for f in mine[k]]}
                               for k, v in drafts.items()}}
            if instruction:
                body["critic_instruction"] = instruction[:300]
            return body

        # one request, made small enough to stream: shorter explanations first, then only each draft's main finding
        levels = ((600, 600), (240, 240), (240, 100), (240, 0), (160, 0))
        body = next((p for p in (payload(*level) for level in levels) if fits(p)), payload(0, 0))
        reply = self.llm.ask_json(self.name, "word_drafts", PROMPT, body, target_agent="Critic", round_no=round_no,
                                  validate=lambda d: None if d.get("explanation") else "no explanation") if self.llm else None
        new_es, new_en = correction["value"], fmt(correction["value"])
        for target in ("eswiki", "enwiki"):
            if target not in drafts:
                continue
            finding = lead[target]
            old = visible_text(BREAK.sub(" / ", (drafts[target].get("replaces") or {}).get("value") or ""))
            if not old and finding["claim"].get("value_from") == "wikidata" and finding["claim"].get("value") is not None:
                old = f"{finding['claim']['value']} " + ("de Wikidata" if target == "eswiki" else "from Wikidata")
            old = old or ("sin cifra" if target == "eswiki" else "no figure")
            same = parse_population(old) == correction["value"]  # right figure, wrong label or reference
            if reply and reply[0].get(f"{target[:2]}_summary"):
                drafts[target]["edit_summary"] = str(reply[0][f"{target[:2]}_summary"])[:500]
            elif target == "eswiki":
                figure = format_like(new_es, old)
                was = "misma cifra" if same else f"antes {old}"
                why = "" if finding["class"] == "missing_value" else f": {REASON_ES.get(finding['class'], finding['class'])}"
                drafts[target]["edit_summary"] = (f"Población según el Censo {correction['year']} del INE: {figure} hab. "
                                                  f"({was}{why}).")
            else:
                was = "same figure" if same else f"was {old}"
                why = "" if finding["class"] == "missing_value" else f": {REASON_EN.get(finding['class'], finding['class'])}"
                drafts[target]["edit_summary"] = (f"Population per INE's {correction['year']} census: {new_en} "
                                                  f"({was}{why}).")
        if "wikidata" in drafts:
            drafts["wikidata"]["edit_summary"] = f"Add Census {correction['year']} population ({new_en}) from INE"
        if reply:
            drafts["explanation"] = str(reply[0]["explanation"])[:1500]
        else:  # each page's main finding, in page order, each sentence once
            leads = [next(f for f in findings if f["id"] == main[k]) for k in mine]
            sentences = [s for f in leads for s in re.split(r"(?<=\.)\s+", f["explanation"].strip()) if s]
            drafts["explanation"] = " ".join(dict.fromkeys(sentences)) + \
                f" The drafts give the Census {correction['year']} count, {new_en}, cited to INE."
        drafts["explanation_by"] = model_note(reply[1]) if reply else {"method": "rules"}
