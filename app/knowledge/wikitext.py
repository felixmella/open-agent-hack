"""Deterministic wikitext helpers: the parts of a population claim that code can read reliably.

Anything these helpers can't read cleanly (a year written into the value field, a figure only in the prose) is left
to the Extractor agent, which reads the text with the model and is checked against the quotes it returns.
"""
import re
from urllib.parse import urlparse

REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S)
UNCLOSED_REF = re.compile(r"<ref[^>]*>.*$", re.S)
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
EXTERNAL_LINK = re.compile(r"\[https?://\S+\s*([^\]]*)\]")
NUMBER = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+|\d+")
YEAR = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
NAMED_REF = re.compile(r'<ref\s+name\s*=\s*"?([^">/]+?)"?\s*>(.*?)</ref>', re.S | re.I)
NAMED_REF_USE = re.compile(r'<ref\s+name\s*=\s*"?([^">/]+?)"?\s*/>', re.I)
URL = re.compile(r"https?://[^\s|\]}<]+")
DATE_PARAM = re.compile(r"\|\s*(?:fechaacceso|accessdate|access-date|fechaarchivo|archivedate|archive-date|urlarchivo|"
                        r"archiveurl|archive-url|fecha|date)\s*=[^|}]*", re.I)
HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
POPULATION_WORDS = re.compile(r"habitantes|poblaci[oó]n|censo|inhabitants|population|census|residents", re.I)
FIGURE = re.compile(r"\d{1,3}(?:[., ]\d{3})+|\d{3,}")
CENSUS_WORDS = re.compile(r"cens", re.I)
PROJECTION_WORDS = re.compile(r"proyecci|estimaci|projection|estimate", re.I)


def strip_markup(text):
    """Drop references, unwrap links and non-breaking spaces; keep the visible text."""
    if not text:
        return ""
    text = UNCLOSED_REF.sub("", REF.sub(" ", text))
    text = EXTERNAL_LINK.sub(r"\1", LINK.sub(r"\1", text))
    text = text.replace("&nbsp;", " ").replace(" ", " ")
    return " ".join(text.split())


def parse_population(raw):
    """A figure written as 26.746, 26,746, 24 640 or 46121; None when the field holds anything else."""
    candidate = TEMPLATE.sub("", strip_markup(raw)).strip()
    if NUMBER.fullmatch(candidate):
        return int(re.sub(r"\D", "", candidate))
    return None


def parse_year(raw):
    """The first plausible year (1800-2099) in a field such as '[[Censo chileno de 2017|2017]]' or '2012 Census'."""
    match = YEAR.search(strip_markup(raw))
    return int(match.group(1)) if match else None


def has_citation(raw):
    """Whether a reference field cites something (a <ref>, a template such as {{cita web}}, or a link)."""
    text = (raw or "").strip()
    if not text or re.fullmatch(r"\{\{\s*(cr|cita requerida|citation needed)\s*\}\}", text, re.I):
        return False
    return bool(re.search(r"<ref|\{\{\s*(cit|cite)|https?://", text, re.I))


def named_references(wikitext):
    """Each named reference's content, as defined once in the article (<ref name="INE">...</ref>)."""
    refs = {}
    for name, body in NAMED_REF.findall(wikitext or ""):
        refs.setdefault(name.strip(), body.strip())
    return refs


def resolve_reference(raw, wikitext):
    """The citation behind a reference field: inline refs as written, reused ones (<ref name="INE"/>) looked up."""
    refs = named_references(wikitext) if NAMED_REF_USE.search(raw or "") else {}
    return NAMED_REF_USE.sub(lambda m: refs.get(m.group(1).strip(), m.group(0)), raw or "")


def citation_facts(text):
    """What a citation points at: the years it names (access and archive dates left out) and its web domains."""
    undated = DATE_PARAM.sub("", text or "")
    domains = {urlparse(url).netloc.lower() for url in URL.findall(text or "")}
    return {"years": sorted({int(y) for y in YEAR.findall(undated)}),
            "domains": sorted(d[4:] if d.startswith("www.") else d for d in domains if d)}


def basis_of(text):
    """'census' or 'projection' when a label says so ('2012 Census', 'proyección 2020'), else None."""
    if PROJECTION_WORDS.search(text or ""):
        return "projection"
    return "census" if CENSUS_WORDS.search(text or "") else None


def template_body(wikitext, name):
    """The inside of the first {{name ...}} template, nested templates included; None if there is none."""
    match = re.search(r"\{\{\s*" + re.escape(name), wikitext or "", re.I)
    if not match:
        return None
    depth, i = 0, match.start()
    while i < len(wikitext):
        if wikitext.startswith("{{", i):
            depth, i = depth + 1, i + 2
        elif wikitext.startswith("}}", i):
            depth, i = depth - 1, i + 2
            if depth == 0:
                return wikitext[match.end():i - 2]
        else:
            i += 1
    return None


def split_parameters(body):
    """A template's parameters, split on the pipes that aren't inside a nested template or link."""
    parts, current, depth, i = [], [], 0, 0
    while i < len(body):
        pair = body[i:i + 2]
        if pair in ("{{", "[["):
            depth, i = depth + 1, i + 2
            current.append(pair)
        elif pair in ("}}", "]]"):
            depth, i = depth - 1, i + 2
            current.append(pair)
        elif body[i] == "|" and depth == 0:
            parts.append("".join(current))
            current, i = [], i + 1
        else:
            current.append(body[i])
            i += 1
    parts.append("".join(current))
    return [p.strip() for p in parts[1:]]


