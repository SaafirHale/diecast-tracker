"""Match a messy marketplace listing title to one catalogue model, or refuse.

The matcher is deliberately conservative. A wrong match poisons the price
history for a model (a $9 loose Hot Wheels counted as a $25 Mini GT drags the
median and fires false "deal" alerts), while a missed match only costs one
data point. So it returns one of:

  matched    one model, confident, and the listing is a comparable item
  rejected   it is (probably) that model, but not comparable: a lot, loose,
             a chase car, damaged, a custom, an empty box...
  ambiguous  two or more models fit about equally (same casting, colour not
             stated); kept for review, never counted
  no_match   nothing in the catalogue fits

Signals, strongest first:
  1. Item number (MGT00745, T64G-TL021-WH, OT1173...). Sellers who type it
     are usually right, so an item-number hit is near-certain.
  2. Hard gates: a stated scale, maker or marque that differs from the
     model's rules the model out outright.
  3. Token overlap weighted by rarity across the catalogue (IDF), so "Zonda"
     counts for far more than "RHD" or "Pandem".
  4. Conflicts: a colour, race number, year or steering side in the listing
     that the model does not have.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from . import normalize as N
from .catalogue import Model

MATCH_THRESHOLD = 0.62    # minimum confidence to call it a match
AMBIGUITY_MARGIN = 0.12   # best must beat runner-up by this much
REVIEW_FLOOR = 0.25       # below this, report no_match rather than ambiguous
FOREIGN_WEIGHT = 2.5      # idf above which a stray listing word counts as evidence
BUDGET_TOKENS = 5         # recall is judged against this many of a model's rarest tokens

# Flags that make a listing not comparable with a sealed, single, genuine model.
EXCLUDING_FLAGS = {"lot", "loose", "damaged", "custom", "not_a_model", "not_genuine", "chase", "signed"}

_FLAG_PATTERNS: dict[str, str] = {
    "lot": r"\blots?\b|\bbundle\b|\bset of \d+|\b[2-9] ?x\b|\bx ?[2-9]\s*$|\b\d+ (?:cars|pcs|pieces|models)\b|\bcollection of\b|\bbulk\b|\b(?:master )?case of\b",
    "loose": r"\bloose\b|\bno box\b|\bwithout (?:the )?box\b|\bunboxed\b|\bout of (?:the )?box\b|\boob\b|\bopened\b|\bno packaging\b",
    "damaged": r"\bdamaged?\b|\bbroken\b|\bmissing\b|\bas[- ]is\b|\bfor parts\b|\bcrushed\b|\bcracked\b|\bscratche[sd]\b|\bchipped\b",
    "box_damage": r"\b(?:box|blister|card|packaging) (?:damage|damaged|wear|dent|dented|crease|creased|soft)\b|\b(?:dented|creased|soft|worn) (?:box|blister|card|corners?)\b|\bimperfect (?:box|package)\b",
    "custom": r"\bcustom(?:i[sz]ed)?\b|\bmodified\b|\brepaint(?:ed)?\b|\bwheel swap(?:ped)?\b|\bkitbash\w*",
    "chase": r"\bchase\b|\bsuper ?chase\b",
    "not_a_model": r"\bbox only\b|\bempty box\b|\bwheels only\b|\bdecals?\b|\bkeychain\b|\bsticker\b|\bblister only\b|\bcard only\b|\bdisplay case\b|\bacrylic case\b|\bbox protectors?\b|\bpro[- ]?tech\b|\bposter\b|\bcatalog(?:ue)?\b|\bpin\b|\bt-?shirt\b",
    "not_genuine": r"\b3d[- ]?print(?:ed)?\b|\breplica\b|\bfake\b|\bbootleg\b|\bknock[- ]?off\b|\bproxy\b",
    "signed": r"\bsigned\b|\bautograph(?:ed)?\b",
    "preorder": r"\bpre[- ]?orders?\b|\bcoming soon\b|\bpresale\b|\bpre[- ]?sale\b",
}
_FLAG_RES = {k: re.compile(v) for k, v in _FLAG_PATTERNS.items()}


def detect_flags(title: str) -> dict[str, str]:
    """flag -> the text that triggered it."""
    t = title.lower()
    out = {}
    box = _FLAG_RES["box_damage"].search(t)
    if box:
        out["box_damage"] = box.group(0)
        t = t[:box.start()] + " " + t[box.end():]   # "box damaged" says nothing about the car
    for flag, rx in _FLAG_RES.items():
        m = rx.search(t)
        if m and flag not in out:
            out[flag] = m.group(0)
    return out


@dataclass
class Candidate:
    model: Model
    score: float
    how: str            # "item_number" | "fuzzy"
    reasons: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # hard: a different variant


@dataclass
class MatchResult:
    status: str                      # matched | rejected | ambiguous | no_match
    model: Model | None = None
    confidence: float = 0.0
    how: str = ""
    flags: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    candidates: list[tuple[str, float]] = field(default_factory=list)  # for review

    @property
    def model_id(self) -> str | None:
        return self.model.id if self.model else None

    @property
    def comparable(self) -> bool:
        """Counts towards market price stats."""
        return self.status == "matched" and "box_damage" not in self.flags


class _Indexed:
    """Per-model features precomputed once."""

    def __init__(self, m: Model):
        text = " ".join([m.name, *m.aliases])
        self.model = m
        self.tokens = list(dict.fromkeys(N.tokens(m.name)))  # ordered, unique
        self.all_tokens = set(N.tokens(text))
        self.colours = N.colours(self.all_tokens)
        self.race_numbers = N.race_numbers(text)
        self.years = N.years(text)
        self.steering = N.steering(text)
        self.marques = N.marques(text) | N.marques(m.marque)
        self.name_lower = text.lower()
        self.item_keys = _item_number_keys(m)


def _item_number_keys(m: Model) -> set[str]:
    """Compact spellings of the maker's item number a seller might type."""
    sku = N.compact(m.sku)
    keys = {sku}
    base = re.sub(r"(007e)$", "", sku)          # Mini GT's 007 suffix is often dropped
    keys.add(base)
    mm = re.fullmatch(r"(mgt|khmg|ot|gt|pr)(\d+)(.*)", base)
    if mm:
        prefix, digits, tail = mm.groups()
        n = int(digits)
        for width in (0, 3, 4, 5, 6):
            keys.add(f"{prefix}{n:0{width}d}{tail}")
    parts = re.split(r"[^A-Za-z0-9]+", m.sku.lower())
    if len(parts) >= 3:                          # T64G-TL021-WH -> also "tl021wh"
        keys.add("".join(parts[1:]))
    return {k for k in keys if len(k) >= 5}


