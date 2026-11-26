# Judikáty bot ⚖️

Jednou týdně (v pátek v 17:00) automaticky stáhne nová rozhodnutí **Nejvyššího soudu** a **Ústavního soudu**,
nechá je zpracovat umělou inteligencí (Claude) a uloží:

- **shrnutí** (o co šlo, jak a proč soud rozhodl),
- **klíčové řešené otázky** – zobecněné hmotněprávní otázky včetně právně rozhodných okolností
  (např. *„Je platná výpověď z pracovního poměru, kterou jménem zaměstnavatele podala třetí osoba,
  jež se neprokázala plnou mocí?“*) a jak je soud zodpověděl,
- **právní věty** ve stylu Sbírky soudních rozhodnutí a stanovisek,
- výsledek, právní oblast, dotčené předpisy, hesla a odhad významu.

Výsledky najdete na třech místech:

| Kde | Co |
|---|---|
| `prehledy/` | týdenní přehled v Markdownu, čitelný přímo na GitHubu (`prehledy/README.md` je rejstřík) |
| `docs/` | webová stránka s vyhledáváním a filtry (GitHub Pages) + RSS kanál `feed.xml` |
| `data/rozhodnuti/` | JSON záznam každého rozhodnutí (pro další zpracování) |

Všechno běží zdarma na GitHub Actions. Platíte jen za Claude API, a to přes **Batch API za poloviční cenu**.

---

## Zprovoznění (cca 10 minut, bez programování)

Kroky dělejte v tomto pořadí – bot se spustí sám hned po nahrání souborů, takže klíč
a oprávnění musí být nastavené předem.

1. **Vytvořte prázdný repozitář na GitHubu** (může být soukromý), zatím do něj nic nenahrávejte.
2. **API klíč:** na <https://console.anthropic.com> si vytvořte klíč. V repozitáři pak
   *Settings → Secrets and variables → Actions → New repository secret*:
   název `ANTHROPIC_API_KEY`, hodnota = váš klíč.
3. **Oprávnění:** *Settings → Actions → General → Workflow permissions* → zvolte
   **Read and write permissions** a uložte.
4. **Před nahráním** zkontrolujte v `nastaveni.toml` hlavně `senaty` a `prvni_beh_od`.
5. **Nahrajte soubory** (*Add file → Upload files*, přetáhněte všechny soubory a složky včetně `.github`).
   > Tip: složka `.github` je na Macu/Linuxu skrytá. Nejjednodušší je zip rozbalit a nahrát
   > přes `git`, nebo na GitHubu vytvořit soubor `.github/workflows/tydne.yml` ručně a vložit do něj obsah.

   Tím se automaticky spustí **první běh** (sledujte na záložce *Actions*). Zpracuje rozhodnutí
   zveřejněná od data `prvni_beh_od` (výchozí 23. 11. 2026). Výsledky se objeví ve složkách
   `prehledy/` a `data/`, jakmile doběhne dávka – obvykle do hodiny.
   Pokud jste klíč zapomněli nastavit, běh jen vypíše upozornění; doplňte klíč a spusťte
   *Actions → Týdenní judikatura → Run workflow* ručně.
6. **Webová stránka (volitelné):** *Settings → Pages → Source: Deploy from a branch*,
   větev `main`, složka `/docs`. Adresu stránky pak vložte do `nastaveni.toml` jako
   `adresa_webu` (kvůli RSS). U soukromého repozitáře vyžaduje Pages placený GitHub účet.

Dál už bot běží sám každý pátek v 17:00 a zpracuje vždy jen novinky. Další nahrávání nebo
úpravy souborů ho znovu nespouštějí.

## Nastavení

Vše je v souboru **`nastaveni.toml`** (upravíte přímo na GitHubu tužkou ✏️). Nejdůležitější:

- `[nejvyssi_soud] senaty` – **které senáty NS vás zajímají**, např. `senaty = [21, 22, 25, 33]`
  (číslo na začátku spisové značky). Omezení se posílá přímo do vyhledávání NS, takže rozhodnutí
  ostatních senátů se vůbec nestahují. Prázdný seznam `[]` = všechny senáty.
- `[nejvyssi_soud] vyloucit.oblasti` – oblasti, které vás nezajímají, i když je řeší vámi zvolené
  senáty. Výchozí `["pracovni", "dedicke", "restituce"]`, dále lze přidat `"rodinne"` a `"sjm"`. Pozná se z předmětu řízení v záhlaví
  rozhodnutí a z metadat NS (heslo, dotčené předpisy), ještě **před** odesláním Claudovi – nic to nestojí.
  Seznam vyřazených rozhodnutí je na konci každého přehledu, abyste mohl filtr zkontrolovat.
  Další výrazy lze doplnit do `vyloucit.vlastni_vzory`.
- `[nejvyssi_soud] kategorie` – výchozí je `["A", "B", "C"]`, tedy jen judikatorně významná
  rozhodnutí (A = nejvýznamnější … E = ostatní). Kategorii NS uvádí až v detailu rozhodnutí,
  proto se detail stáhne, ale rozhodnutí kategorie D a E se AI vůbec nepošlou. Když kategorie
  ještě není přidělena, bot to zkusí znovu příští týden.

