"""Text normalisation shared by the catalogue side and the listing side.

Marketplace titles are written by hand, in a hurry, for search engines. The
same Mini GT can appear as "MINIGT #745", "Mini-GT MGT00745" or
"TSM 1/64 Cadillac V Series R". Everything here turns that into comparable
tokens and pulls out the structured bits: scale, maker, race numbers, years,
colours, steering side.
"""

from __future__ import annotations

import re
import unicodedata

# --- scale -------------------------------------------------------------------

_SCALE_RE = re.compile(r"(?<![\d.])1\s*[:/\-]\s*(12|18|24|43|64|87)(?!\d)")
_SCALE_WORD_RE = re.compile(r"\b(64|18|43)(?:th)?\s*scale\b")


def scales(text: str) -> set[str]:
    t = text.lower()
    found = {f"1:{m}" for m in _SCALE_RE.findall(t)}
    found |= {f"1:{m}" for m in _SCALE_WORD_RE.findall(t)}
    return found


# --- makers ------------------------------------------------------------------

# Phrase -> canonical maker. Longest phrases are tried first, so "gt spirit"
# wins over the "gt" inside "mini gt". Sub-ranges map to their parent maker.
MAKER_ALIASES: dict[str, str] = {
    "mini gt": "Mini GT", "minigt": "Mini GT", "mini-gt": "Mini GT", "tsm model": "Mini GT",
    "tsm": "Mini GT", "kaido house": "Mini GT", "kaidohouse": "Mini GT",
    "tarmac works": "Tarmac Works", "tarmacworks": "Tarmac Works", "tarmac": "Tarmac Works",
    "global64": "Tarmac Works", "global 64": "Tarmac Works", "hobby64": "Tarmac Works",
    "hobby 64": "Tarmac Works", "road64": "Tarmac Works", "truck64": "Tarmac Works",
    "j collection": "Tarmac Works",
    "pop race": "Pop Race", "poprace": "Pop Race",
    "inno models": "Inno Models", "inno model": "Inno Models", "inno64": "Inno Models",
    "inno 64": "Inno Models", "inno": "Inno Models",
    "gt spirit": "GT Spirit", "gtspirit": "GT Spirit", "gt-spirit": "GT Spirit",
    "otto mobile": "Otto Mobile", "ottomobile": "Otto Mobile", "otto": "Otto Mobile",
    "bm creations": "BM Creations", "bmcreations": "BM Creations", "bm creation": "BM Creations",
    "minichamps": "Minichamps", "paul's model art": "Minichamps",
    "sparky": "Spark", "spark model": "Spark", "spark": "Spark",
}

# Makers we do not track. Seeing one of these and none of ours means the
# listing is for a different product, however well the casting name matches.
OTHER_MAKERS = (
    "hot wheels", "hotwheels", "matchbox", "tomica", "majorette", "greenlight", "green light",
    "kyosho", "autoart", "auto art", "solido", "maisto", "jada", "m2 machines", "auto world",
    "johnny lightning", "ignition model", "model collect", "focal horizon", "stance hunters",
    "micro turbo", "time micro", "ym model", "cm model", "norev", "bburago", "welly",
    "tomytec", "racing champions", "top speed", "topspeed", "lcd models", "dct",
)

_MAKER_PATTERNS = sorted(MAKER_ALIASES, key=len, reverse=True)