def _weak_number(m: Model) -> str | None:
    """Mini GT box number sellers write as "#745" or "No. 745"."""
    mm = re.fullmatch(r"(?:MGT|KHMG)0*(\d+).*", m.sku.upper())
    return mm.group(1) if mm else None


class Matcher:
    def __init__(self, models: list[Model]):
        self.index = [_Indexed(m) for m in models]
        df = Counter(t for ix in self.index for t in set(ix.tokens))
        n = len(self.index)
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
        self.default_idf = math.log(1 + n)

    def weight(self, tok: str) -> float:
        w = self.idf.get(tok, self.default_idf)
        if tok.isdigit() and len(tok) <= 2:
            w *= 0.5                              # bare small numbers are weak evidence
        return w

    # -- public -------------------------------------------------------------

    def match(self, title: str) -> MatchResult:
        flags = detect_flags(title)
        l_scales = N.scales(title)
        l_makers = N.makers(title)
        l_others = N.other_makers(title)
        l_marques = N.marques(title)
        l_toks = N.tokens(title)
        l_grams = N.joined_ngrams(l_toks)
        l_compact_grams = N.joined_ngrams(re.findall(r"[a-z0-9]+", N.fold(title)), 4)
        l_colours = N.colours(l_toks)
        l_numbers = N.race_numbers(title)
        l_years = N.years(title)
        l_steer = N.steering(title)

        if l_others and not l_makers:
            return MatchResult("no_match", flags=flags,
                               reasons=[f"listing names another maker ({', '.join(sorted(l_others))})"])

        cands: list[Candidate] = []
        for ix in self.index:
            m = ix.model
            reasons, conflicts = [], []
            # Hard gates.
            if l_scales and m.scale not in l_scales:
                continue
            if l_makers and m.maker not in l_makers:
                continue
            if l_marques and ix.marques and not (l_marques & ix.marques):
                continue

            weak = _weak_number(m)
            hit = ix.item_keys & l_compact_grams
            if hit:
                score, how = 0.97, "item_number"
                reasons.append(f"item number {sorted(hit)[0].upper()}")
            else:
                how = "fuzzy"
                matched = [t for t in ix.tokens if t in l_grams]
                weights = sorted((self.weight(t) for t in ix.tokens), reverse=True)
                # Titles are capped at ~80 chars, so judge recall against the
                # model's most distinctive tokens, not its whole long name.
                budget = sum(weights[:BUDGET_TOKENS]) or 1.0
                score = min(1.0, sum(self.weight(t) for t in matched) / budget)
                if not any(self.weight(t) >= 2.0 for t in matched):
                    score *= 0.5                  # nothing distinctive matched
                reasons.append(f"tokens {matched}")
                # Words that are rare in the catalogue but absent from this
                # model point at a sibling ("Skyfall" vs "Thunderball").
                foreign = [t for t in l_toks if t in self.idf and t not in ix.all_tokens
                           and self.weight(t) >= FOREIGN_WEIGHT]
                if foreign:
                    score *= 0.85 ** min(len(set(foreign)), 3)
                    reasons.append(f"other-model words {sorted(set(foreign))}")
                if weak and weak in l_numbers and m.maker in l_makers:
                    score = min(1.0, score + 0.25)
                    reasons.append(f"box number #{weak}")

            # Hard conflicts: the listing states an attribute this model does
            # not have, so it is most likely a sibling variant we do not stock.
            stray_numbers = l_numbers - ix.race_numbers - ({weak} if weak else set())
            if ix.race_numbers and stray_numbers:
                conflicts.append(f"race number {sorted(stray_numbers)} vs {sorted(ix.race_numbers)}")
            if ix.colours and l_colours and not (l_colours & ix.colours):
                conflicts.append(f"colour {sorted(l_colours)} vs {sorted(ix.colours)}")
            if ix.steering and l_steer and not (l_steer & ix.steering):
                conflicts.append(f"steering {sorted(l_steer)} vs {sorted(ix.steering)}")
            # Soft conflicts: plausible seller noise.
            if ix.colours and l_colours - ix.colours and l_colours & ix.colours:
                score *= 0.92
            if ix.years and l_years and not (l_years & ix.years):
                score *= 0.6
                reasons.append(f"year {sorted(l_years)} vs {sorted(ix.years)}")

            # Missing context lowers confidence a little.
            if not l_makers:
                score *= 0.88
            if not l_scales:
                score *= 0.96
            cands.append(Candidate(m, max(0.0, min(1.0, score)), how, reasons, conflicts))

        cands.sort(key=lambda c: c.score, reverse=True)
        top = [(c.model.id, round(c.score, 3)) for c in cands[:3]]
        # An item number that contradicts the title is for a human to look at.
        contradicted = [c for c in cands if c.how == "item_number" and c.conflicts]
        viable = [c for c in cands if not c.conflicts]
        ours = bool(l_makers) or bool(viable and viable[0].score >= REVIEW_FLOOR)

        if contradicted and not any(c.how == "item_number" for c in viable):
            c = contradicted[0]
            return MatchResult("ambiguous", model=c.model, confidence=round(c.score, 3), how=c.how,
                               flags=flags, reasons=c.reasons + c.conflicts, candidates=top)

        if not viable or viable[0].score < REVIEW_FLOOR:
            excluding = sorted(set(flags) & EXCLUDING_FLAGS)
            if excluding and ours:
                return MatchResult("rejected", flags=flags, candidates=top,
                                   reasons=[f"not comparable: {', '.join(excluding)}"])
            closest = cands[0] if cands else None
            why = ["no catalogue model fits"]
            if closest and closest.conflicts:
                why = [f"closest is {closest.model.id} but {'; '.join(closest.conflicts)}"]
            return MatchResult("no_match", flags=flags, candidates=top, reasons=why)

        best = viable[0]
        runner = viable[1].score if len(viable) > 1 else 0.0

        # A flag word that is part of the model's own name ("Birch Silver
        # Metallic (Damaged)") describes the model, not the listing.
        own_name = self._index_of(best.model).name_lower
        flags = {f: trig for f, trig in flags.items() if trig not in own_name}
        excluding = sorted(set(flags) & EXCLUDING_FLAGS)

        if best.score < MATCH_THRESHOLD or best.score - runner < AMBIGUITY_MARGIN:
            # Not sure which model, but sure it is not comparable: say so.
            if excluding:
                return MatchResult("rejected", confidence=round(best.score, 3), flags=flags,
                                   reasons=[f"not comparable: {', '.join(excluding)}"], candidates=top)
            return MatchResult("ambiguous", model=best.model, confidence=round(best.score, 3),
                               how=best.how, flags=flags, reasons=best.reasons, candidates=top)
        status = "rejected" if excluding else "matched"
        reasons = best.reasons + ([f"not comparable: {', '.join(excluding)}"] if excluding else [])
        return MatchResult(status, model=best.model, confidence=round(best.score, 3), how=best.how,
                           flags=flags, reasons=reasons, candidates=top)

    def _index_of(self, model: Model) -> _Indexed:
        return next(ix for ix in self.index if ix.model is model)
