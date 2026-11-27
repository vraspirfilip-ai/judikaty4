"""Společná datová struktura pro rozhodnutí z obou soudů."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime


@dataclass
class Rozhodnuti:
    id: str                      # unikátní klíč, např. "NS:667225CB..." nebo "US:3-2449-26_1"
    soud: str                    # "NS" | "US"
    url: str
    spisova_znacka: str = ""
    ecli: str = ""
    forma: str = ""              # rozsudek / usnesení / nález / stanovisko
    datum_rozhodnuti: str = ""   # ISO YYYY-MM-DD
    datum_zverejneni: str = ""   # ISO YYYY-MM-DD
    kategorie: str = ""          # NS: A–E
    text: str = ""
    extra: dict = field(default_factory=dict)

    def bez_textu(self) -> dict:
        d = asdict(self)
        d.pop("text", None)
        return d


_DATUM_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
_DATUM_US_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_DATUM_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

MESICE = {
    "ledna": 1, "února": 2, "března": 3, "dubna": 4, "května": 5, "června": 6,
    "července": 7, "srpna": 8, "září": 9, "října": 10, "listopadu": 11, "prosince": 12,
}
_DATUM_SLOVNE_RE = re.compile(r"(\d{1,2})\.\s*(" + "|".join(MESICE) + r")\s+(\d{4})")


def datum_iso(text: str) -> str:
    """Převede '12. 8. 2020', '12. srpna 2020', '08/12/2020' nebo ISO na 'YYYY-MM-DD'."""
    if not text:
        return ""
    if m := _DATUM_ISO_RE.search(text):
        return m.group(0)
    if m := _DATUM_RE.search(text):
        d, mth, y = map(int, m.groups())
    elif m := _DATUM_SLOVNE_RE.search(text):
        d, mth, y = int(m.group(1)), MESICE[m.group(2)], int(m.group(3))
    elif m := _DATUM_US_RE.search(text):
        # Lotus Domino obvykle vrací MM/DD/YYYY
        mth, d, y = map(int, m.groups())
        if mth > 12:
            d, mth = mth, d
    else:
        return ""
    try:
        return date(y, mth, d).isoformat()
    except ValueError:
        return ""


def cesky_datum(iso: str) -> str:
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return iso
    return f"{d.day}. {d.month}. {d.year}"