def _phrase_re(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")


_MAKER_RES = [(_phrase_re(p), MAKER_ALIASES[p]) for p in _MAKER_PATTERNS]
_OTHER_RES = [_phrase_re(p) for p in OTHER_MAKERS]


def makers(text: str) -> set[str]:
    t = text.lower()
    found = set()
    for rx, maker in _MAKER_RES:
        if rx.search(t):
            found.add(maker)
            t = rx.sub(" ", t)
    return found


def other_makers(text: str) -> set[str]:
    t = text.lower()
    return {rx.pattern for rx in _OTHER_RES if rx.search(t)}


def strip_makers(text: str) -> str:
    t = text.lower()
    for rx, _ in _MAKER_RES:
        t = rx.sub(" ", t)
    return t


# --- marques -----------------------------------------------------------------

MARQUE_ALIASES: dict[str, str] = {
    "lambo": "lamborghini", "lamborghini": "lamborghini", "porsche": "porsche",
    "merc": "mercedes", "mercedes": "mercedes", "benz": "mercedes", "amg": "mercedes",
    "bmw": "bmw", "nissan": "nissan", "datsun": "datsun", "toyota": "toyota", "honda": "honda",
    "mazda": "mazda", "mitsubishi": "mitsubishi", "fuso": "mitsubishi", "subaru": "subaru",
    "aston": "aston martin", "jaguar": "jaguar", "jag": "jaguar", "lotus": "lotus",
    "mclaren": "mclaren", "pagani": "pagani", "koenigsegg": "koenigsegg", "cadillac": "cadillac",
    "lincoln": "lincoln", "abarth": "abarth", "fiat": "abarth", "vw": "volkswagen",
    "volkswagen": "volkswagen", "land rover": "land rover", "range rover": "land rover",
    "landrover": "land rover", "alphatauri": "alphatauri", "alpha tauri": "alphatauri",
    "ferrari": "ferrari", "ford": "ford", "chevrolet": "chevrolet", "chevy": "chevrolet",
    "dodge": "dodge", "audi": "audi", "acura": "acura", "lexus": "lexus", "bugatti": "bugatti",
    "alfa romeo": "alfa romeo", "volvo": "volvo", "hyundai": "hyundai", "kia": "kia",
    "tesla": "tesla", "rolls royce": "rolls royce", "bentley": "bentley", "maserati": "maserati",
    "mini cooper": "mini", "shelby": "ford", "gmc": "gmc", "jeep": "jeep",
}
_MARQUE_RES = [(_phrase_re(p), m) for p, m in sorted(MARQUE_ALIASES.items(), key=lambda kv: -len(kv[0]))]


def marques(text: str) -> set[str]:
    t = strip_makers(text)
    found = set()
    for rx, m in _MARQUE_RES:
        if rx.search(t):
            found.add(m)
            t = rx.sub(" ", t)
    return found


# --- tokens ------------------------------------------------------------------

COLOURS = {
    "white", "black", "red", "blue", "green", "yellow", "orange", "purple", "pink", "gray",
    "silver", "gold", "brown", "beige", "chrome", "teal", "cyan", "magenta", "bronze",
    "champagne", "maroon", "burgundy", "navy", "violet", "camouflage",
}

# Token-level synonyms, applied to both sides before comparison.
SYNONYMS = {
    "grey": "gray", "wht": "white", "blk": "black", "slv": "silver", "met": "metallic",
    "mtlc": "metallic", "metalic": "metallic", "giallo": "yellow", "bianco": "white",
    "rosso": "red", "nero": "black", "viola": "violet", "camo": "camouflage",
    "lambo": "lamborghini", "merc": "mercedes", "benz": "mercedes", "vw": "volkswagen",
    "colour": "color", "lbwk": "libertywalk", "lb": "libertywalk", "rauh": "rwb",
    "formula1": "f1", "tyre": "tire", "hakosuka": "hakosuka", "jdm": "",
}

# Multi-word phrases folded into single tokens before tokenising.
PHRASES = [
    (r"liberty\s*walk", "libertywalk"),
    (r"lb[\s-]*works", "lbworks"),
    (r"lb[\s-]*super\s*silhouette|super\s*silhouette|lbss", "lbss"),
    (r"rocket\s*bunny", "rocketbunny"),
    (r"formula\s*(?:one|1)", "f1"),
    (r"right\s*hand\s*drive", "rhd"),
    (r"left\s*hand\s*drive", "lhd"),
    (r"james\s*bond", "bond"),
    (r"rauh[\s-]*welt(?:\s*begriff)?", "rwb"),
    (r"(?<![a-z0-9])no\.?\s*(?=\d)", "#"),
]

# Words that carry no identity: listing boilerplate and the store's naming tails.
STOPWORDS = {
    "a", "an", "and", "the", "of", "by", "in", "on", "for", "to", "with", "w", "x", "vs",
    "diecast", "die", "cast", "model", "models", "car", "cars", "scale", "toy", "vehicle",
    "new", "brand", "nib", "nip", "mib", "mint", "sealed", "boxed", "box", "in-box", "rare",
    "htf", "limited", "edition", "le", "series", "special", "version", "ver", "pieces", "pcs",
    "worldwide", "free", "fast", "shipping", "ship", "ships", "us", "usa", "seller", "collectible",
    "collector", "collectors", "authentic", "genuine", "official", "licensed", "release",
    "exclusive", "metallic", "graphics", "designed", "1", "64", "18", "43", "164", "118",
    "blister", "card", "carded", "packaging", "item", "lot", "set", "piece", "movie", "gp",
    "hours",
}

_YEAR_RE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-3]\d)(?!\d)")
_RACE_NO_RE = re.compile(r"#\s*(\d{1,3})(?!\d)")


def fold(text: str) -> str:
    """Lowercase, strip accents, fold phrases, join hyphenated/dotted words."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " and ").replace("’", "'")
    t = _SCALE_RE.sub(" ", t)
    for pattern, repl in PHRASES:
        t = re.sub(pattern, f" {repl} " if repl != "#" else "#", t)
    t = re.sub(r"(?<=[a-z0-9])[-.](?=[a-z0-9])", "", t)  # RX-7 -> rx7, GT-R -> gtr, V-Series.R -> vseriesr
    return t


def tokens(text: str) -> list[str]:
    t = fold(strip_makers(text))
    out = []
    for raw in re.findall(r"#?[a-z0-9']+", t):
        tok = raw.lstrip("#").replace("'", "")
        tok = SYNONYMS.get(tok, tok)
        if tok and tok not in STOPWORDS:
            out.append(tok)
    return out


def joined_ngrams(toks: list[str], n_max: int = 3) -> set[str]:
    """Unigrams plus adjacent tokens glued together, so "rx 7" also yields "rx7"."""
    grams = set(toks)
    for n in range(2, n_max + 1):
        for i in range(len(toks) - n + 1):
            grams.add("".join(toks[i:i + n]))
    return grams


def race_numbers(text: str) -> set[str]:
    t = fold(text)
    return {n.lstrip("0") or "0" for n in _RACE_NO_RE.findall(t)}


def years(text: str) -> set[str]:
    return set(_YEAR_RE.findall(text))


def colours(toks) -> set[str]:
    return {t for t in toks if t in COLOURS}


def steering(text: str) -> set[str]:
    t = fold(text)
    return {s for s in ("rhd", "lhd") if re.search(rf"(?<![a-z]){s}(?![a-z])", t)}


def compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
