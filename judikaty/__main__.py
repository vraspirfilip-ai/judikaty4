"""Spuštění: python -m judikaty [--bez-ai] [--jen NS|US] [--jen-vyzvednout] [--okamzite]"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import davky, filtry, http, vystupy
from .zdroje import nejvyssi_soud as ns
from .zdroje import ustavni_soud as us

log = logging.getLogger("judikaty")
KOREN = vystupy.KOREN
STAV = vystupy.DATA / "stav.json"
TZ = ZoneInfo("Europe/Prague")
MAX_POKUSU = 3
OPAKOVAT = {"chyba", "bez_kategorie"}


def nacti_nastaveni() -> dict:
    p = KOREN / "nastaveni.toml"
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def nacti_stav() -> dict:
    if STAV.exists():
        return json.loads(STAV.read_text(encoding="utf-8"))
    return {"zname": {}, "inicializovano": {}}


def uloz_stav(stav: dict) -> None:
    STAV.parent.mkdir(parents=True, exist_ok=True)
    tmp = STAV.with_suffix(".tmp")
    tmp.write_text(json.dumps(stav, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(STAV)


def oznac(stav: dict, rid: str, stav_zaznamu: str, **dalsi) -> None:
    stav["zname"][rid] = {"stav": stav_zaznamu, "datum": date.today().isoformat(), **dalsi}


def zpracuj_soud(soud: str, nastaveni: dict, stav: dict, analyzator, ted: datetime,
                 davka: davky.Davka | None = None) -> tuple[int, int]:
    """Vrátí (zpracováno nebo zařazeno do dávky, chyb)."""
    cfg = nastaveni.get("nejvyssi_soud" if soud == "NS" else "ustavni_soud", {})
    if not cfg.get("zapnuto", True):
        log.info("%s: vypnuto v nastavení", soud)
        return 0, 0
    limit = int(cfg.get("max_rozhodnuti_za_beh", cfg.get("max_rozhodnuti_za_den", 100 if soud == "NS" else 40)))
    prvni_beh = not stav["inicializovano"].get(soud)
    obecne = nastaveni.get("obecne", {})
    od = str(obecne.get("prvni_beh_od") or "")[:10] if prvni_beh else ""
    podle = str(obecne.get("prvni_beh_podle", "zverejneni"))
    if prvni_beh and od:
        log.info("%s: první běh – zpracuji rozhodnutí s datem %s od %s", soud,
                 "zveřejnění" if podle == "zverejneni" else "rozhodnutí", od)
        cfg = {**cfg, "od": od}
    elif prvni_beh:
        limit = min(limit, int(cfg.get("prvni_beh_max", 10)))
        log.info("%s: první běh – zpracuji max. %s nejnovějších, zbytek označím jako viděný", soud, limit)

    # stavy „chyba“ a „bez_kategorie“ s méně než MAX_POKUSU pokusy zkusíme znovu příště
    zname = {k for k, v in stav["zname"].items()
             if not (v.get("stav") in OPAKOVAT and v.get("pokusy", 0) < MAX_POKUSU)}

    if soud == "NS":
        # chybu v nastavení oblastí ohlásit hned, ne až u prvního rozhodnutí
        filtry.zkontroluj(cfg.get("vyloucit", {}).get("oblasti", []))
        kandidati = ns.seznam_novych(cfg, zname, limit)
    else:
        kandidati = us.seznam_novych(cfg, zname, limit)
    log.info("%s: nalezeno %s nových kandidátů", soud, len(kandidati))

    kategorie = {k.upper() for k in cfg.get("kategorie", [])}
    senaty = {int(s) for s in cfg.get("senaty", [])}
    max_stari = int(cfg.get("max_stari_dni", 30))
    hranice = (ted.date() - timedelta(days=max_stari)).isoformat()

    if od:
        # zveřejnění musí být od zvoleného data; podle data rozhodnutí filtrujeme níže zvlášť
        hranice = min(hranice, od) if podle != "zverejneni" else od

    hotovo = chyb = 0
    starsich_za_sebou = 0  # NS výsledky jsou řazené od nejnovějších → po řadě starších můžeme skončit
    for klic, kontext in kandidati:
        rid = f"{soud}:{klic}"
        if hotovo >= limit or (od and starsich_za_sebou >= 25):
            if prvni_beh:
                oznac(stav, rid, "preskoceno", duvod="první běh")
            continue
        # NS: nechtěný senát poznáme už z výpisu → detail vůbec nestahujeme
        if soud == "NS" and senaty:
            s = ns.senat_ze_spzn(kontext or "")
            if s is not None and s not in senaty:
                oznac(stav, rid, "preskoceno", duvod=f"senát {s}")
                continue
        try:
            r = ns.stahni(klic) if soud == "NS" else us.stahni(klic, kontext)
        except Exception as e:  # noqa: BLE001
            chyb += 1
            pokusy = stav["zname"].get(rid, {}).get("pokusy", 0) + 1
            log.warning("%s: stažení %s selhalo (%s/%s): %s", soud, klic, pokusy, MAX_POKUSU, e)
            oznac(stav, rid, "chyba", pokusy=pokusy, chyba=str(e)[:300])
            uloz_stav(stav)
            continue

        if soud == "NS" and senaty:
            s = ns.senat_ze_spzn(r.spisova_znacka)
            if s is not None and s not in senaty:
                oznac(stav, rid, "preskoceno", duvod=f"senát {s}")
                continue
        if soud == "NS" and kategorie:
            if not r.kategorie:
                # kategorie ještě nemusí být přidělena → zkusíme při dalším běhu
                pokusy = stav["zname"].get(rid, {}).get("pokusy", 0) + 1
                oznac(stav, rid, "bez_kategorie", pokusy=pokusy, spzn=r.spisova_znacka)
                continue
            if r.kategorie not in kategorie:
                oznac(stav, rid, "preskoceno", duvod=f"kategorie {r.kategorie}")
                continue
        zverejneno = r.datum_zverejneni
        if zverejneno and zverejneno < hranice:
            oznac(stav, rid, "preskoceno", duvod=f"zveřejněno {zverejneno}")
            starsich_za_sebou += 1
            continue
        if od and podle == "rozhodnuti" and r.datum_rozhodnuti and r.datum_rozhodnuti < od:
            oznac(stav, rid, "preskoceno", duvod=f"rozhodnuto {r.datum_rozhodnuti}")
            continue
        starsich_za_sebou = 0

        if soud == "US" and cfg.get("jen_nalezy", True) and r.forma != "nález":
            oznac(stav, rid, "preskoceno", duvod=f"forma {r.forma or 'neznámá'}", spzn=r.spisova_znacka)
            continue
        if soud == "NS":
            vyl = cfg.get("vyloucit", {})
            oblast = filtry.vyrazujici_oblast(r, vyl.get("oblasti", []), vyl.get("vlastni_vzory", []))
            if oblast:
                # do přehledu se vypíše seznam vyřazených, aby šel filtr zkontrolovat
                oznac(stav, rid, "vyrazeno", duvod=oblast, spzn=r.spisova_znacka, url=r.url,
                      den=ted.date().isoformat())
                log.info("%s: vyřazeno %s (%s)", soud, r.spisova_znacka, oblast)
                continue

        zaznam = r.bez_textu()
        zaznam["zpracovano"] = ted.isoformat(timespec="seconds")
        zaznam["delka_textu"] = len(r.text)
        if cfg.get("ulozit_plny_text", False):
            zaznam["text"] = r.text
        if davka is not None:
            davka.pridej(r, zaznam)
            oznac(stav, rid, "v_davce", spzn=r.spisova_znacka)
            uloz_stav(stav)
            hotovo += 1
            log.info("%s: → do dávky %s", soud, r.spisova_znacka or klic)
            continue
        if analyzator is not None:
            try:
                zaznam["rozbor"] = analyzator.zpracuj(r)
                zaznam["model"] = analyzator.model
            except Exception as e:  # noqa: BLE001
                chyb += 1
                pokusy = stav["zname"].get(rid, {}).get("pokusy", 0) + 1
                log.warning("%s: AI rozbor %s selhal (%s/%s): %s", soud, r.spisova_znacka, pokusy, MAX_POKUSU, e)
                oznac(stav, rid, "chyba", pokusy=pokusy, chyba=str(e)[:300])
                uloz_stav(stav)
                continue
        vystupy.uloz_zaznam(zaznam)
        oznac(stav, rid, "ok", spzn=r.spisova_znacka)
        uloz_stav(stav)
        hotovo += 1
        log.info("%s: ✓ %s", soud, r.spisova_znacka or klic)

    stav["inicializovano"][soud] = True
    uloz_stav(stav)
    return hotovo, chyb


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stahování a AI rozbor judikatury NS a ÚS")
    ap.add_argument("--bez-ai", action="store_true", help="jen stáhnout, bez Claude API")
    ap.add_argument("--jen", choices=["NS", "US"], help="zpracovat jen jeden soud")
    ap.add_argument("--jen-vystupy", action="store_true", help="jen přegenerovat přehledy a web")
    ap.add_argument("--jen-vyzvednout", action="store_true",
                    help="nic nestahovat, jen vyzvednout dokončené dávky (kontrolní běh)")
    ap.add_argument("--okamzite", action="store_true",
                    help="nepoužít Batch API, zpracovat hned (dvojnásobná cena)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    nastaveni = nacti_nastaveni()
    obecne = nastaveni.get("obecne", {})
    http.nastav_prodlevu(obecne.get("prodleva_mezi_dotazy_s", 1.5))
    ted = datetime.now(TZ)
    davkove = bool(obecne.get("davkove_zpracovani", True)) and not args.okamzite

    vysledky: dict[str, tuple[int, int] | str] = {}
    analyzator = None
    if not args.jen_vystupy:
        stav = nacti_stav()
        if not args.bez_ai:
            from .rozbor import Analyzator
            analyzator = Analyzator(
                model=os.environ.get("CLAUDE_MODEL") or obecne.get("model", "claude-sonnet-5-5"),
                max_znaku=int(obecne.get("max_znaku_textu", 120_000)),
            )
            # nejdřív vyzvednout dávky z minula (kdyby nedoběhly)
            if davky.ceka_se(stav):
                vysledky["dávky z minula"] = davky.vyzvedni(analyzator, stav, oznac, uloz_stav, MAX_POKUSU)

        if not args.jen_vyzvednout:
            davka = davky.Davka(analyzator, stav) if (analyzator and davkove) else None
            for soud in ("US", "NS"):
                if args.jen and args.jen != soud:
                    continue
                try:
                    vysledky[soud] = zpracuj_soud(soud, nastaveni, stav, analyzator, ted, davka)
                except Exception as e:  # noqa: BLE001
                    log.error("%s: zdroj selhal: %s", soud, e)
                    vysledky[soud] = f"CHYBA: {e}"
            if davka is not None:
                try:
                    davka.odeslat()
                except Exception as e:  # noqa: BLE001
                    # odeslání selhalo → rozhodnutí vrátíme k opakování příště
                    log.error("Odeslání dávky selhalo: %s", e)
                    for p in davka.pozadavky:
                        f = davky.FRONTA / f"{p['custom_id']}.json"
                        if f.exists():
                            rid = json.loads(f.read_text(encoding="utf-8"))["id"]
                            oznac(stav, rid, "chyba", pokusy=1, chyba=f"odeslání dávky: {e}"[:300])
                            f.unlink()
                    vysledky["dávka"] = f"CHYBA: {e}"
                uloz_stav(stav)

        if analyzator and davky.ceka_se(stav):
            max_minut = 0 if args.jen_vyzvednout else float(obecne.get("max_cekani_na_davku_min", 240))
            vysledky["vyzvednuto z dávky"] = davky.cekej_a_vyzvedni(
                analyzator, stav, oznac, uloz_stav, MAX_POKUSU, max_minut,
                float(obecne.get("interval_kontroly_davky_s", 60)))
            if davky.ceka_se(stav):
                vysledky["čeká se"] = f"{len(stav['davky'])} dávka/y ještě běží, vyzvedne je kontrolní běh"

    zaznamy = vystupy.nacti_vsechny()
    stav_vyrazene = [v for v in nacti_stav()["zname"].values() if v.get("stav") == "vyrazeno"]
    # přehledy pro všechny dny, kdy se v posledních 3 týdnech něco zpracovalo
    # (dávka odeslaná v pátek a vyzvednutá později patří do pátečního přehledu)
    hranice = (ted.date() - timedelta(days=21)).isoformat()
    dny = sorted({(z.get("zpracovano") or "")[:10] for z in zaznamy if (z.get("zpracovano") or "") >= hranice})
    prehled = None
    for den in dny:
        vyrazene = [v for v in stav_vyrazene if v.get("den") == den]
        prehled = vystupy.denni_prehled(den, zaznamy, bool(obecne.get("skryt_procesni_v_prehledu", True)),
                                        vyrazene) or prehled
    vystupy.index_prehledu()
    vystupy.web_data(zaznamy)
    vystupy.rss(zaznamy, obecne.get("adresa_webu", ""))

    # souhrn do GitHub Actions
    souhrn = ["## Judikáty – běh " + ted.strftime("%d. %m. %Y %H:%M"), ""]
    for klic, v in vysledky.items():
        souhrn.append(f"- **{klic}**: " + (f"{v[0]}, chyb {v[1]}" if isinstance(v, tuple) else v))
    if analyzator:
        u = analyzator.spotreba
        cena = "poloviční (Batch API)" if davkove else "plná"
        souhrn.append(f"- Tokeny: vstup {u['input_tokens']:,}, výstup {u['output_tokens']:,}".replace(",", " ")
                      + f" – cena {cena}")
    if not args.jen_vystupy:
        chyby = [(k, v) for k, v in nacti_stav()["zname"].items()
                 if v.get("stav") == "chyba" and v.get("datum") == date.today().isoformat()]
        if chyby:
            souhrn += ["", "### Chyby v tomto běhu", ""]
            souhrn += [f"- {v.get('spzn') or k}: {v.get('chyba', '')}" for k, v in chyby[:10]]
    if prehled:
        souhrn += ["", prehled.read_text(encoding="utf-8")]
    if gh := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(gh, "a", encoding="utf-8") as f:
            f.write("\n".join(souhrn) + "\n")
    print("\n".join(souhrn[:10]))

    # selhaly-li všechny zdroje, ať o tom GitHub pošle e-mail
    zdroje = [v for k, v in vysledky.items() if k in ("NS", "US")]
    if zdroje and all(isinstance(v, str) for v in zdroje):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
