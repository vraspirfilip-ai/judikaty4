"""Sdílený HTTP klient se zdvořilou prodlevou a opakováním."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) judikaty-bot/1.0 "
    "(denni prehled judikatury; https://github.com/)"
)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "cs,en;q=0.5"})

PRODLEVA_S = 1.5
_posledni = 0.0


def nastav_prodlevu(sekundy: float) -> None:
    global PRODLEVA_S
    PRODLEVA_S = float(sekundy)


def post(url: str, data: dict, *, pokusy: int = 3, timeout: int = 60) -> requests.Response:
    """POST formuláře (např. vyhledávání na úřední desce)."""
    return get(url, pokusy=pokusy, timeout=timeout, _data=data)


def get(url: str, *, pokusy: int = 3, timeout: int = 60, _data: dict | None = None) -> requests.Response:
    """GET s prodlevou mezi dotazy (šetříme servery soudů) a opakováním při chybě."""
    global _posledni
    posledni_chyba: Exception | None = None
    for pokus in range(1, pokusy + 1):
        cekat = PRODLEVA_S - (time.monotonic() - _posledni)
        if cekat > 0:
            time.sleep(cekat)
        try:
            r = (_session.post(url, data=_data, timeout=timeout) if _data is not None
                 else _session.get(url, timeout=timeout))
            _posledni = time.monotonic()
            if r.status_code == 200:
                _oprav_kodovani(r)
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                posledni_chyba = requests.HTTPError(f"HTTP {r.status_code} pro {url}")
            else:
                r.raise_for_status()
        except requests.RequestException as e:
            _posledni = time.monotonic()
            posledni_chyba = e
        log.warning("Pokus %s/%s selhal: %s", pokus, pokusy, posledni_chyba)
        time.sleep(5 * pokus)
    raise RuntimeError(f"Nepodařilo se stáhnout {url}: {posledni_chyba}")


def _oprav_kodovani(r: requests.Response) -> None:
    ct = r.headers.get("content-type", "").lower()
    if "charset" not in ct:
        r.encoding = r.apparent_encoding or "utf-8"
