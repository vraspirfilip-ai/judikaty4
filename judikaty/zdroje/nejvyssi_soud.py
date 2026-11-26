"""Nejvyšší soud – databáze rozhodnuti.nsoud.cz (Lotus Domino).

Databáze nemá API ani RSS rozhodnutí. Používáme stejné vyhledávací URL, jaké
generuje oficiální formulář (`$$WebSearch1?SearchView&Query=...`), s řazením
od nejnovějších dokumentů. Každé rozhodnutí má stabilní 32místný identifikátor
(UNID) v odkazu `WebSearch/<UNID>?openDocument`, podle kterého poznáme, co už
máme zpracované.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .. import http
from ..model import Rozhodnuti, datum_iso

log = logging.getLogger(__name__)

BASE = "https://rozhodnuti.nsoud.cz/Judikatura/judikatura_ns.nsf"
UNID_RE = re.compile(r"WebSearch/([0-9A-Fa-f]{32})")

# Fulltextový dotaz, který odpovídá prakticky všem rozhodnutím (každé obsahuje
# „Nejvyšší soud“). Řazení SearchOrder=3 = podle data, nejnovější první.
VYCHOZI_DOTAZ = '([ARozhodnutiRT]=("Nejvyšší soud"))'


def url_vyhledavani(dotaz: str, start: int, pocet: int, razeni: int = 3) -> str:
    return (
        f"{BASE}/$$WebSearch1?SearchView&Query={quote(dotaz, safe='')}"
        f"&SearchMax=1000&SearchOrder={razeni}&Start={start}&Count={pocet}&pohled=1"
    )


def url_detailu(unid: str) -> str:
    return f"{BASE}/WebSearch/{unid}?openDocument"


SPZN_RE = re.compile(r"\b(\d{1,2})\s+(?:[A-ZČ][A-Za-zČčŘř]{1,6})\s+\d{1,6}/\d{4}")


def senat_ze_spzn(spzn: str) -> int | None:
    """'21 Cdo 2128/2025' → 21."""
    m = SPZN_RE.search(spzn or "")
    return int(m.group(1)) if m else None


def sestav_dotaz(nastaveni: dict) -> str:
    """Složí fulltextový dotaz: vlastní dotaz (nebo výchozí) + omezení na vybrané senáty.

    Senát je v databázi NS samostatné pole [spzn1] (spisová značka je rozdělena
    na [spzn1] senát, [spzn2] agenda, [spzn3] číslo, …), takže server vrací
    rovnou jen rozhodnutí zvolených senátů a ostatní se vůbec nestahují.
    """
    zaklad = nastaveni.get("dotaz") or VYCHOZI_DOTAZ
    senaty = [int(s) for s in nastaveni.get("senaty", [])]
    if not senaty:
        return zaklad
    omezeni = " OR ".join(f"[spzn1]={s}" for s in senaty)
    return f"({zaklad}) AND ({omezeni})"


def najdi_odkazy(html: str) -> list[tuple[str, str]]:
    """Vrátí [(UNID, spisová značka z výpisu – pokud je vidět)] v pořadí, bez duplicit."""
    soup = BeautifulSoup(html, "lxml")
    videne, vysledek = set(), []
    for a in soup.find_all("a", href=UNID_RE):
        u = UNID_RE.search(a["href"]).group(1).upper()
        if u in videne:
            continue
        videne.add(u)
        radek = a.find_parent("tr") or a.parent
        napoveda = ""
        for kandidat in (a.get_text(" "), radek.get_text(" ") if radek else ""):
            if m := SPZN_RE.search(kandidat):
                napoveda = m.group(0)
                break
        vysledek.append((u, napoveda))
    if not vysledek:  # záloha, kdyby odkazy nebyly v <a href>
        for u in UNID_RE.findall(html):
            u = u.upper()
            if u not in videne:
                videne.add(u)
                vysledek.append((u, ""))
    return vysledek


def najdi_unid(html: str) -> list[str]:
    return [u for u, _ in najdi_odkazy(html)]


def seznam_novych(nastaveni: dict, zname: set[str], limit: int) -> list[tuple[str, str]]:
    """Projde stránky výsledků a vrátí [(UNID, sp. zn. z výpisu)] rozhodnutí, která ještě nemáme."""
    dotaz = sestav_dotaz(nastaveni)
    na_stranku = int(nastaveni.get("na_stranku", 50))
    max_stranek = int(nastaveni.get("max_stranek", 10))
    razeni = int(nastaveni.get("razeni", 3))
    log.info("NS: dotaz %s", dotaz)

    nove: list[tuple[str, str]] = []
    for i in range(max_stranek):
        url = url_vyhledavani(dotaz, i * na_stranku + 1, na_stranku, razeni)
        log.info("NS: stránka výsledků %s", i + 1)
        odkazy = najdi_odkazy(http.get(url).text)
        if not odkazy:
            if i == 0:
                raise RuntimeError(
                    "NS: vyhledávání nevrátilo žádné odkazy na rozhodnutí – "
                    "možná se změnila struktura webu, nebo zvolené senáty nic nemají. URL: " + url
                )
            break
        uz = {u for u, _ in nove}
        cerstve = [(u, s) for u, s in odkazy if f"NS:{u}" not in zname and u not in uz]
        nove.extend(cerstve)
        if not cerstve or len(nove) >= limit * 5:
            # celá stránka už je známá → dál jsou jen starší rozhodnutí
            break
    return nove


_POLE = {
    "spisova_znacka": r"Spisová\s+značka\s*:?\s*\n?\s*([^\n]{3,60})",
    "ecli": r"(ECLI:CZ:NS:\d{4}:[0-9A-Z.]+)",
    "datum_rozhodnuti": r"Datum\s+rozhodnutí\s*:?\s*\n?\s*([^\n]{6,30})",
    "datum_zverejneni": r"Datum\s+zveřejnění\s*:?\s*\n?\s*([^\n]{6,30})",
    "kategorie": r"Kategorie\s+rozhodnutí\s*:?\s*\n?\s*([A-E])\b",
    "forma": r"Typ\s+rozhodnutí\s*:?\s*\n?\s*([^\n]{3,30})",
    "heslo": r"Heslo\s*:?\s*\n?\s*([^\n]{3,300})",
    "dotcene_predpisy": r"Dotčené\s+předpisy\s*:?\s*\n?\s*([^\n]{3,400})",
    "oficialni_pravni_veta": r"Právní\s+věta\s*:?\s*\n?\s*([^\n]{20,3000})",
}


def zpracuj_detail(unid: str, html: str) -> Rozhodnuti:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()

    hodnoty: dict[str, str] = {}
    for klic, vzor in _POLE.items():
        m = re.search(vzor, text, re.IGNORECASE)
        if m:
            hodnoty[klic] = m.group(1).strip()

    r = Rozhodnuti(id=f"NS:{unid}", soud="NS", url=url_detailu(unid))
    r.ecli = hodnoty.get("ecli", "")
    r.spisova_znacka = hodnoty.get("spisova_znacka", "") or _spzn_z_ecli(r.ecli) or _spzn_z_textu(text)
    r.datum_rozhodnuti = datum_iso(hodnoty.get("datum_rozhodnuti", ""))
    r.datum_zverejneni = datum_iso(hodnoty.get("datum_zverejneni", ""))
    r.kategorie = hodnoty.get("kategorie", "").upper()
    forma = hodnoty.get("forma", "")
    if not forma:
        m = re.search(r"\b(ROZSUDEK|USNESENÍ|STANOVISKO)\b", text)
        forma = m.group(1) if m else ""
    r.forma = forma.lower()
    r.extra = {k: hodnoty[k] for k in ("heslo", "dotcene_predpisy", "oficialni_pravni_veta") if k in hodnoty}

    # Text rozhodnutí začíná typicky „ČESKÁ REPUBLIKA“ / „ROZSUDEK“ / „USNESENÍ“.
    # Metadata (např. „Typ rozhodnutí: USNESENÍ“) přeskočíme.
    m = re.search(r"ČESKÁ\s+REPUBLIKA", text)
    if not m:
        konec_meta = max((x.end() for x in re.finditer(r"Datum\s+zveřejnění|Kategorie\s+rozhodnutí", text)), default=0)
        m = re.compile(r"\b(ROZSUDEK|USNESENÍ|STANOVISKO)\b").search(text, konec_meta)
    r.text = text[m.start():] if m and m.start() < len(text) * 0.7 else text
    return r


_AGENDY = {"CDO": "Cdo", "TDO": "Tdo", "ICDO": "ICdo", "NSCR": "NSČR", "CDON": "Cdon",
           "TZ": "Tz", "TCU": "Tcu", "TVO": "Tvo", "TT": "Tt", "CPJN": "Cpjn",
           "CMPJN": "Cmpjn", "TPJN": "Tpjn", "CZN": "Czn", "SE": "Se", "NCU": "Ncu",
           "NCD": "Ncd", "CUL": "Cul", "TZN": "Tzn"}


def _spzn_z_ecli(ecli: str) -> str:
    # ECLI:CZ:NS:2026:21.CDO.2128.2025.1 → 21 Cdo 2128/2025
    m = re.match(r"ECLI:CZ:NS:\d{4}:(\d+)\.([A-Z]+)\.(\d+)\.(\d{4})", ecli or "")
    if not m:
        return ""
    senat, agenda, cislo, rok = m.groups()
    return f"{senat} {_AGENDY.get(agenda, agenda.capitalize())} {cislo}/{rok}"


def _spzn_z_textu(text: str) -> str:
    m = re.search(r"\b(\d{1,2}\s+[A-ZČ][A-Za-zČč]{1,5}\s+\d{1,5}/\d{4})", text)
    return m.group(1) if m else ""


def stahni(unid: str) -> Rozhodnuti:
    return zpracuj_detail(unid, http.get(url_detailu(unid)).text)
