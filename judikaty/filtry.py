"""Vyřazení nechtěných právních oblastí ještě PŘED rozborem (nic to nestojí).

Senáty NS nemají čistou specializaci (jeden senát řeší např. pracovní spory
i obecné civilní věci), proto se oblast pozná z obsahu rozhodnutí:
- z metadat NS (Heslo, Dotčené předpisy – např. „předpisu č. 262/2006 Sb.“),
- ze záhlaví a výroku rozhodnutí (úvod textu až po „takto:“), kde je uveden
  předmět řízení („o neplatnost výpovědi z pracovního poměru“, „o pozůstalosti
  po zůstaviteli…“, „o vydání nemovitostí“).
Odůvodnění se záměrně neprohledává – zmínka o zaměstnavateli nebo dědici
v odůvodnění ještě neznamená, že jde o pracovní či dědický spor.
"""
from __future__ import annotations

import re

from .model import Rozhodnuti

OBLASTI: dict[str, dict] = {
    "pracovni": {
        "nazev": "pracovní právo",
        "vzory": [
            r"pracovní(ho|m|mu)?\s+poměr", r"zákoník\w*\s+práce", r"262\s*/\s*2006", r"65\s*/\s*1965",
            r"výpověď\w*\s+z\s+pracovního", r"zrušení\s+pracovního", r"rozvázání\s+pracovního",
            r"\bodstupné", r"náhrad\w+\s+mzdy", r"\bmzd[yaě]\b", r"pracovní\w*\s+úraz",
            r"nemoc\w*\s+z\s+povolání", r"dohod\w*\s+o\s+(provedení\s+práce|pracovní\s+činnosti)",
            r"\bzaměstnan(ec|ce|kyně)\b.{0,80}\bzaměstnavatel", r"\bzaměstnavatel\w*\b.{0,80}\bzaměstnan",
        ],
    },
    "dedicke": {
        "nazev": "dědické právo",
        "vzory": [
            # pozor: samotné „dědic“ nestačí – objevuje se i při úmrtí účastníka běžného sporu
            r"pozůstalost", r"dědictv", r"\bzávěť", r"neopomenuteln", r"povinn\w+\s+díl",
            r"dědick\w+\s+(řízení|nápad|titul|podíl|práv|spor)",
        ],
    },
    "restituce": {
        "nazev": "restituce",
        "vzory": [
            r"restitu", r"229\s*/\s*1991", r"87\s*/\s*1991", r"428\s*/\s*2012", r"243\s*/\s*1992",
            r"403\s*/\s*1990", r"119\s*/\s*1990", r"náhradní\w*\s+pozem", r"pozemkov\w+\s+fond",
            r"státní\w*\s+pozemkov\w+\s+úřad", r"oprávněn\w+\s+osob\w+\s+podle",
            # „o vydání věci“ je běžná vlastnická žaloba, proto jen nemovitosti/pozemky
            r"vydání\s+(nemovit|pozemk|zemědělsk)",
            r"majetkov\w+\s+vyrovnání\s+s\s+církv", r"mimosoudní\s+rehabilitac", r"soudní\s+rehabilitac",
        ],
    },
}


def zahlavi(text: str) -> str:
    """Úvod rozhodnutí: záhlaví (účastníci, předmět řízení) a výrok – po slovo „takto“."""
    zacatek = text[:8000]
    oduvodneni = re.search(r"\n\s*(Odůvodnění|Stručné\s+odůvodnění)", zacatek)
    if oduvodneni:
        return zacatek[: oduvodneni.start()]
    konec = re.search(r"\btakto\s*:", zacatek, re.IGNORECASE)
    return zacatek[: konec.end() + 600] if konec else zacatek[:3000]


def vyrazujici_oblast(r: Rozhodnuti, oblasti: list[str], vlastni_vzory: list[str] | None = None) -> str | None:
    """Vrátí název oblasti, kvůli které se má rozhodnutí vyřadit, jinak None."""
    if not oblasti and not vlastni_vzory:
        return None
    meta = " ".join(str(r.extra.get(k, "")) for k in ("heslo", "dotcene_predpisy"))
    kde = (meta + "\n" + zahlavi(r.text)).lower()
    for klic in oblasti:
        definice = OBLASTI.get(klic)
        if not definice:
            raise ValueError(f"Neznámá oblast k vyřazení: {klic!r}. Možnosti: {', '.join(OBLASTI)}")
        for vzor in definice["vzory"]:
            if re.search(vzor, kde, re.IGNORECASE | re.DOTALL):
                return definice["nazev"]
    for vzor in vlastni_vzory or []:
        if re.search(vzor, kde, re.IGNORECASE | re.DOTALL):
            return f"vlastní vzor „{vzor}“"
    return None
