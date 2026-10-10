# Hohlkammer Dashboard

Preisvergleich für Hohlkammerplakate **DIN A1 und DIN A0, 10 Lochbohrungen, einseitig 4/0** bei elf Online-Druckereien:
Flyeralarm, WIRmachenDRUCK, Saxoprint, Drucknische, highway2print, wahlplakatshop, jajabo, print24, maxxprint, Bannerkönig und myDisplays.
Auflagen: 1, 100, 500, 1.000, 5.000 und 10.000 Stück. Alle Preise inklusive Standardversand innerhalb Deutschlands.

Zusätzlich: **18/1-Großflächenplakate** (356 × 252 cm, Affichenpapier mit blauer Rückseite, einseitig 4/0) in kleinen Auflagen von **1, 3, 5 und 10 Stück**
bei Flyeralarm, WIRmachenDRUCK, highway2print, wahlplakatshop, maxxprint, Bannerkönig und myDisplays. Direktlink zur Ansicht: `…/#18/1`.

## Aufbau

| Datei | Zweck |
|---|---|
| `index.html` | Die Webseite (Ranking, Preisverlauf, alle Datenstände) |
| `data/prices.json` | Alle gespeicherten Preise, ein Datenstand pro Tag |
| `scraper/fetch_prices.py` | Fragt die elf Shops ab und schreibt `data/prices.json` |
| `.github/workflows/update-prices.yml` | Startet die Abfrage täglich und auf Knopfdruck |

## Einrichtung (einmalig)

1. **GitHub Pages einschalten:** Repository → *Settings* → *Pages* → *Source*: „Deploy from a branch“, Branch `main`, Ordner `/ (root)` → *Save*.
   Die Seite ist danach unter `https://<konto>.github.io/<repository>/` erreichbar.
2. **Actions erlauben:** Repository → *Settings* → *Actions* → *General* → unter „Workflow permissions“ **Read and write permissions** wählen → *Save*.
3. **Ersten Abruf starten:** Reiter *Actions* → „Preise aktualisieren“ → *Run workflow*.

## Preise aktualisieren

- **Automatisch:** jeden Morgen gegen 6:15 Uhr (Sommerzeit).
- **Von Hand:** Knopf „Preise aktualisieren“ auf der Seite oder *Actions* → „Preise aktualisieren“ → *Run workflow*. Nur wer Schreibrechte am Repository hat, kann das auslösen. Nach etwa zwei Minuten ist der neue Stand auf der Seite.

Schlägt ein Shop fehl (z. B. weil er seine Seite umgebaut hat), übernimmt das Skript dessen letzten Preis und vermerkt den Fehler. Das Dashboard zeigt das als Hinweis. Fehlerdetails stehen im Protokoll des jeweiligen Actions-Laufs.

## Hinweise zu einzelnen Shops

- **Drucknische:** 12-fach statt 10-fach Lochung (A1 und A0); Preis wird im Browser berechnet, daher nutzt das Skript Playwright.
- **highway2print:** Versand kommt extra und wird anhand der Gewichtstabelle des Shops hinzugerechnet (A1 0,225 kg, A0 0,45 kg pro Plakat). A0 erst ab 2 Stück. Für 10.000 × A0 (4,5 t) reicht die Tabelle nicht, der Versand ist dort geschätzt.
- **wahlplakatshop:** online 10 bis 5.000 Stück; A0 nur mit 12-fach-Stanzung.
- **jajabo:** Staffelpreise stehen als Tabelle auf der Produktseite, 3 mm Platte, Versand gratis.
- **print24:** Preis-Schnittstelle mit kurzlebigem Token; alle Auflagen bis 10.000, Versand inklusive.
- **maxxprint:** Preis über Preisregeln des Shops; höchstens 100 Stück je Motiv, daher nur 1 und 100 Stück.
- **Bannerkönig:** keine Lochung wählbar; Versand erst im Warenkorb, eingerechnet ist nur der Mindestbetrag von 6,90 € netto.
- **myDisplays:** keine 10-fach-Lochung (nur 4 Eckbohrungen); Versand geschätzt mit 9,90 € je 30-kg-Paket.
- **Salierdruck** (angefragt) bietet Wahlplakate nur in 120×80, 140×100 und 170×120 cm an und ist deshalb nicht enthalten.
- **Saxoprint:** online höchstens 1.000 Stück. **Flyeralarm:** höchstens 5.000 Stück.

### 18/1-Großflächenplakate

| Shop | Material | Hinweis |
|---|---|---|
| Flyeralarm | 115 g Affichenpapier | eigenes Produkt „18/1 Plakate“, Versand inklusive |
| WIRmachenDRUCK | 120 g Affichenpapier Blueback | Versand inklusive |
| highway2print | 115 g Plakatpapier Blueback | 4 Teile; Versand nach Gewichtstabelle (1,077 kg pro Plakat) |
| wahlplakatshop | 115 g Affichenpapier | 4 Teile; 1–100 Stück, Versand inklusive |
| maxxprint | 115 g Blueback-Affichenpapier | 4 Teile, verklebefertig gemappt; höchstens 50 Stück je Motiv |
| Bannerkönig | 120 g Blueback-Affichenpapier | Versand erst im Warenkorb, eingerechnet nur 6,90 € netto |
| myDisplays | 130 g Affichenpapier Blueback | Freiformat 356 × 252 cm, gedruckt in Bahnen bis 130 cm; Versand geschätzt |

Nicht enthalten: **print24** (18/1 erst ab 100 Stück), **Saxoprint**, **Drucknische** und **jajabo** (kein 18/1-Format).

## Lokal testen (optional)

```bash
pip install -r scraper/requirements.txt
python -m playwright install chromium
python scraper/fetch_prices.py
python -m http.server 8000   # dann http://localhost:8000 öffnen
```
