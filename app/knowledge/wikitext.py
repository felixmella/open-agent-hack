"""Deterministic wikitext helpers: the parts of a population claim that code can read reliably.

Anything these helpers can't read cleanly (a year written into the value field, a figure only in the prose) is left
to the Extractor agent, which reads the text with the model and is checked against the quotes it returns.
"""
import re

REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S)
UNCLOSED_REF = re.compile(r"<ref[^>]*>.*$", re.S)
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
EXTERNAL_LINK = re.compile(r"\[https?://\S+\s*([^\]]*)\]")
NUMBER = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+|\d+")
YEAR = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")


def strip_markup(text):
    """Drop references, unwrap links and non-breaking spaces; keep the visible text."""
    if not text:
        return ""
    text = UNCLOSED_REF.sub("", REF.sub("", text))
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
