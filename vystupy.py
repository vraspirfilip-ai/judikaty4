"""Ukládání výsledků: JSON pro každé rozhodnutí, týdenní přehled v Markdownu,
data pro webovou stránku (GitHub Pages) a RSS kanál."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .model import cesky_datum

KOREN = Path(__file__).resolve().parent.parent
DATA = KOREN / "data"
ROZHODNUTI = DATA / "rozhodnuti"
PREHLEDY = KOREN / "prehledy"
WEB = KOREN / "docs"

SOUD_NAZEV = {"NS": "Nejvyšší soud", "US": "Ústavní soud"}
VYZNAM_PORADI = {"vysoký": 0, "střední": 1, "nízký": 2}
VYZNAM_IKONA = {"vysoký": "🔴", "střední": "🟡", "nízký": "⚪"}


def klicove_otazky(rozbor: dict) -> list[dict]:
    """Seznam {otazka, odpoved}; zvládne i starší záznamy s jedinou „pravni_otazka“."""
    otazky = [o for o in rozbor.get("klicove_otazky") or [] if isinstance(o, dict) and o.get("otazka")]
    if not otazky and rozbor.get("pravni_otazka"):
        otazky = [{"otazka": rozbor["pravni_otazka"], "odpoved": ""}]
    return otazky


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-")[:60] or "rozhodnuti"


def cesta_zaznamu(zaznam: dict) -> Path:
    rok = (zaznam.get("zpracovano") or "")[:4] or "nezname"
    kratke_id = zaznam["id"].split(":", 1)[1][:12]
    nazev = f"{_slug(zaznam.get('spisova_znacka') or '')}_{_slug(kratke_id)}.json"
    return ROZHODNUTI / zaznam["soud"] / rok / nazev


def uloz_zaznam(zaznam: dict) -> Path:
    p = cesta_zaznamu(zaznam)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(zaznam, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def nacti_vsechny() -> list[dict]:
    zaznamy = []
    for p in ROZHODNUTI.rglob("*.json"):
        try:
            zaznamy.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    zaznamy.sort(key=lambda z: (z.get("zpracovano", ""), z.get("datum_rozhodnuti", "")), reverse=True)
    return zaznamy


def _razeni(z: dict):
    a = z.get("rozbor") or {}
    return (0 if z["soud"] == "US" else 1, VYZNAM_PORADI.get(a.get("vyznam"), 3), z.get("spisova_znacka", ""))


def markdown_zaznamu(z: dict) -> str:
    a = z.get("rozbor") or {}
    forma = (z.get("forma") or "rozhodnutí").capitalize()
    datum = cesky_datum(z.get("datum_rozhodnuti", ""))
    nadpis = f"### {VYZNAM_IKONA.get(a.get('vyznam'), '')} {z.get('spisova_znacka') or z['id']}".strip()
    radky = [nadpis, ""]
    meta = [f"{forma}" + (f" ze dne {datum}" if datum else "")]
    if z.get("kategorie"):
        meta.append(f"kategorie {z['kategorie']}")
    if a.get("pravni_oblast"):
        meta.append(a["pravni_oblast"])
    if a.get("vyznam"):
        meta.append(f"význam: {a['vyznam']}")
    meta.append(f"[plný text]({z['url']})")
    radky.append(" · ".join(meta))
    radky.append("")
    if not a:
        radky.append("_Bez AI rozboru._")
        return "\n".join(radky) + "\n"
    radky += [f"**Shrnutí:** {a.get('shrnuti', '')}", ""]
    otazky = klicove_otazky(a)
    if otazky:
        radky += ["**Klíčové řešené otázky:**", ""]
        for i, o in enumerate(otazky, 1):
            radky.append(f"{i}. *{o['otazka']}*" + (f"  \n   → {o['odpoved']}" if o.get("odpoved") else ""))
        radky.append("")
    if a.get("vysledek"):
        radky += [f"**Výsledek:** {a['vysledek']}", ""]
    vety = a.get("pravni_vety") or []
    if vety:
        radky.append("**Právní věty:**")
        radky.append("")
        for i, v in enumerate(vety, 1):
            radky.append(f"> {i}. {v}" if len(vety) > 1 else f"> {v}")
            radky.append(">")
        radky[-1] = ""
    if a.get("dotcene_predpisy"):
        radky += [f"**Předpisy:** {', '.join(a['dotcene_predpisy'])}", ""]
    if a.get("klicova_slova"):
        radky += [f"**Hesla:** {', '.join(a['klicova_slova'])}", ""]
    return "\n".join(radky) + "\n"


def denni_prehled(den: str, zaznamy: list[dict], skryt_procesni: bool = False,
                  vyrazene: list[dict] | None = None) -> Path | None:
    dnesni = [z for z in zaznamy if (z.get("zpracovano") or "")[:10] == den]
    vyrazene = vyrazene or []
    if not dnesni and not vyrazene:
        return None
    dnesni.sort(key=_razeni)
    pocty = {s: sum(1 for z in dnesni if z["soud"] == s) for s in ("US", "NS")}
    procesni = [z for z in dnesni if (z.get("rozbor") or {}).get("jen_procesni")]
    radky = [
        f"# Týdenní přehled judikatury – {cesky_datum(den)}",
        "",
        f"Nově zpracováno **{len(dnesni)}** rozhodnutí (Ústavní soud: {pocty['US']}, "
        f"Nejvyšší soud: {pocty['NS']}).",
        "",
        "> Shrnutí a právní věty vytvořila AI z plného textu rozhodnutí. "
        "Před použitím vždy ověřte v originálu.",
        "",
    ]
    for soud in ("US", "NS"):
        vybrane = [z for z in dnesni if z["soud"] == soud]
        if skryt_procesni:
            vybrane = [z for z in vybrane if not (z.get("rozbor") or {}).get("jen_procesni")]
        if not vybrane:
            continue
        radky += [f"## {SOUD_NAZEV[soud]}", ""]
        for z in vybrane:
            radky.append(markdown_zaznamu(z))
            radky.append("---\n")
    if skryt_procesni and procesni:
        radky += ["## Procesní rozhodnutí (bez právní věty)", ""]
        for z in procesni:
            a = z.get("rozbor") or {}
            radky.append(f"- [{z.get('spisova_znacka')}]({z['url']}) – {a.get('vysledek', '')}")
        radky.append("")
    if vyrazene:
        radky += [f"## Vyřazeno filtrem oblastí ({len(vyrazene)})", "",
                  "_Tato rozhodnutí NS se AI neposlala. Pokud mezi nimi vidíte něco, co vás zajímá, "
                  "upravte `[nejvyssi_soud.vyloucit]` v `nastaveni.toml`._", ""]
        for v in sorted(vyrazene, key=lambda v: (v.get("duvod", ""), v.get("spzn", ""))):
            radky.append(f"- [{v.get('spzn') or 'rozhodnutí'}]({v.get('url', '')}) – {v.get('duvod', '')}")
        radky.append("")
    p = PREHLEDY / den[:4] / f"{den}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(radky), encoding="utf-8")
    return p


def index_prehledu() -> None:
    soubory = sorted(PREHLEDY.rglob("*.md"), reverse=True)
    soubory = [s for s in soubory if s.name != "README.md"]
    radky = ["# Týdenní přehledy judikatury", ""]
    for s in soubory[:365]:
        den = s.stem
        radky.append(f"- [{cesky_datum(den)}]({s.relative_to(PREHLEDY).as_posix()})")
    PREHLEDY.mkdir(exist_ok=True)
    (PREHLEDY / "README.md").write_text("\n".join(radky) + "\n", encoding="utf-8")


def web_data(zaznamy: list[dict], limit: int = 3000) -> None:
    WEB.mkdir(exist_ok=True)
    out = []
    for z in zaznamy[:limit]:
        a = z.get("rozbor") or {}
        out.append({
            "id": z["id"], "soud": z["soud"], "url": z["url"],
            "spzn": z.get("spisova_znacka", ""), "ecli": z.get("ecli", ""),
            "forma": z.get("forma", ""), "datum": z.get("datum_rozhodnuti", ""),
            "zpracovano": (z.get("zpracovano") or "")[:10], "kategorie": z.get("kategorie", ""),
            "oblast": a.get("pravni_oblast", ""), "vyznam": a.get("vyznam", ""),
            "otazky": klicove_otazky(a), "shrnuti": a.get("shrnuti", ""),
            "vety": a.get("pravni_vety", []), "vysledek": a.get("vysledek", ""),
            "predpisy": a.get("dotcene_predpisy", []), "hesla": a.get("klicova_slova", []),
            "procesni": bool(a.get("jen_procesni")),
        })
    (WEB / "data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def rss(zaznamy: list[dict], odkaz_webu: str, limit: int = 150) -> None:
    WEB.mkdir(exist_ok=True)
    polozky = []
    for z in [z for z in zaznamy if not (z.get("rozbor") or {}).get("jen_procesni")][:limit]:
        a = z.get("rozbor") or {}
        try:
            dt = datetime.fromisoformat(z.get("zpracovano")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            dt = datetime.now(timezone.utc)
        popis = a.get("shrnuti", "")
        if a.get("pravni_vety"):
            popis += "\n\nPrávní věty:\n" + "\n".join(f"• {v}" for v in a["pravni_vety"])
        titulek = f"{SOUD_NAZEV[z['soud']]} {z.get('spisova_znacka', '')}"
        otazky = klicove_otazky(a)
        if otazky:
            titulek += f" – {otazky[0]['otazka']}"
            popis = "Klíčové otázky:\n" + "\n".join(
                f"• {o['otazka']} → {o.get('odpoved', '')}" for o in otazky) + "\n\n" + popis
        polozky.append(
            "<item>"
            f"<title>{escape(titulek)}</title>"
            f"<link>{escape(z['url'])}</link>"
            f"<guid isPermaLink=\"false\">{escape(z['id'])}</guid>"
            f"<pubDate>{format_datetime(dt)}</pubDate>"
            f"<category>{escape(a.get('pravni_oblast', ''))}</category>"
            f"<description>{escape(popis)}</description>"
            "</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        "<title>Judikatura NS a ÚS – AI přehled</title>"
        f"<link>{escape(odkaz_webu or 'https://github.com/')}</link>"
        "<description>Nová rozhodnutí Nejvyššího a Ústavního soudu se shrnutím a právními větami.</description>"
        "<language>cs</language>" + "".join(polozky) + "</channel></rss>\n"
    )
    (WEB / "feed.xml").write_text(xml, encoding="utf-8")
