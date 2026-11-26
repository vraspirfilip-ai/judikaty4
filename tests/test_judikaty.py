"""Offline testy parserů a celého běhu (bez sítě a bez AI)."""
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from judikaty import vystupy
from judikaty.model import datum_iso
from judikaty.zdroje import nejvyssi_soud as ns
from judikaty.zdroje import ustavni_soud as us

NULOVE = {"prodleva_mezi_dotazy_s": 0, "interval_kontroly_davky_s": 0}
UNID1 = "667225CB4F6921ADC1258EB80052A85A"
UNID2 = "AD07ED6EAA54C472C1258EB80052A854"

NS_VYSLEDKY = f"""<html><body><table>
<tr><td><a href="/Judikatura/judikatura_ns.nsf/WebSearch/{UNID1}?openDocument&Highlight=0,">21 Cdo 2128/2025</a></td></tr>
<tr><td><a href="/Judikatura/judikatura_ns.nsf/WebSearch/{UNID2}?openDocument">33 Cdo 2092/2026</a></td></tr>
<tr><td><a href="/Judikatura/judikatura_ns.nsf/WebSearch/{UNID1}?openDocument">dup</a></td></tr>
</table></body></html>"""

NS_DETAIL = """<html><head><script>var x=1;</script></head><body>
<table>
<tr><td>Soud:</td><td>Nejvyšší soud</td></tr>
<tr><td>Datum rozhodnutí:</td><td>10/23/2026</td></tr>
<tr><td>Spisová značka:</td><td>21 Cdo 2128/2025</td></tr>
<tr><td>ECLI:</td><td>ECLI:CZ:NS:2026:21.CDO.2128.2025.1</td></tr>
<tr><td>Typ rozhodnutí:</td><td>USNESENÍ</td></tr>
<tr><td>Heslo:</td><td>Dovolání</td></tr>
<tr><td>Kategorie rozhodnutí:</td><td>E</td></tr>
<tr><td>Datum zveřejnění:</td><td>11/20/2026</td></tr>
</table>
<p>21 Cdo 2128/2025-150</p><p>ČESKÁ REPUBLIKA</p><p>USNESENÍ</p>
<p>Nejvyšší soud České republiky rozhodl v senátě ... takto: Dovolání se odmítá.</p>
<p>Odůvodnění: """ + "Text odůvodnění. " * 50 + "</p></body></html>"

US_TEXT = """<html><head><title>III.ÚS 2449/26 - NALUS</title></head><body>
<div>III.ÚS 2449/26 ze dne 21. 10. 2026</div><div>Česká republika</div><div>NÁLEZ</div>
<div>Ústavního soudu</div><div>Jménem republiky</div>
<p>Ústavní soud rozhodl v senátě ... ECLI:CZ:US:2026:3.US.2449.26.1 ...</p>
<p>""" + "Odůvodnění nálezu. " * 40 + "</p></body></html>"


def _rss(dny_zpet=1):
    dt = format_datetime(datetime.now(timezone.utc) - timedelta(days=dny_zpet))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Souhrn nálezů vyhlášených v 47. týdnu roku 2026</title>
