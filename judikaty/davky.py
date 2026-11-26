"""Dávkové zpracování přes Message Batches API (poloviční cena).

Průběh:
1. stažená rozhodnutí se uloží do fronty `data/fronta/` (metadata bez textu)
   a jejich požadavky se odešlou jednou dávkou,
2. ID dávky se zapíše do `data/stav.json` (klíč "davky"),
3. bot čeká na dokončení; když dávka nedoběhne včas, vyzvedne ji kterýkoli
   další běh (kontrolní běhy jsou naplánované ve workflow),
4. hotové rozbory se spojí s metadaty z fronty a uloží jako běžné záznamy.

Výsledky dávky zůstávají na straně Anthropicu k vyzvednutí 29 dní.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date

from . import vystupy
from .model import Rozhodnuti
from .rozbor import vytahni_rozbor

log = logging.getLogger(__name__)
FRONTA = vystupy.DATA / "fronta"


def custom_id(rid: str) -> str:
    """Batch API povoluje v custom_id jen [a-zA-Z0-9_-], max. 64 znaků."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", rid)[:64]


class Davka:
    def __init__(self, analyzator, stav: dict):
        self.a = analyzator
        self.stav = stav
        self.pozadavky: list[dict] = []

    def pridej(self, r: Rozhodnuti, zaznam: dict) -> None:
        cid = custom_id(r.id)
        FRONTA.mkdir(parents=True, exist_ok=True)
        (FRONTA / f"{cid}.json").write_text(json.dumps(zaznam, ensure_ascii=False, indent=1), encoding="utf-8")
        self.pozadavky.append({"custom_id": cid, "params": self.a.parametry(r)})

    def odeslat(self) -> str | None:
        if not self.pozadavky:
            return None
        b = self.a.client.messages.batches.create(requests=self.pozadavky)
        self.stav.setdefault("davky", {})[b.id] = {
            "vytvoreno": date.today().isoformat(),
            "pozadavky": [p["custom_id"] for p in self.pozadavky],
        }
        log.info("Odeslána dávka %s (%s rozhodnutí)", b.id, len(self.pozadavky))
        self.pozadavky = []
        return b.id


def ceka_se(stav: dict) -> bool:
    return bool(stav.get("davky"))


def vyzvedni(analyzator, stav: dict, oznac, uloz_stav, max_pokusu: int) -> tuple[int, int]:
    """Zpracuje všechny dokončené dávky. Vrátí (uloženo, chyb)."""
    ulozeno = chyb = 0
    for bid in list(stav.get("davky", {})):
        try:
            b = analyzator.client.messages.batches.retrieve(bid)
        except Exception as e:  # noqa: BLE001
            log.warning("Dávku %s nelze načíst: %s", bid, e)
            continue
        if b.processing_status != "ended":
            log.info("Dávka %s ještě běží (%s)", bid, b.processing_status)
            continue

        for vysledek in analyzator.client.messages.batches.results(bid):
            cid = vysledek.custom_id
            soubor = FRONTA / f"{cid}.json"
            if not soubor.exists():
                continue
            zaznam = json.loads(soubor.read_text(encoding="utf-8"))
            rid = zaznam["id"]
            typ = vysledek.result.type
            try:
                if typ != "succeeded":
                    raise RuntimeError(f"výsledek dávky: {typ}")
                zprava = vysledek.result.message
                analyzator.zapocti(zprava)
                zaznam["rozbor"] = vytahni_rozbor(zprava)
                zaznam["model"] = analyzator.model
                zaznam["davka"] = bid
                vystupy.uloz_zaznam(zaznam)
                oznac(stav, rid, "ok", spzn=zaznam.get("spisova_znacka", ""))
                ulozeno += 1
            except Exception as e:  # noqa: BLE001
                chyb += 1
                pokusy = stav["zname"].get(rid, {}).get("pokusy", 0) + 1
                log.warning("Rozbor %s selhal (%s/%s): %s", zaznam.get("spisova_znacka"), pokusy, max_pokusu, e)
                oznac(stav, rid, "chyba", pokusy=pokusy, chyba=str(e)[:300])
            soubor.unlink(missing_ok=True)

        # co v dávce chybělo (nemělo by nastat), vrátíme k opakování
        for cid in stav["davky"][bid].get("pozadavky", []):
            soubor = FRONTA / f"{cid}.json"
            if soubor.exists():
                rid = json.loads(soubor.read_text(encoding="utf-8"))["id"]
                oznac(stav, rid, "chyba", pokusy=stav["zname"].get(rid, {}).get("pokusy", 0) + 1,
                      chyba="chybí ve výsledcích dávky")
                soubor.unlink()
        del stav["davky"][bid]
        uloz_stav(stav)
        log.info("Dávka %s vyzvednuta", bid)
    return ulozeno, chyb


def cekej_a_vyzvedni(analyzator, stav, oznac, uloz_stav, max_pokusu: int,
                     max_minut: float, interval_s: float = 60) -> tuple[int, int]:
    """Čeká na dokončení dávek (nejvýš max_minut) a průběžně je vyzvedává."""
    konec = time.monotonic() + max_minut * 60
    celkem = [0, 0]
    while True:
        u, c = vyzvedni(analyzator, stav, oznac, uloz_stav, max_pokusu)
        celkem[0] += u
        celkem[1] += c
        if not ceka_se(stav) or time.monotonic() >= konec:
            break
        time.sleep(interval_s)
    if ceka_se(stav):
        log.info("Některé dávky ještě běží – vyzvedne je příští kontrolní běh.")
    return celkem[0], celkem[1]
