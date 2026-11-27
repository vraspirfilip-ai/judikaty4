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
    "rodinne": {
        "nazev": "rodinné právo",
        "vzory": [
            r"rozvod", r"rozluk", r"výživn\w*", r"péč\w+\s+o\s+(nezletil|dít)", r"úprav\w+\s+poměrů",
            r"styk\w*\s+s\s+(nezletil|dít)", r"\bnezletil\w*\b.{0,60}\bpéč", r"otcovstv", r"mateřstv",
            r"osvojen", r"pěstounsk", r"svěřen\w*\s+(nezletil|dít|do\s+péče)", r"poručnick",
            r"neúplně\s+svéprávn\w+.{0,40}nezletil",
            r"(zákon\w*\s+o\s+rodině|94\s*/\s*1963)", r"manželstv\w+\s+(se\s+rozvádí|neplatn|zdánliv)",
        ],
    },
    "sjm": {
        "nazev": "společné jmění manželů",
        "vzory": [r"společn\w+\s+jmění", r"\bSJM\b", r"vypořádání\s+společného", r"bezpodílov\w+\s+spoluvlastn"],
    },
    "exekuce": {
        "nazev": "exekuce a výkon rozhodnutí",
        "vzory": [r"exekuc", r"exekutor", r"exekuční", r"120\s*/\s*2001", r"výkon\w*\s+rozhodnutí",
                  r"soudní\w*\s+exekutor", r"vylouč\w+\s+(věci\s+)?z\s+(exekuce|soupisu|výkonu)",
                  r"excindační", r"dražb\w*.{0,40}(exekuc|výkon)", r"zastavení\s+(exekuce|výkonu)"],
    },
    "soudni_uschovy": {
        "nazev": "soudní úschovy",
        "vzory": [r"soudní\w*\s+úschov", r"\búschovní\w*\s+(řízení|věc)", r"do\s+(soudní\s+)?úschovy",
                  r"předmět\w*\s+(soudní\s+)?úschovy", r"z\s+(soudní\s+)?úschovy"],
    },
    "nekala_soutez": {
        "nazev": "nekalá soutěž",
        "vzory": [r"nekal\w+\s+soutěž", r"§\s*29(7[6-9]|8[0-9]|9[0-9])\b", r"klamav\w+\s+reklam",
                  r"parazitován\w*\s+na\s+pověsti", r"nebezpečí\s+záměny", r"srovnávací\s+reklam"],
    },
    "arbitraze": {
        "nazev": "rozhodčí řízení",
        "vzory": [r"rozhodčí\w*\s+(nález|doložk|smlouv|řízen|soud|senát)", r"\brozhodc\w*", r"arbitráž",
                  r"216\s*/\s*1994", r"zrušení\s+rozhodčího"],
    },
    "dusevni_vlastnictvi": {
        "nazev": "duševní vlastnictví",
        "vzory": [r"autorsk\w+\s+(práv|zákon|díl|odměn)", r"121\s*/\s*2000", r"ochrann\w+\s+znám[kc]",
                  r"441\s*/\s*2003", r"\bpatent", r"průmyslov\w+\s+(vzor|vlastnictv|práv)", r"užitn\w+\s+vzor",
                  r"licenční\w*\s+smlouv", r"kolektivní\w*\s+správ", r"\b(OSA|DILIA|INTERGRAM|OAZA)\b",
                  r"doménov\w+\s+jmén", r"označení\s+původu", r"zeměpisn\w+\s+označen"],
    },
}

# Volnější názvy v nastavení („rodinné věci“, „pracovněprávní spory“ …) → klíč oblasti
ALIASY = {
    "pracovni": "pracovni", "pracovnepravni": "pracovni", "pracovne": "pracovni", "prace": "pracovni",
    "dedicke": "dedicke", "dedictvi": "dedicke", "dedicky": "dedicke", "pozustalost": "dedicke",
    "restituce": "restituce", "restitucni": "restituce",
    "rodinne": "rodinne", "rodina": "rodinne", "rodinny": "rodinne", "opatrovnicke": "rodinne",
    "sjm": "sjm", "spolecnejmenimanzelu": "sjm", "vyporadanisjm": "sjm",
    "exekuce": "exekuce", "exekuci": "exekuce", "exekucni": "exekuce", "vykonrozhodnuti": "exekuce",
    "exekuceavykonrozhodnuti": "exekuce",
        "soudniuschovy": "soudni_uschovy", "uschovy": "soudni_uschovy", "uschova": "soudni_uschovy",
    "soudniuschova": "soudni_uschovy",
    "nekalasoutez": "nekala_soutez", "nekalesouteze": "nekala_soutez", "nekalesoutez": "nekala_soutez",
    "arbitraze": "arbitraze", "arbitraz": "arbitraze", "rozhodcirizeni": "arbitraze", "rozhodci": "arbitraze",
    "dusevnivlastnictvi": "dusevni_vlastnictvi", "dusevni": "dusevni_vlastnictvi",
    "autorske": "dusevni_vlastnictvi", "autorskeprava": "dusevni_vlastnictvi",
    "ochranneznamky": "dusevni_vlastnictvi", "prumyslovevlastnictvi": "dusevni_vlastnictvi",
}
_VYPLN = re.compile(r"(veci|vec|pravo|pravni|spory|spor|agenda|oblast)")


def normalizuj_oblast(nazev: str) -> str:
    """'rodinne veci' / 'Rodinné právo' / 'pracovněprávní spory' → klíč z OBLASTI."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(nazev)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z]", "", t)
    if t in ALIASY:
        return ALIASY[t]
    t = _VYPLN.sub("", t)
    if t in ALIASY:
        return ALIASY[t]
    raise ValueError(
        f"Neznámá oblast k vyřazení: {nazev!r}. Možnosti: "
        + ", ".join(f'"{k}" ({v["nazev"]})' for k, v in OBLASTI.items())
        + ". Jiné výrazy lze zadat do vyloucit.vlastni_vzory."
    )


def zkontroluj(oblasti: list[str]) -> list[str]:
    return [normalizuj_oblast(o) for o in oblasti]


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
    for klic in zkontroluj(oblasti):
        definice = OBLASTI[klic]
        for vzor in definice["vzory"]:
            if re.search(vzor, kde, re.IGNORECASE | re.DOTALL):
                return definice["nazev"]
    for vzor in vlastni_vzory or []:
        if re.search(vzor, kde, re.IGNORECASE | re.DOTALL):
            return f"vlastní vzor „{vzor}“"
    return None