<link>https://www.usoud.cz/aktualne/souhrn</link><pubDate>{dt}</pubDate>
<category>rozhodnuti</category>
<content:encoded><![CDATA[<p>Spisová značka: III. ÚS 2449/26 <a href="https://nalus.usoud.cz:443/Search/GetText.aspx?sz=3-2449-26_1">zde</a></p>
<p><a href="https://nalus.usoud.cz/Search/GetText.aspx?sz=Pl-24-10">zde</a></p>]]></content:encoded>
</item>
<item><title>Přehled jednání</title><link>https://www.usoud.cz/aktualne/jednani</link>
<pubDate>{dt}</pubDate><category>prehled_jednani</category><content:encoded><![CDATA[nic]]></content:encoded></item>
</channel></rss>""".encode()


def test_datumy():
    assert datum_iso("23. 10. 2026") == "2026-10-23"
    assert datum_iso("10/23/2026") == "2026-10-23"
    assert datum_iso("ze dne 12. srpna 2020") == "2020-08-12"
    assert datum_iso("") == ""


def test_ns_seznam_a_detail():
    assert ns.najdi_unid(NS_VYSLEDKY) == [UNID1, UNID2]
    r = ns.zpracuj_detail(UNID1, NS_DETAIL)
    assert r.spisova_znacka == "21 Cdo 2128/2025"
    assert r.ecli == "ECLI:CZ:NS:2026:21.CDO.2128.2025.1"
    assert r.datum_rozhodnuti == "2026-10-23"
    assert r.datum_zverejneni == "2026-11-20"
    assert r.kategorie == "E"
    assert r.forma == "usnesení"
    assert r.text.startswith("ČESKÁ REPUBLIKA")
    assert "var x" not in r.text
    assert ns._spzn_z_ecli("ECLI:CZ:NS:2026:29.ICDO.12.2025.1") == "29 ICdo 12/2025"


def test_ns_url():
    u = ns.url_vyhledavani(ns.VYCHOZI_DOTAZ, 51, 50)
    assert "$$WebSearch1?SearchView&Query=%28%5BARozhodnutiRT%5D" in u
    assert "&Start=51&Count=50" in u and "SearchOrder=3" in u


def test_us_parsery():
    assert us.sz_na_spzn("3-2449-26_1") == "III. ÚS 2449/26"
    assert us.sz_na_spzn("Pl-24-10_1") == "Pl. ÚS 24/10"
    polozky = us.nacti_rss(_rss())
    assert len(polozky) == 2
    assert us.najdi_sz(polozky[0]["obsah"]) == ["3-2449-26_1", "Pl-24-10_1"]
    r = us.zpracuj_text("3-2449-26_1", US_TEXT)
    assert r.datum_rozhodnuti == "2026-10-21"
    assert r.forma == "nález"
    assert r.ecli == "ECLI:CZ:US:2026:3.US.2449.26.1"


@pytest.fixture
def izolovane(tmp_path, monkeypatch):
    import judikaty.__main__ as hlavni
    monkeypatch.setattr(vystupy, "DATA", tmp_path / "data")
    monkeypatch.setattr(vystupy, "ROZHODNUTI", tmp_path / "data" / "rozhodnuti")
    monkeypatch.setattr(vystupy, "PREHLEDY", tmp_path / "prehledy")
    monkeypatch.setattr(vystupy, "WEB", tmp_path / "docs")
    import judikaty.davky
    monkeypatch.setattr(judikaty.davky, "FRONTA", tmp_path / "data" / "fronta")
    monkeypatch.setattr(hlavni, "STAV", tmp_path / "data" / "stav.json")
    monkeypatch.setattr(hlavni, "nacti_nastaveni", lambda: {"obecne": NULOVE})

    class Odp:
        def __init__(self, body):
            self.content = body if isinstance(body, bytes) else body.encode()
            self.text = self.content.decode()

    stranky = {"rss": _rss()}
    stazene = []

    def fake_get(url, **kw):
        if url == us.RSS_URL:
            return Odp(stranky["rss"])
        if "GetText.aspx" in url:
            return Odp(US_TEXT)
        if "$$WebSearch1" in url:
            return Odp(NS_VYSLEDKY if "Start=1&" in url else "<html></html>")
        if "WebSearch/" in url:
            stazene.append(url)
            html = NS_DETAIL.replace("11/20/2026", datetime.now().strftime("%m/%d/%Y"))
            if UNID2 in url:
                html = (html.replace("21 Cdo 2128/2025", "33 Cdo 2092/2026")
                            .replace("21.CDO.2128.2025", "33.CDO.2092.2026")
                            .replace("<td>E</td>", "<td>B</td>"))
            return Odp(html)
        raise AssertionError(url)

    import judikaty.http
    monkeypatch.setattr(judikaty.http, "get", fake_get)
    hlavni.stazene = stazene
    return tmp_path, hlavni


from types import SimpleNamespace as NS_

from judikaty.rozbor import Analyzator as PravyAnalyzator


def _zprava(spzn):
    vstup = {"shrnuti": f"Shrnutí {spzn}.", "klicove_otazky": [{"otazka": "Je platná výpověď, kterou podala třetí osoba bez plné moci?", "odpoved": "Ne, protože …"}],
             "pravni_vety": ["Obecný závěr soudu."], "vysledek": "zamítnuto",
             "pravni_oblast": "civilní proces", "dotcene_predpisy": ["§ 237 o. s. ř."],
             "klicova_slova": ["dovolání"], "vyznam": "střední", "duvod_vyznamu": "x",
             "jen_procesni": False}
    return NS_(content=[NS_(type="tool_use", input=vstup)],
               usage=NS_(input_tokens=1000, output_tokens=100))


class FalesneDavky:
    """Napodobuje client.messages.batches; dávka doběhne až po `kol` dotazech."""
    def __init__(self, kol=1, selhat=()):
        self.kol, self.selhat, self.davky, self.dotazu = kol, set(selhat), {}, 0

    def create(self, requests):
        bid = f"msgbatch_{len(self.davky)}"
        self.davky[bid] = requests
        return NS_(id=bid)

    def retrieve(self, bid):
        self.dotazu += 1
        return NS_(processing_status="ended" if self.dotazu >= self.kol else "in_progress")

    def results(self, bid):
        for req in self.davky[bid]:
            cid = req["custom_id"]
            if cid in self.selhat:
                yield NS_(custom_id=cid, result=NS_(type="errored"))
            else:
                obsah = req["params"]["messages"][0]["content"]
                spzn = obsah.split("Spisová značka: ")[1].split("\n")[0]
                yield NS_(custom_id=cid, result=NS_(type="succeeded", message=_zprava(spzn)))


class FalesnyAnalyzator:
    model = "test"

    def __init__(self, davky=None):
        self.spotreba = {"input_tokens": 0, "output_tokens": 0}
        self.client = NS_(messages=NS_(batches=davky or FalesneDavky()))
        self._a = PravyAnalyzator.__new__(PravyAnalyzator)
        self._a.model, self._a.max_znaku, self._a.max_tokens = "test", 100000, 100

    def parametry(self, r):
        return self._a.parametry(r)

    def zapocti(self, z):
        self.spotreba["input_tokens"] += z.usage.input_tokens

    def zpracuj(self, r):
        return _zprava(r.spisova_znacka).content[0].input


def test_cely_beh(izolovane, monkeypatch):
    tmp, hlavni = izolovane
    import judikaty.rozbor
    monkeypatch.setattr(judikaty.rozbor, "Analyzator", lambda **kw: FalesnyAnalyzator())
    assert hlavni.main([]) == 0

    stav = json.loads((tmp / "data" / "stav.json").read_text())
    assert stav["zname"][f"NS:{UNID1}"]["stav"] == "ok"
    assert stav["zname"]["US:3-2449-26_1"]["stav"] == "ok"
    assert stav["inicializovano"] == {"NS": True, "US": True}
    zaznamy = list((tmp / "data" / "rozhodnuti").rglob("*.json"))
    assert len(zaznamy) == 4
    prehled = next((tmp / "prehledy").rglob("2*.md")).read_text()
    assert "III. ÚS 2449/26" in prehled and "Obecný závěr soudu." in prehled
    assert "Klíčové řešené otázky" in prehled and "bez plné moci?" in prehled
    web = json.loads((tmp / "docs" / "data.json").read_text())
    assert len(web) == 4 and web[0]["otazky"][0]["odpoved"] == "Ne, protože …"
    assert "bez plné moci?" in (tmp / "docs" / "feed.xml").read_text()
    assert "<rss" in (tmp / "docs" / "feed.xml").read_text()

    # druhý běh: nic nového
    assert hlavni.main([]) == 0
    assert len(list((tmp / "data" / "rozhodnuti").rglob("*.json"))) == 4


def test_bez_ai(izolovane):
    tmp, hlavni = izolovane
    assert hlavni.main(["--bez-ai", "--jen", "US"]) == 0
    assert len(list((tmp / "data" / "rozhodnuti").rglob("*.json"))) == 2


def test_dotaz_senaty():
    assert ns.sestav_dotaz({}) == ns.VYCHOZI_DOTAZ
    d = ns.sestav_dotaz({"senaty": [21, 33]})
    assert d == f"({ns.VYCHOZI_DOTAZ}) AND ([spzn1]=21 OR [spzn1]=33)"
    assert ns.senat_ze_spzn("29 ICdo 12/2025") == 29
    assert ns.najdi_odkazy(NS_VYSLEDKY) == [(UNID1, "21 Cdo 2128/2025"), (UNID2, "33 Cdo 2092/2026")]


def test_filtr_senatu_a_kategorii(izolovane, monkeypatch):
    tmp, hlavni = izolovane
    monkeypatch.setattr(hlavni, "nacti_nastaveni", lambda: {
        "obecne": NULOVE,
        "nejvyssi_soud": {"senaty": [33], "kategorie": ["A", "B", "C"]},
    })
    assert hlavni.main(["--bez-ai", "--jen", "NS"]) == 0
    stav = json.loads((tmp / "data" / "stav.json").read_text())["zname"]
    # senát 21 se přeskočil bez stažení detailu
    assert stav[f"NS:{UNID1}"]["stav"] == "preskoceno"
    assert not any(UNID1 in u for u in hlavni.stazene)
    assert stav[f"NS:{UNID2}"]["stav"] == "ok"

    # kategorie: senát 21 povolen, ale jeho rozhodnutí je kategorie E → nezpracuje se
    (tmp / "data" / "stav.json").unlink()
    monkeypatch.setattr(hlavni, "nacti_nastaveni", lambda: {
        "obecne": NULOVE,
        "nejvyssi_soud": {"senaty": [21, 33], "kategorie": ["A", "B", "C"]},
    })
    assert hlavni.main(["--bez-ai", "--jen", "NS"]) == 0
    stav = json.loads((tmp / "data" / "stav.json").read_text())["zname"]
    assert stav[f"NS:{UNID1}"] == {**stav[f"NS:{UNID1}"], "stav": "preskoceno", "duvod": "kategorie E"}
    assert stav[f"NS:{UNID2}"]["stav"] == "ok"


def test_davka_nedobehne_a_vyzvedne_ji_kontrolni_beh(izolovane, monkeypatch):
    tmp, hlavni = izolovane
    import judikaty.rozbor
    falesne = FalesneDavky(kol=10**9, selhat={"US_Pl-24-10_1"})
    monkeypatch.setattr(judikaty.rozbor, "Analyzator", lambda **kw: FalesnyAnalyzator(falesne))
    monkeypatch.setattr(hlavni, "nacti_nastaveni", lambda: {"obecne": {**NULOVE, "max_cekani_na_davku_min": 0}})
    assert hlavni.main([]) == 0
    stav = json.loads((tmp / "data" / "stav.json").read_text())
    assert list(stav["davky"]) == ["msgbatch_0"]
    assert stav["zname"]["US:3-2449-26_1"]["stav"] == "v_davce"
    assert len(list((tmp / "data" / "fronta").glob("*.json"))) == 4
    assert not list((tmp / "data" / "rozhodnuti").rglob("*.json"))

    # kontrolní běh: dávka mezitím doběhla
    falesne.kol = 0
    assert hlavni.main(["--jen-vyzvednout"]) == 0
    stav = json.loads((tmp / "data" / "stav.json").read_text())
    assert stav["davky"] == {}
    assert stav["zname"]["US:3-2449-26_1"]["stav"] == "ok"
    assert stav["zname"]["US:Pl-24-10_1"]["stav"] == "chyba"   # zkusí se znovu příště
    assert len(list((tmp / "data" / "rozhodnuti").rglob("*.json"))) == 3
    assert not list((tmp / "data" / "fronta").glob("*.json"))
    assert "Obecný závěr soudu." in next((tmp / "prehledy").rglob("2*.md")).read_text()


def test_okamzite(izolovane, monkeypatch):
    tmp, hlavni = izolovane
    import judikaty.rozbor
    monkeypatch.setattr(judikaty.rozbor, "Analyzator", lambda **kw: FalesnyAnalyzator())
    assert hlavni.main(["--okamzite", "--jen", "US"]) == 0
    assert len(list((tmp / "data" / "rozhodnuti").rglob("*.json"))) == 2


def test_prvni_beh_od_data(izolovane, monkeypatch):
    tmp, hlavni = izolovane
    from datetime import date
    def nastav(od):
        monkeypatch.setattr(hlavni, "nacti_nastaveni", lambda: {
            "obecne": {**NULOVE, "prvni_beh_od": od, "prvni_beh_podle": "zverejneni"},
            "nejvyssi_soud": {"prvni_beh_max": 1}})
    # od předevčírka: vše zveřejněné v posledních dnech projde, limit prvni_beh_max se nepoužije
    nastav((date.today() - timedelta(days=3)).isoformat())
    assert hlavni.main(["--bez-ai"]) == 0
    stav = json.loads((tmp / "data" / "stav.json").read_text())["zname"]
    assert all(v["stav"] == "ok" for v in stav.values()), stav
    assert len(stav) == 4
    zaznam = json.loads(next((tmp / "data" / "rozhodnuti" / "US").rglob("*.json")).read_text())
    assert zaznam["datum_zverejneni"]  # z RSS

    # od zítřka: nic se nezpracuje
    for f in (tmp / "data").rglob("*.json"):
        f.unlink()
    nastav((date.today() + timedelta(days=1)).isoformat())
    assert hlavni.main(["--bez-ai"]) == 0
    stav = json.loads((tmp / "data" / "stav.json").read_text())["zname"]
    assert stav and all(v["stav"] == "preskoceno" for v in stav.values()), stav


from judikaty import filtry
from judikaty.model import Rozhodnuti

VSE = ["pracovni", "dedicke", "restituce"]


def _r(zahlavi, oduvodneni="", **extra):
    text = f"ČESKÁ REPUBLIKA\nROZSUDEK\nNejvyšší soud rozhodl {zahlavi}, takto:\nI. Dovolání se zamítá.\n" \
           f"Odůvodnění:\n{oduvodneni}"
    return Rozhodnuti(id="NS:X", soud="NS", url="", spisova_znacka="21 Cdo 1/2026", text=text, extra=extra)


@pytest.mark.parametrize("zahlavi, ocekavano", [
    ("ve věci žalobce J. N. proti žalovanému ABC s. r. o. o neplatnost výpovědi z pracovního poměru",
     "pracovní právo"),
    ("ve věci žalobkyně o zaplacení 50 000 Kč náhrady mzdy", "pracovní právo"),
    ("v řízení o pozůstalosti po zůstaviteli J. N., zemřelém dne 1. 1. 2020", "dědické právo"),
    ("ve věci žalobce proti žalované o určení, že nemovitost patří do pozůstalosti", "dědické právo"),
    ("ve věci žalobce proti Státnímu pozemkovému úřadu o vydání nemovitostí", "restituce"),
    ("ve věci žalobců o převod náhradních pozemků", "restituce"),
])
def test_filtr_vyradi(zahlavi, ocekavano):
    assert filtry.vyrazujici_oblast(_r(zahlavi), VSE) == ocekavano


@pytest.mark.parametrize("zahlavi, oduvodneni", [
    ("ve věci žalobce proti žalované bance o zaplacení 120 000 Kč z úvěrové smlouvy",
     "Žalobce byl zaměstnancem jiné firmy; jeho dědic se řízení neúčastnil."),
    ("ve věci žalobkyně o určení vlastnického práva k pozemku p. č. 123", "Kupní smlouva je platná."),
    ("ve věci žalobce o náhradu škody z dopravní nehody", ""),
    ("ve věci žalobce J. N., zemřelého, za něhož pokračují jeho dědici, o zaplacení 10 000 Kč", ""),
    ("ve věci žalobce proti žalovanému o vydání věci (automobilu)", ""),
])
def test_filtr_nevyradi(zahlavi, oduvodneni):
    # zmínky v odůvodnění nevadí – rozhoduje předmět řízení
    assert filtry.vyrazujici_oblast(_r(zahlavi, oduvodneni), VSE) is None


def test_filtr_podle_metadat_a_vlastnich_vzoru():
    r = _r("ve věci žalobce o zaplacení 10 000 Kč", dotcene_predpisy="§ 52 písm. g) předpisu č. 262/2006Sb.")
    assert filtry.vyrazujici_oblast(r, ["pracovni"]) == "pracovní právo"
    assert filtry.vyrazujici_oblast(r, []) is None
    r2 = _r("ve věci insolvenčního správce dlužníka o určení pravosti pohledávky")
    assert filtry.vyrazujici_oblast(r2, VSE, [r"insolvenční"]).startswith("vlastní vzor")
    with pytest.raises(ValueError):
        filtry.vyrazujici_oblast(r, ["neexistuje"])


def test_us_jen_nalezy_a_vyrazene_v_prehledu(izolovane, monkeypatch):
    tmp, hlavni = izolovane
    import judikaty.zdroje.ustavni_soud as usm
    puvodni = usm.zpracuj_text
    def jako_usneseni(sz, html, kontext=None):
        if sz.startswith("Pl"):
            html = html.replace("NÁLEZ", "USNESENÍ")
        return puvodni(sz, html, kontext)
    monkeypatch.setattr(usm, "zpracuj_text", jako_usneseni)
    import judikaty.http
    puvodni_get = judikaty.http.get
    def get(url, **kw):
        o = puvodni_get(url, **kw)
        if "WebSearch/" + UNID2 in url:  # 33 Cdo – udělej z něj pracovní spor
            o.text = o.text.replace("rozhodl v senátě ...", "rozhodl ve věci o neplatnost výpovědi z pracovního poměru")
        return o
    monkeypatch.setattr(judikaty.http, "get", get)
    monkeypatch.setattr(hlavni, "nacti_nastaveni", lambda: {
        "obecne": NULOVE, "nejvyssi_soud": {"vyloucit": {"oblasti": VSE}}})
    assert hlavni.main(["--bez-ai"]) == 0
    stav = json.loads((tmp / "data" / "stav.json").read_text())["zname"]
    assert stav["US:3-2449-26_1"]["stav"] == "ok"
    assert stav["US:Pl-24-10_1"] == {**stav["US:Pl-24-10_1"], "stav": "preskoceno", "duvod": "forma usnesení"}
    assert stav[f"NS:{UNID2}"]["stav"] == "vyrazeno"
    assert stav[f"NS:{UNID1}"]["stav"] == "ok"
    prehled = next((tmp / "prehledy").rglob("2*.md")).read_text()
    assert "Vyřazeno filtrem oblastí (1)" in prehled and "33 Cdo 2092/2026" in prehled


@pytest.mark.parametrize("nazev, klic", [
    ("rodinne veci", "rodinne"), ("Rodinné právo", "rodinne"), ("pracovněprávní spory", "pracovni"),
    ("dědictví", "dedicke"), ("restituce", "restituce"), ("SJM", "sjm"), ("pracovni", "pracovni"),
])
def test_aliasy_oblasti(nazev, klic):
    assert filtry.normalizuj_oblast(nazev) == klic


@pytest.mark.parametrize("zahlavi, ocekavano", [
    ("ve věci péče o nezletilou A. B. a výživného", "rodinné právo"),
    ("ve věci žalobkyně o rozvod manželství", "rodinné právo"),
    ("ve věci žalobce o popření otcovství", "rodinné právo"),
    ("ve věci žalobkyně o vypořádání společného jmění manželů", "společné jmění manželů"),
])
def test_filtr_rodinne(zahlavi, ocekavano):
    assert filtry.vyrazujici_oblast(_r(zahlavi), ["rodinne veci", "sjm"]) == ocekavano


def test_rodinne_nevyradi_obecny_spor():
    assert filtry.vyrazujici_oblast(_r("ve věci žalobce o zaplacení kupní ceny 80 000 Kč"), ["rodinne"]) is None


def test_popis_chyby_davky():
    from judikaty.davky import popis_chyby
    r = NS_(type="errored", error=NS_(type="error", error=NS_(type="invalid_request_error",
                                                              message="Your credit balance is too low")))
    assert popis_chyby(r) == "invalid_request_error: Your credit balance is too low"
    assert popis_chyby(NS_(type="expired", error=None)) == "dávka nedoběhla do 24 hodin"


VASE = ["pracovni", "dedicke", "restituce", "rodinne veci", "soudni uschovy", "nekala soutez",
        "arbitraze", "dusevni vlastnictvi"]


@pytest.mark.parametrize("zahlavi, ocekavano", [
    ("ve věci navrhovatele o vydání předmětu soudní úschovy", "soudní úschovy"),
    ("ve věci žalobce o zdržení se jednání nekalé soutěže", "nekalá soutěž"),
    ("ve věci žalobkyně o zrušení rozhodčího nálezu", "rozhodčí řízení"),
    ("ve věci žalobce o ochranu práva k ochranné známce", "duševní vlastnictví"),
    ("ve věci žalobce o zaplacení autorské odměny", "duševní vlastnictví"),
])
def test_vase_nove_oblasti(zahlavi, ocekavano):
    assert filtry.vyrazujici_oblast(_r(zahlavi), VASE) == ocekavano


@pytest.mark.parametrize("zahlavi", [
    "ve věci žalobce proti žalované o zaplacení 300 000 Kč z kupní smlouvy",
    "ve věci žalobkyně o určení neplatnosti smlouvy o převodu obchodního podílu",
    "ve věci žalobce o náhradu škody způsobené jednatelem společnosti",
])
def test_vase_oblasti_nevyradi_obchodni_spory(zahlavi):
    assert filtry.vyrazujici_oblast(_r(zahlavi), VASE) is None
