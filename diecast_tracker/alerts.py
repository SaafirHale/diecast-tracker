"""Alert rules: when is a listing worth a look?

below_median   landed price (item + shipping) is at least `pct_below` under
               the recent median for that model. The reference is the sold
               median when there are enough sales in the window, else the
               asking median. The listing itself is excluded from its own
               reference.
restock_margin landed price leaves at least `margin` of the store's own
               selling price as gross margin, so it can be bought to restock.

Guards: only comparable, confidently matched listings in the right currency;
at least `min_samples` reference points; and a price far below the median
is still alerted but tagged "check seller", because that is where scams and
mislabelled listings live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import db, stats


@dataclass
class AlertRules:
    pct_below: float = 0.20        # 20% under the reference median
    min_samples: int = 5
    window_days: int = 90
    min_confidence: float = 0.75
    suspicious_below: float = 0.50  # under half the median: tag it
    margin: float | None = 0.35     # restock rule; None turns it off
    kinds: tuple[str, ...] = ("ask",)


@dataclass
class Alert:
    rule: str
    landed: float
    reference: float | None
    reference_kind: str | None
    n_reference: int
    pct_below: float | None
    note: str = ""


def reference_for(conn, model_id: str, rules: AlertRules, at, exclude_id=None):
    since = at - timedelta(days=rules.window_days)
    for kind in ("sold", "ask"):
        s = stats.summarise(db.landed_prices(conn, model_id, kind, since, exclude_id))
        if s and s.n >= rules.min_samples:
            return kind, s
    return None, None


def evaluate(conn, obs: dict, store_price: float | None, rules: AlertRules, at) -> list[Alert]:
    if obs["kind"] not in rules.kinds or not obs.get("comparable"):
        return []
    if (obs.get("confidence") or 0) < rules.min_confidence or obs.get("currency", "USD") != "USD":
        return []
    landed = obs["price"] + (obs.get("shipping") or 0.0)
    out = []

    kind, ref = reference_for(conn, obs["model_id"], rules, at, exclude_id=obs.get("id"))
    if ref:
        below = 1 - landed / ref.median
        if below >= rules.pct_below:
            note = "far under median: check seller and photos" if landed < ref.median * rules.suspicious_below else ""
            out.append(Alert("below_median", landed, ref.median, kind, ref.n, round(below, 3), note))

    if rules.margin is not None and store_price:
        ceiling = store_price * (1 - rules.margin)
        if landed <= ceiling:
            out.append(Alert("restock_margin", landed, store_price, "store", 0,
                             round(1 - landed / store_price, 3),
                             f"buy at or under ${ceiling:.2f} keeps {rules.margin:.0%} margin"))
    return out


def save(conn, observation_id: int, model_id: str, alerts: list[Alert], at) -> int:
    n = 0
    for a in alerts:
        cur = conn.execute(
            """INSERT OR IGNORE INTO alerts (observation_id, model_id, rule, landed, reference,
                 reference_kind, n_reference, pct_below, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (observation_id, model_id, a.rule, a.landed, a.reference, a.reference_kind,
             a.n_reference, a.pct_below, a.note, db.iso(at)),
        )
        n += cur.rowcount
    return n