- `model` – který Claude zpracovává rozhodnutí (`claude-sonnet-5-5` je dobrý kompromis,
  `claude-haiku-5-5` je levnější, `claude-opus-5-5` nejpečlivější). Lze přepsat i proměnnou
  `CLAUDE_MODEL` v *Settings → Secrets and variables → Actions → Variables*.
- `max_rozhodnuti_za_beh` – strop na jeden běh (nezpracované zůstanou na příští týden).
- `dotaz` – vlastní filtr pro NS, např. jen civilní dovolání.

## Batch API (poloviční cena)

Rozbory se posílají Claudovi jednou dávkou přes Message Batches API, které stojí polovinu běžné ceny.
Výsledky ale nejsou okamžitě: dávka obvykle doběhne do hodiny, nejpozději do 24 hodin.

- Pondělní běh stáhne rozhodnutí, odešle dávku a čeká na výsledky až 4 hodiny
  (`max_cekani_na_davku_min`). Přehled je tedy obvykle hotový v pátek večer.
- Pokud dávka do té doby nedoběhne, vyzvednou ji **kontrolní běhy** (pátek kolem 20:30 a 23:30,
  sobota ráno). Když na nic nečekají, skončí během pár sekund.
- Rozhodnutí čekající na výsledek leží ve složce `data/fronta/`. Rozbory, které v dávce selžou,
  se zkusí znovu příští týden.
- Ručně můžete spustit *Actions → Týdenní judikatura → Run workflow* s režimem:
  `jen-vyzvednout` (jen vyzvednout hotovou dávku) nebo `okamzite` (bez dávky, výsledek hned, plná cena).
- Dávkové zpracování vypnete v `nastaveni.toml`: `davkove_zpracovani = false`.

## Náklady

Díky filtru kategorií A–C a senátů jde týdně typicky o desítky rozhodnutí; běžné rozhodnutí má zhruba 5–15 tisíc tokenů.
Se Sonnetem 5.5 přes Batch API vyjde jedno rozhodnutí zhruba na 1,5 centu, tedy při 20–50 rozhodnutích
týdně asi 0,35–0,90 USD týdně. Přesnou spotřebu tokenů každého běhu uvidíte v souhrnu na záložce *Actions*.
Dál ušetříte užším výběrem senátů nebo levnějším modelem.

## Jak to funguje

- **Nejvyšší soud:** databáze <https://rozhodnuti.nsoud.cz> nemá API, takže bot používá stejné
  vyhledávací adresy jako oficiální formulář, řadí od nejnovějších a stahuje detail každého
  nového rozhodnutí (spisová značka, ECLI, data, kategorie, plný text).
- **Ústavní soud:** z RSS <https://www.usoud.cz/rss> (tiskové zprávy a týdenní souhrny
  vyhlášených nálezů) bere odkazy do databáze NALUS a stahuje plné texty.
  Zpracovávají se **jen nálezy** (`jen_nalezy = true`); usnesení se přeskočí.
- Co už bylo zpracováno, je zapsáno v `data/stav.json`. Když stažení nebo rozbor selže,
  zkusí se to znovu příští týden (max. 3×).
- Mezi dotazy na weby soudů je prodleva 1,5 s, aby bot servery nezatěžoval.

## Proč dva časy v plánu

GitHub plánuje v UTC a nezná letní čas. Workflow se proto v pátek spouští v 15:00 i 16:00 UTC
a první krok nechá proběhnout jen ten běh, který odpovídá 17:00 pražského času. Druhý se hned
ukončí (v Actions uvidíte krátký „přeskočený“ běh, to je v pořádku). GitHub může naplánované
běhy při vytížení o pár desítek minut zpozdit.

## Když něco nefunguje

- Běh selže, pokud nefunguje ani jeden zdroj, a GitHub vám pošle e-mail. Podrobnosti najdete
  v logu na záložce *Actions*.
- Hláška *„vyhledávání nevrátilo žádné odkazy“* znamená, že NS změnil strukturu webu – je potřeba
  upravit `judikaty/zdroje/nejvyssi_soud.py`.
- GitHub u veřejných repozitářů po 60 dnech bez aktivity naplánované běhy pozastaví. Pokud vám
  přijde e-mail, stačí na záložce *Actions* workflow znovu povolit.

## Spuštění na vlastním počítači

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m judikaty            # vše (přes Batch API)
python -m judikaty --okamzite # bez dávky, výsledky hned
python -m judikaty --jen-vyzvednout  # jen vyzvednout dokončenou dávku
python -m judikaty --bez-ai   # jen stáhnout, bez AI
python -m judikaty --jen US   # jen Ústavní soud
pip install pytest && pytest  # testy
```

## Upozornění

Shrnutí a právní věty vytváří AI. Nejsou to oficiální právní věty soudů a mohou obsahovat chyby.
Před použitím vždy ověřte text rozhodnutí v originále (odkaz je u každého záznamu).
Data pocházejí z veřejných databází Nejvyššího soudu a Ústavního soudu.
