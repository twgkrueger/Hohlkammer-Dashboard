# Hohlkammer Dashboard

Preisvergleich für Hohlkammerplakate **DIN A1, 10 Lochbohrungen, einseitig 4/0** bei sieben Online-Druckereien:
Flyeralarm, WIRmachenDRUCK, Saxoprint, Drucknische, highway2print, wahlplakatshop und jajabo.
Auflagen: 1, 100, 500, 1.000 und 10.000 Stück. Alle Preise inklusive Standardversand innerhalb Deutschlands.

## Aufbau

| Datei | Zweck |
|---|---|
| `index.html` | Die Webseite (Ranking, Preisverlauf, alle Datenstände) |
| `data/prices.json` | Alle gespeicherten Preise, ein Datenstand pro Tag |
| `scraper/fetch_prices.py` | Fragt die sieben Shops ab und schreibt `data/prices.json` |
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

- **Drucknische:** 12-fach statt 10-fach Lochung; Preis wird im Browser berechnet, daher nutzt das Skript Playwright.
- **highway2print:** Versand kommt extra und wird anhand der Gewichtstabelle des Shops (0,225 kg pro Plakat) hinzugerechnet.
- **wahlplakatshop:** online 10 bis 5.000 Stück.
- **jajabo:** Staffelpreise stehen als Tabelle auf der Produktseite, 3 mm Platte, Versand gratis.
- **Saxoprint:** online höchstens 1.000 Stück. **Flyeralarm:** höchstens 5.000 Stück.

## Lokal testen (optional)

```bash
pip install -r scraper/requirements.txt
python -m playwright install chromium
python scraper/fetch_prices.py
python -m http.server 8000   # dann http://localhost:8000 öffnen
```
