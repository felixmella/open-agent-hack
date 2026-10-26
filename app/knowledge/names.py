"""People's names, as Wikipedia, Wikidata and SERVEL write them: cleaning an infobox field down to a name, and
deciding how closely a written name fits a person in SERVEL's results.

SERVEL writes names in capitals without accents, as given names, first surname and second surname, and in 2024
gives only the first given name ("ENRIQUE" / "DEL BARRIO" / "HERNANDEZ"). Articles write them with accents, often
without the second surname or with every given name ("Enrique Alfonso del Barrio Hernández"), sometimes with a
nickname ("Max Luksic") or a typo ("Alejando"). The comparison is positional: the given names written before the
person's first surname, the second surname after it.

Levels, strongest first:
  same      the first surname, a given name, and no other second surname: the same person
  likely    the first surname, and a given name that is a nickname, an abbreviation or one letter off (or a
            surname one letter off): probably the same person, which the model is asked to confirm
  partial   the surnames fit but the given name doesn't (a relative?), or another second surname: the model decides
  none      no fit
"""
import re
import unicodedata

PARTICLES = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "E"}
LEVELS = {"same": 3, "likely": 2, "partial": 1, "none": 0}
# Spanish nicknames and short forms of given names (folded): nickname -> given names it stands for
NICKNAMES = {
    "MAX": {"MAXIMILIANO", "MAXIMO"}, "PATO": {"PATRICIO"}, "PANCHO": {"FRANCISCO"}, "PACO": {"FRANCISCO"},
    "PEPE": {"JOSE"}, "NACHO": {"IGNACIO"}, "MANOLO": {"MANUEL"}, "LUCHO": {"LUIS"}, "CHELO": {"MARCELO", "MARCELA"},
    "TITO": {"ALBERTO", "HECTOR"}, "MEMO": {"GUILLERMO"}, "TOMMY": {"TOMAS"}, "CHRISTIAN": {"CRISTIAN"},
    "CRISTIAN": {"CHRISTIAN"}, "JOHNNY": {"JUAN", "JONATHAN"}, "JUANCHO": {"JUAN"}, "RODO": {"RODOLFO", "RODRIGO"},
    "FELO": {"RAFAEL"}, "RAFA": {"RAFAEL"}, "ALE": {"ALEJANDRO", "ALEJANDRA"}, "CATA": {"CATALINA"},
    "CONI": {"CONSTANZA"}, "JAVI": {"JAVIER", "JAVIERA"}, "GABO": {"GABRIEL"}, "LALO": {"EDUARDO"},
}
BREAK = re.compile(r"<br\s*/?>|\n", re.I)
TITLES = re.compile(r"^(?:SR|SRA|SRTA|DR|DRA|DON|DONA|D)\b\.?\s+", re.I)