def historical_populations(wikitext):
    """The year/figure pairs of an English article's {{Historical populations}} table, in article order."""
    body = template_body(wikitext, "Historical populations")
    if body is None:
        return []
    positional = [p for p in split_parameters(body) if not re.match(r"^[\w -]+=", p)]
    rows = []
    for year_raw, value_raw in zip(positional[::2], positional[1::2]):
        year, value = parse_year(year_raw), parse_population(value_raw)
        if year and value is not None and year_raw.strip().isdigit():
            rows.append({"year": year, "value": value, "raw": f"|{year_raw} |{value_raw}"})
    return rows


def drop_templates(text):
    """Remove templates (infoboxes, citations), innermost first, keeping the first value of inline ones such as
    {{convert|530.5|sqkm}}."""
    text = text or ""
    while True:
        reduced = re.sub(r"\{\{\s*(?:convert|formatnum:|nowrap|nobr)\s*\|?([^|{}]*)[^{}]*\}\}", r"\1", text, flags=re.I)
        reduced = TEMPLATE.sub("", reduced)
        if reduced == text:
            return text
        text = reduced


def visible_text(text):
    """Readable text from wikitext: templates dropped, references and link markup removed, bold and italics
    unwrapped."""
    return re.sub(r"'{2,}", "", strip_markup(drop_templates(text)))


# Lines that aren't running prose: lists (often locality figures), tables and images.
SKIPPED_LINES = ("*", "#", "{|", "|", "!", "[[Archivo:", "[[File:", "[[Imagen:", "[[Image:")


def article_passages(wikitext, *, limit=6000):
    """The paragraphs that talk about the population, as visible text tagged with their section, in article
    order and within `limit` characters: what the Extractor reads."""
    sections, last, heading = [], 0, "lead"
    for match in HEADING.finditer(wikitext or ""):
        sections.append((heading, wikitext[last:match.start()]))
        heading, last = match.group(2).strip(), match.end()
    sections.append((heading, (wikitext or "")[last:]))
    passages, used = [], 0
    for heading, raw in sections:
        lines = [line for line in drop_templates(raw).splitlines() if not line.lstrip().startswith(SKIPPED_LINES)]
        for paragraph in re.split(r"\n\s*\n", "\n".join(lines)):
            text = " ".join(visible_text(paragraph).split())
            if not text or not POPULATION_WORDS.search(text) or not FIGURE.search(text):
                continue
            if used + len(text) > limit:
                return passages
            passages.append({"section": heading, "text": text})
            used += len(text)
    return passages


def quote_supported(quote, passages, value_text, year=None):
    """Code check for every extracted claim: the quote appears verbatim in the passages, the figure appears
    verbatim in the quote, and so does the year when one is given."""
    def squash(s):
        return " ".join(str(s or "").replace(" ", " ").replace("&nbsp;", " ").split())
    quote, value_text = squash(quote), squash(value_text)
    if not quote or not value_text or value_text not in quote:
        return False
    if year is not None and str(year) not in quote:
        return False
    return any(quote in squash(p["text"]) for p in passages)


STATED_FIGURE = re.compile(r"(\d{1,3}(?:[., ]\d{3})+|\d{3,7})\s*(?:habitantes|inhabitants|personas|people|residents)"
                           r"|(?:poblaci[oó]n de|population of)\s*(?:aproximadamente\s*)?(\d{1,3}(?:[., ]\d{3})+|\d{3,7})",
                           re.I)
CENSUS_YEAR = re.compile(r"(?:censo|census)\D{0,25}?((?:19|20)\d{2})|((?:19|20)\d{2})\D{0,12}?(?:censo|census)", re.I)


def sentences(text):
    """Split visible text into sentences without breaking figures written as 25.795."""
    return [s.strip() for s in re.split(r"\.(?=\s)|;\s", text) if s.strip()]


def rule_claims(passages):
    """Population statements found by pattern ('censo de 2024 ... 1 598 habitantes', 'the 2017 census ... 24,333
    inhabitants'): the Extractor's deterministic path, used when the model is unavailable."""
    claims = []
    for passage in passages:
        for sentence in sentences(passage["text"]):
            figure = STATED_FIGURE.search(sentence)
            if not figure or not re.search(r"cens|poblaci[oó]n|population", sentence, re.I):
                continue
            value_text = figure.group(1) or figure.group(2)
            year = CENSUS_YEAR.search(sentence)
            year_value = int(year.group(1) or year.group(2)) if year else None
            basis = "projection" if PROJECTION_WORDS.search(sentence) else "census" if year else "unspecified"
            if year_value is None and YEAR.search(sentence):  # '(INE 2002)', 'en 1970'
                year_value = int(YEAR.search(sentence).group(1))
            claims.append({"value_text": value_text, "value": parse_population(value_text), "year": year_value,
                           "basis": basis, "scope": "comuna", "location": "lead" if passage["section"] == "lead" else "body",
                           "quote": sentence})
    return claims
