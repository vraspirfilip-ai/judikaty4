"""Ústavní soud – RSS usoud.cz + plné texty z databáze NALUS.

NALUS je ASP.NET formulář bez API. Ústavní soud ale každý den publikuje
v RSS (https://www.usoud.cz/rss) tiskové zprávy a týdenní „Souhrny vyhlášených
nálezů“ s přímými odkazy na NALUS ve tvaru
`https://nalus.usoud.cz/Search/GetText.aspx?sz=3-2449-26_1`.
Z nich bereme identifikátory a stahujeme plné texty.

Pokrývá tedy všechny nálezy (ty ÚS shrnuje každý týden) a usnesení,
o kterých vydal tiskovou zprávu. Běžná odmítací usnesení se nestahují.
"""
from __future__ import annotations

import email.utils
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .. import http
from ..model import Rozhodnuti, datum_iso

log = logging.getLogger(__name__)

RSS_URL = "https://www.usoud.cz/rss"
NALUS_TEXT = "https://nalus.usoud.cz/Search/GetText.aspx?sz={sz}"
SZ_RE = re.compile(r"nalus\.usoud\.cz(?::443)?/Search/GetText\.aspx\?sz=([A-Za-z0-9]+-\d+-\d+(?:_\d+)?)", re.I)
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
ZAJIMAVE_KATEGORIE = {"rozhodnuti", "tiskova_zprava"}


def sz_na_spzn(sz: str) -> str:
    """'3-2449-26_1' → 'III. ÚS 2449/26', 'Pl-24-10_1' → 'Pl. ÚS 24/10'."""
    zaklad = sz.split("_")[0]
    casti = zaklad.split("-")
    if len(casti) != 3:
        return sz
    senat, cislo, rok = casti
    rimske = {"1": "I.", "2": "II.", "3": "III.", "4": "IV."}
    oznaceni = "Pl." if senat.lower() == "pl" else rimske.get(senat, senat + ".")
    return f"{oznaceni} ÚS {cislo}/{rok}"


def nacti_rss(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    polozky = []
    for item in root.iter("item"):
        pub = item.findtext("pubDate") or ""
        try:
            dt = email.utils.parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            dt = None
        polozky.append({
            "titulek": (item.findtext("title") or "").strip(),
            "odkaz": (item.findtext("link") or "").strip(),
            "datum": dt,
            "kategorie": {(c.text or "").strip() for c in item.findall("category")},
            "obsah": (item.findtext(CONTENT_NS) or "") + (item.findtext("description") or ""),
        })
    return polozky


def najdi_sz(text: str) -> list[str]:
    videne, out = set(), []
    for sz in SZ_RE.findall(text or ""):
        if "_" not in sz:
            sz += "_1"
        if sz not in videne:
            videne.add(sz)
            out.append(sz)
    return out


def seznam_novych(nastaveni: dict, zname: set[str], limit: int) -> list[tuple[str, dict]]:
    """Vrátí [(sz, kontext)] nových rozhodnutí odkazovaných z RSS."""
    max_stari = int(nastaveni.get("max_stari_dni", 14))
    hranice = datetime.now(timezone.utc) - timedelta(days=max_stari)
    if nastaveni.get("od"):  # první běh od zvoleného data
        hranice = datetime.fromisoformat(nastaveni["od"]).replace(tzinfo=ZoneInfo("Europe/Prague"))
    polozky = nacti_rss(http.get(RSS_URL).content)
    if not polozky:
        raise RuntimeError("ÚS: RSS neobsahuje žádné položky – možná se změnil formát.")

    vysledek: list[tuple[str, dict]] = []
    videne: set[str] = set()
    for p in polozky:
        if p["datum"] and p["datum"] < hranice:
            continue
        sz_list = najdi_sz(p["obsah"])
        relevantni = (
            p["kategorie"] & ZAJIMAVE_KATEGORIE
            or re.search(r"nález|usnesení|souhrn", p["titulek"], re.I)
        )
        if not sz_list and relevantni and p["odkaz"]:
            # obsah v RSS může být zkrácený → stáhneme celý článek
            try:
                sz_list = najdi_sz(http.get(p["odkaz"]).text)
            except Exception as e:  # noqa: BLE001
                log.warning("ÚS: nelze načíst článek %s: %s", p["odkaz"], e)
        kontext = {"zdroj_titulek": p["titulek"], "zdroj_odkaz": p["odkaz"],
                   "zdroj_datum": p["datum"].astimezone(ZoneInfo("Europe/Prague")).date().isoformat() if p["datum"] else ""}
        for sz in sz_list:
            if f"US:{sz}" in zname or sz in videne:
                continue
            videne.add(sz)
            vysledek.append((sz, kontext))
    return vysledek


def zpracuj_text(sz: str, html: str, kontext: dict | None = None) -> Rozhodnuti:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) < 300:
        raise RuntimeError(f"ÚS: text {sz} je podezřele krátký ({len(text)} znaků) – zatím nezveřejněn?")

    r = Rozhodnuti(id=f"US:{sz}", soud="US", url=NALUS_TEXT.format(sz=sz))
    r.spisova_znacka = sz_na_spzn(sz)
    if m := re.search(r"(ECLI:CZ:US:\d{4}:[0-9A-Za-z.]+)", text):
        r.ecli = m.group(1)
    if m := re.search(r"ze\s+dne\s+(\d{1,2}\.\s*\d{1,2}\.\s*\d{4}|\d{1,2}\.\s*[a-zúěščřžýáíé]+\s+\d{4})", text):
        r.datum_rozhodnuti = datum_iso(m.group(1))
    if m := re.search(r"(ČESKÁ\s+REPUBLIKA|Česká\s+republika)", text):
        r.text = text[m.start():]
    else:
        r.text = text
    # forma až z textu rozhodnutí (ne z navigace stránky)
    if m := re.search(r"\b(NÁLEZ|USNESENÍ|STANOVISKO)\b", r.text[:1500]):
        r.forma = m.group(1).lower()
    r.extra = dict(kontext or {})
    # datum zveřejnění = kdy o rozhodnutí ÚS informoval v RSS
    r.datum_zverejneni = r.extra.pop("zdroj_datum", "") or ""
    return r


def stahni(sz: str, kontext: dict | None = None) -> Rozhodnuti:
    return zpracuj_text(sz, http.get(NALUS_TEXT.format(sz=sz)).text, kontext)