def fold(text):
    """Upper case, accents and punctuation removed: 'Núñez' -> 'NUNEZ', 'O'Ryan' -> 'O RYAN'."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z]+", " ", text).split())


def tokens(text):
    return [t for t in fold(text).split() if t not in PARTICLES]


def visible(raw):
    """What an infobox field shows: references, comments and templates dropped, wikilinks by their label."""
    text = re.sub(r"<!--.*?(-->|$)", "", str(raw or ""), flags=re.S)
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?(</ref>|$)", "", text, flags=re.S | re.I)
    text = re.sub(r"\{\{\s*(?:nowrap|small|nobr)\s*\|([^{}]*)\}\}", r"\1", text, flags=re.I)
    while re.search(r"\{\{[^{}]*\}\}", text):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s*([^\]]*)\]", r"\1", text)
    text = re.sub(r"'''?|<[^>]+>", " ", BREAK.sub("\n", text))
    return text


def link_target(raw):
    """The article a name field links to, when it links one ('[[Jairo del Pino Lema|Jairo del Pino]]')."""
    match = re.search(r"\[\[([^|\]#]+)(?:\|[^\]]*)?\]\]", str(raw or ""))
    return match.group(1).strip() if match else None


def parse_field(raw):
    """An infobox name field -> {'name', 'notes' (text in brackets: party, 'alcalde suplente'), 'others' (more
    names after a line break), 'linked'}; name None when the field names no one."""
    lines = [line.strip(" ,;") for line in visible(raw).split("\n")]
    lines = [line for line in lines if re.search(r"[A-Za-zÀ-ÿ]", line)]
    if not lines:
        return {"name": None, "notes": [], "others": [], "linked": None}
    first = lines[0]
    notes = [n.strip() for n in re.findall(r"\(([^()]*)\)", first) if n.strip()]
    name = re.sub(r"\([^()]*\)|\(.*$", "", first)
    name = TITLES.sub("", " ".join(name.split())).strip(" ,;-–")
    others = [re.sub(r"\([^()]*\)", "", line).strip(" ,;-–") for line in lines[1:]]
    target = link_target(raw)
    linked = target if target and fold(target) != fold(name) and set(tokens(name)) <= set(tokens(target)) else None
    return {"name": name or None, "notes": notes, "others": [o for o in others if o], "linked": linked}


def person(nombres, primer_apellido, segundo_apellido):
    return {"given": tokens(nombres), "first": tokens(primer_apellido), "second": tokens(segundo_apellido),
            "full": " ".join(str(p) for p in (nombres, primer_apellido, segundo_apellido) if p)}


def one_off(a, b):
    """Whether two words differ by one edit (a letter added, dropped or changed), for words of 5 letters or more."""
    if a == b or min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def given_fit(word, given):
    """How a written given name fits a person's given names: 'exact', 'near' (nickname, abbreviation, one letter
    off) or None."""
    if word in given:
        return "exact"
    if any(g in NICKNAMES.get(word, ()) for g in given):
        return "near"
    if len(word) >= 3 and any(g.startswith(word) and len(g) > len(word) for g in given):  # MAX -> MAXIMILIANO
        return "near"
    if len(word) == 1 and any(g.startswith(word) for g in given):  # an initial
        return "near"
    if any(one_off(word, g) for g in given):
        return "near"
    return None


def find(words, part, near=False):
    """Where a multi-word surname starts in the written words, exactly (or one letter off); None if absent."""
    for i in range(len(words) - len(part) + 1):
        window = words[i:i + len(part)]
        if window == part or near and all(w == p or one_off(w, p) for w, p in zip(window, part)):
            return i
    return None


def compare(name, who):
    """How a written name fits a SERVEL person: {'level', 'why'}."""
    words = tokens(name)
    first, second, given = who["first"], who["second"], who["given"]
    if not words or not first:
        return {"level": "none", "why": "no name"}
    at, near_surname = find(words, first), False
    if at is None:
        at = find(words, first, near=True)
        near_surname = at is not None
    if at is None:
        if second and find(words, second) is not None and any(given_fit(w, given) == "exact" for w in words):
            return {"level": "partial", "why": "the given name and second surname fit, but not the first surname"}
        return {"level": "none", "why": "the first surname isn't there"}
    before, after = words[:at], words[at + len(first):]
    fits = [given_fit(w, given) for w in before]
    if after and second and after[:len(second)] != second and not all(one_off(a, s) for a, s in zip(after, second)):
        return {"level": "partial", "why": f"another second surname ({' '.join(after)}, not {' '.join(second)})"}
    if not before:
        return {"level": "partial", "why": "the surname alone"}
    if "exact" in fits and not near_surname:
        return {"level": "same", "why": "first surname and given name" + (" and second surname" if after else "")}
    if "exact" in fits or "near" in fits:
        how = "a surname one letter off" if near_surname else "a nickname, short form or misspelling of a given name"
        return {"level": "likely", "why": how}
    return {"level": "partial", "why": f"the surname fits but not the given name ({' '.join(before)})"}


def title_case(full):
    """SERVEL's capitals as a name: 'ENRIQUE DEL BARRIO HERNANDEZ' -> 'Enrique del Barrio Hernandez' (accents can't
    be restored from SERVEL's text)."""
    words = str(full or "").title().split()
    return " ".join(w.lower() if i and w.upper() in PARTICLES else w for i, w in enumerate(words))


def same_letters(written, full):
    """Whether a written name has exactly the letters of a SERVEL name, accents and case aside."""
    return fold(written) == fold(full)
