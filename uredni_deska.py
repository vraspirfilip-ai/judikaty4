"""Nejvyšší soud – elektronická úřední deska, vyhlašovaná rozhodnutí.

https://www.nsoud.cz/uredni-deska/obcanskopravni-a-obchodni-kolegium/vyhlasovana-rozhodnuti

Tabulka: spisová značka | datum vyhlášení | změna | příloha (PDF se zkráceným
písemným vyhotovením rozsudku). Rozhodnutí visí na desce 15 dní. Vyhlášení se
oznamují předem, takže řádky s budoucím datem ještě PDF mít nemusí.

POZOR: PDF na desce nejsou pseudonymizována (obsahují osobní údaje účastníků).
Bot proto plný text nikam neukládá a do ladicího souboru zapisuje jen
strukturu dokumentu, ne jeho obsah.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import date
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .. import http
from ..model import Rozhodnuti, datum_iso

log = logging.getLogger(__name__)

URL = "https://www.nsoud.cz/uredni-deska/obcanskopravni-a-obchodni-kolegium/vyhlasovana-rozhodnuti"
SPZN_RE = re.compile(r"(\d{1,2})\s+([A-ZČ][A-Za-zČčŘř]{1,6})\s+(\d{1,6})\s*/\s*(\d{4})")
DATUM_RE = re.compile(r"\d{1,2}\.\s*\d{1,2}\.\s*\d{4}")

# strukturní údaje o posledním staženém PDF (bez textu) – ukládají se do data/ladeni/
UKAZKA = ""
# HTML výpisu desky (jen sp. zn., data a názvy PDF – bez osobních údajů) pro ladění
VYPIS_HTML = ""


def normalizuj_spzn(text: str) -> str:
    """'29 ICdo 103 / 2026' → '29 ICdo 103/2026'."""
    m = SPZN_RE.search(text or "")
    return f"{m.group(1)} {m.group(2)} {m.group(3)}/{m.group(4)}" if m else ""


def klic(spzn: str) -> str:
    """Stabilní klíč do paměti bota: '28 Cdo 302/2026' → 'UD-28_Cdo_302_2026'."""
    return "UD-" + re.sub(r"[ /]+", "_", spzn)


def nacti_radky(html: str, zaklad: str = URL) -> list[dict]:
    """Řádky tabulky: [{spzn, datum (ISO), pdf (URL nebo ''), zmena}]."""
    soup = BeautifulSoup(html, "lxml")
    radky = []
    for tr in soup.find_all("tr"):
        bunky = tr.find_all(["td", "th"])
        if len(bunky) < 2:
            continue
        spzn = normalizuj_spzn(bunky[0].get_text(" "))
        if not spzn:
            continue
        datum_text = next((DATUM_RE.search(b.get_text(" ")).group(0) for b in bunky[1:]
                           if DATUM_RE.search(b.get_text(" "))), "")
        odkaz = tr.find("a", href=re.compile(r"\.pdf($|\?)", re.I))
        radky.append({
            "spzn": spzn,
            "datum": datum_iso(datum_text),
            "pdf": urljoin(zaklad, odkaz["href"]) if odkaz else "",
            "zmena": bunky[2].get_text(" ", strip=True) if len(bunky) > 2 else "",
        })
    return radky


def dalsi_stranky(html: str, zaklad: str = URL) -> list[str]:
    """Odkazy na další stránky výpisu (stránkování) a na „Vypsat všechna vyhlášení“."""
    soup = BeautifulSoup(html, "lxml")
    cesta = re.sub(r"^https?://[^/]+", "", zaklad).split("?")[0]
    odkazy = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        href = urljoin(zaklad, a["href"])
        if cesta not in href or "?" not in href:
            continue
        if "vypsat všechna" in text:
            odkazy.append(urljoin(zaklad, a["href"]))
            continue
        if text.isdigit() or text in {"další", "›", "»", "následující", "next"} \
                or re.search(r"(page|strana|currentpage)", href, re.I):
            odkazy.append(href)
    # „Vypsat všechna“ dopředu
    odkazy.sort(key=lambda u: 0 if "vypsat" in u.lower() else 1)
    return list(dict.fromkeys(odkazy))


def _ceske_datum(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def formular_hledani(html: str, zaklad: str, od: str = "") -> tuple[str, str, dict] | None:
    """Najde vyhledávací formulář desky a připraví dotaz s co nejvíce výsledky na stránku
    (a případně „Vyhlášení od“). Vrátí (metoda, url, data) nebo None."""
    soup = BeautifulSoup(html, "lxml")
    for form in soup.find_all("form"):
        selecty = form.find_all("select")
        pocet = next((sel for sel in selecty
                      if [o for o in sel.find_all("option") if (o.get("value") or o.get_text(strip=True)).strip().isdigit()]),
                     None)
        if pocet is None:
            continue
        data: dict[str, str] = {}
        for inp in form.find_all("input"):
            nazev, typ = inp.get("name"), (inp.get("type") or "text").lower()
            if not nazev or typ in {"submit", "button", "reset", "image", "file"}:
                continue
            if typ in {"checkbox", "radio"} and not inp.has_attr("checked"):
                continue
            data[nazev] = inp.get("value", "")
        for sel in selecty:
            if not sel.get("name"):
                continue
            moznosti = [(o.get("value") if o.has_attr("value") else o.get_text(strip=True)) for o in sel.find_all("option")]
            if sel is pocet:
                data[sel["name"]] = max((m for m in moznosti if m.strip().isdigit()), key=int)
            else:
                vybrana = sel.find("option", selected=True)
                data[sel["name"]] = (vybrana.get("value", vybrana.get_text(strip=True)) if vybrana
                                     else (moznosti[0] if moznosti else ""))
        # „Vyhlášení od“: pole označené popiskem (label for=…)
        if od:
            for label in form.find_all("label"):
                if re.search(r"vyhlášení\s+od", label.get_text(" "), re.I) and label.get("for"):
                    pole = form.find(id=label["for"])
                    if pole is not None and pole.get("name"):
                        data[pole["name"]] = _ceske_datum(od) if pole.get("type") != "date" else od
        tlacitko = form.find(["button", "input"], attrs={"type": "submit"})
        if tlacitko is not None and tlacitko.get("name"):
            data[tlacitko["name"]] = tlacitko.get("value", "")
        metoda = (form.get("method") or "get").lower()
        return metoda, urljoin(zaklad, form.get("action") or zaklad), data
    return None


def vsechny_radky(url: str = URL, max_stranek: int = 15, od: str = "") -> list[dict]:
    """Projde výpis: výchozí stránku, vyhledávání s maximem výsledků na stránku,
    „Vypsat všechna vyhlášení“ i stránkování. Vrátí všechny řádky (bez duplicit)."""
    global VYPIS_HTML
    navstivene, radky, videne = set(), [], set()

    def pridej(html: str, u: str) -> None:
        for r in nacti_radky(html, u):
            k = (r["spzn"], r["datum"], r["pdf"])
            if k not in videne:
                videne.add(k)
                radky.append(r)

    html = http.get(url).text
    navstivene.add(url)
    VYPIS_HTML = html
    pridej(html, url)
    fronta = dalsi_stranky(html, url)

    formular = formular_hledani(html, url, od)
    if formular:
        metoda, akce, data = formular
        try:
            if metoda == "post":
                html2 = http.post(akce, data).text
                u2 = akce
            else:
                u2 = akce + ("&" if "?" in akce else "?") + urlencode(data)
                html2 = http.get(u2).text
            navstivene.add(u2)
            pridej(html2, u2)
            fronta += dalsi_stranky(html2, u2)
        except Exception as e:  # noqa: BLE001
            log.warning("Úřední deska: vyhledávací formulář selhal: %s", e)

    while fronta and len(navstivene) < max_stranek:
        u = fronta.pop(0)
        if u in navstivene:
            continue
        navstivene.add(u)
        html = http.get(u).text
        pridej(html, u)
        fronta += [o for o in dalsi_stranky(html, u) if o not in navstivene]
    if not radky:
        raise RuntimeError("Úřední deska NS: ve výpisu nejsou žádná rozhodnutí – možná se změnila "
                           "struktura stránky. URL: " + url)
    log.info("Úřední deska: %s řádků z %s stránek", len(radky), len(navstivene))
    return radky


def seznam_novych(nastaveni: dict, zname: set[str], limit: int) -> list[tuple[str, dict]]:
    """Vrátí [(klíč, řádek)] vyhlášených rozhodnutí s PDF, která bot ještě nemá."""
    dnes = date.today().isoformat()
    vysledek = []
    radky = vsechny_radky(nastaveni.get("uredni_deska_url") or URL, int(nastaveni.get("max_stranek_desky", 15)),
                          nastaveni.get("od_data", ""))
    data = sorted(r["datum"] for r in radky if r["datum"])
    if data:
        log.info("Úřední deska: vyhlášení od %s do %s", data[0], data[-1])
    for r in radky:
        if not r["pdf"] or (r["datum"] and r["datum"] > dnes):
            continue  # vyhlášení teprve oznámené – PDF zatím není
        k = klic(r["spzn"])
        if f"NS:{k}" in zname:
            continue
        vysledek.append((k, r))
    # nejnovější vyhlášení první
    vysledek.sort(key=lambda kr: kr[1]["datum"], reverse=True)
    return vysledek


def text_z_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((s.extract_text() or "") for s in reader.pages)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def stahni(k: str, radek: dict) -> Rozhodnuti:
    global UKAZKA
    odpoved = http.get(radek["pdf"])
    text = text_z_pdf(odpoved.content)
    if len(text) < 200:
        raise RuntimeError(f"PDF {radek['spzn']} neobsahuje čitelný text ({len(text)} znaků) – sken?")

    r = Rozhodnuti(id=f"NS:{k}", soud="NS", url=radek["pdf"], spisova_znacka=radek["spzn"])
    r.datum_rozhodnuti = radek["datum"]     # rozsudek je vydán (vyhlášen) vyvěšením
    r.datum_zverejneni = radek["datum"]
    m = re.search(r"\b(ROZSUDEK|USNESENÍ)\b", text)
    r.forma = (m.group(1) if m else "rozsudek").lower()
    if m := re.search(r"(ČESKÁ\s+REPUBLIKA)", text):
        text = text[m.start():]
    r.text = text
    r.extra = {"zdroj": "úřední deska", "zmena": radek.get("zmena", ""),
               "ma_oduvodneni": bool(re.search(r"\bOdůvodnění\b", text))}
    if not UKAZKA:
        nadpisy = [n for n in ("ČESKÁ REPUBLIKA", "ROZSUDEK", "USNESENÍ", "takto", "Odůvodnění", "Poučení")
                   if re.search(re.escape(n), text)]
        UKAZKA = (f"{radek['pdf']}\nspisová značka: {radek['spzn']}\nvyhlášeno: {radek['datum']}\n"
                  f"počet znaků textu: {len(text)}\nnalezené části: {', '.join(nadpisy)}\n"
                  "(text rozhodnutí se kvůli osobním údajům neukládá)\n")
    return r
