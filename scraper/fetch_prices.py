"""Fragt die Preise für Hohlkammerplakate DIN A1 (10 Bohrungen, 4/0) bei sieben
Online-Druckereien ab und schreibt einen Datenstand nach data/prices.json.

Alle Preise sind netto bzw. brutto INKLUSIVE Standardversand innerhalb Deutschlands.
Schlägt ein Shop fehl, wird sein letzter bekannter Preis übernommen und der Fehler
im Datenstand vermerkt, damit das Dashboard vollständig bleibt.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "prices.json"
QTYS = [1, 100, 500, 1000, 10000]
VAT = 1.19
TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)


def r2(x: float) -> float:
    return round(x + 1e-9, 2)


def de_number(s: str) -> float:
    """'1.558,40' -> 1558.4"""
    return float(s.strip().replace(".", "").replace(",", "."))


def item(shop, material, qty, net, gross, url, notes=None):
    d = {"shop": shop, "material": material, "qty": qty, "net": r2(net), "gross": r2(gross), "url": url}
    if notes:
        d["notes"] = notes
    return d


# --------------------------------------------------------------------------- Flyeralarm
FLA_URL = "https://www.flyeralarm.com/de/p/wahlplakate-9456837.html"
FLA_API = (
    "https://www.flyeralarm.com/de/p/9456837/variant?"
    "selection[att.format.conf]=value.dinA1594X84Cm.conf"
    "&selection[att.material.conf]={mat}"
    "&selection[att.farbigkeit.conf]=value.40farbig.conf"
)
FLA_MATERIALS = {
    "value.450GHohlkammerplatteBasic.conf": "450 g Hohlkammerplatte Basic",
    "value.450GHohlkammerplatte.conf": "450 g Hohlkammerplatte",
    "value.450GRecyclingHohlkammerplatte.conf": "450 g Recycling-Hohlkammerplatte",
}


def fetch_fla():
    out = []
    for mat, name in FLA_MATERIALS.items():
        r = session.get(FLA_API.format(mat=mat), timeout=TIMEOUT, headers={"Accept": "application/json"})
        r.raise_for_status()
        quantities = r.json()["variantPrice"]["quantities"]
        by_amount = {q["amount"]: q["deliveryTypes"]["standard"] for q in quantities}
        for qty in QTYS:
            p = by_amount.get(qty)
            if p:  # Preise in Cent
                out.append(item("fla", name, qty, p["salesPriceNet"] / 100, p["salesPriceGross"] / 100, FLA_URL))
    if not out:
        raise RuntimeError("keine Preise in der Antwort")
    return out


# ----------------------------------------------------------------------- WIRmachenDRUCK
WMD_URL = (
    "https://www.wir-machen-druck.de/"
    "wahlplakat-auf-hohlkammerplatte-din-a1-einseitig-40farbig-bedruckt-mit-10-bohrungen.html"
)


def fetch_wmd():
    r = session.get(WMD_URL, timeout=TIMEOUT)
    r.raise_for_status()
    prices = {}
    for qty_s, net_s in re.findall(r"([\d.]+) Stück \(([\d.,]+) Euro netto\)", r.text):
        prices.setdefault(int(qty_s.replace(".", "")), de_number(net_s))
    out = []
    for qty in QTYS:
        if qty in prices:
            net = prices[qty]
            out.append(item("wmd", "Hohlkammerplatte 3 mm", qty, net, net * VAT, WMD_URL))
    if not out:
        raise RuntimeError("Auflagenliste nicht gefunden")
    return out


# ---------------------------------------------------------------------------- Saxoprint
SAX_URL = "https://www.saxoprint.de/plakate/hohlkammerplakate-drucken"
SAX_API = "https://api.saxoprint.de/product-configuration/get-product-prices"
SAX_MAX = 1000  # im Shop online höchstens 1.000 Stück
SAX_CONFIG = [
    (6, 1476), (44, None), (152, 1433), (9, 42), (10, 120), (7, 76), (8, 1133), (48, 1436),
    (64, 1438), (153, 1477), (1, 222), (13, 205), (102, 1055), (2, 179), (27, 188),
]


def fetch_sax():
    out = []
    for qty in [q for q in QTYS if q <= SAX_MAX]:
        body = {
            "productGroupId": 1476,
            "customerNumber": 0,
            "propertyConfiguration": [
                {"propertyId": pid, "value": qty if pid == 44 else val} for pid, val in SAX_CONFIG
            ],
            "printRuns": [],
            "deliverySplitPrintRuns": [],
        }
        r = session.post(SAX_API, json=body, timeout=TIMEOUT, headers={"Origin": "https://www.saxoprint.de"})
        r.raise_for_status()
        j = r.json()
        out.append(item("sax", "PP-Hohlkammerplatte 2,5 mm", qty, float(j["priceNet"]), float(j["priceGross"]), SAX_URL))
    return out


# -------------------------------------------------------------------------- Drucknische
DN_URL = "https://drucknische.de/products/hohlkammerplakate-din-a1"
DN_MAX = 1000
DN_NOTES = ["12-fach statt 10-fach Lochung"]


def fetch_dn():
    """Der Preis wird im Browser berechnet (Rechner-Plugin), daher Playwright."""
    from playwright.sync_api import sync_playwright

    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="de-DE", user_agent=HEADERS["User-Agent"])
        page.goto(DN_URL, wait_until="networkidle", timeout=60000)
        selector = 'input[name="properties[Anzahl der gewünschten Plakate]"]'
        page.wait_for_selector(selector, state="attached", timeout=30000)
        for qty in [q for q in QTYS if q <= DN_MAX]:
            page.evaluate(
                """([sel, v]) => {
                    const inp = document.querySelector(sel);
                    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    set.call(inp, String(v));
                    for (const e of ['input', 'change', 'keyup', 'blur']) inp.dispatchEvent(new Event(e, {bubbles: true}));
                }""",
                [selector, qty],
            )
            page.wait_for_timeout(3000)
            text = page.inner_text("body")
            m = re.search(r"Preis inkl\. gesetzl\. Mwst\.\s*€\s*([\d.,]+)", text)
            if not m:
                raise RuntimeError("Preis auf der Seite nicht gefunden")
            gross = float(m.group(1).replace(",", ""))  # Format "€ 2203.88"
            out.append(item("dn", "PP-Hohlkammerplatte 2,5 mm", qty, gross / VAT, gross, DN_URL, DN_NOTES))
        browser.close()
    return out


# ------------------------------------------------------------------------ highway2print
H2P_URL = "https://www.highway2print.de/produkt/hohlkammerplakat-din-a1/"
H2P_AJAX = "https://www.highway2print.de/wp-admin/admin-ajax.php"
H2P_KG_PER_PIECE = 0.225
# Versand brutto laut https://www.highway2print.de/versandarten/ (Stand 10/2026)
H2P_DPD = [(3, 10.71), (10, 14.28), (15, 17.85), (20, 21.42), (25, 23.80), (30, 29.75)]
H2P_FREIGHT = [
    (100, 91.63), (200, 116.62), (300, 128.52), (400, 183.26), (500, 224.91), (600, 249.90),
    (700, 265.37), (800, 284.41), (900, 297.50), (1000, 314.16), (1250, 364.14), (1500, 383.18),
    (1750, 421.26), (2000, 458.15), (2500, 529.55),
]


def h2p_shipping_gross(qty):
    kg = qty * H2P_KG_PER_PIECE
    for limit, price in H2P_DPD:
        if kg <= limit:
            return price, False
    for limit, price in H2P_FREIGHT:
        if kg <= limit:
            return price, True
    raise RuntimeError(f"Versand für {kg:.0f} kg nicht in der Tabelle")


def fetch_h2p():
    page = session.get(H2P_URL, timeout=TIMEOUT)
    page.raise_for_status()
    m = re.search(r'highwayOfferNonce\s*=\s*"([^"]+)"', page.text)
    if not m:
        raise RuntimeError("Nonce nicht gefunden")
    nonce = m.group(1)
    out = []
    for qty in QTYS:
        data = {
            "action": "highway_live_offer", "nonce": nonce, "product_id": "180", "total_qty": str(qty),
            "motif_count": "1", "lochung": "10-fach-Lochung", "datencheck": "ohne",
        }
        r = session.post(H2P_AJAX, data=data, timeout=TIMEOUT, headers={"Referer": H2P_URL})
        r.raise_for_status()
        j = r.json()
        if not j.get("success"):
            raise RuntimeError(f"Antwort ohne Erfolg für {qty} Stück")
        net_goods = de_number(re.sub(r"<[^>]+>|&nbsp;|&euro;|€", "", j["data"]["net_total"]))
        ship_gross, freight = h2p_shipping_gross(qty)
        net = net_goods + ship_gross / VAT
        note = "Versand per Spedition, nach Gewichtstabelle berechnet" if freight else "Versand nach Gewichtstabelle berechnet"
        out.append(item("h2p", "Hohlkammerplatte 2,5 mm", qty, net, net * VAT, H2P_URL, [note]))
    return out


# ----------------------------------------------------------------------- wahlplakatshop
WPS_URL = "https://www.wahlplakatshop.de/product/hohlkammerplakate-a1/"
WPS_AJAX = "https://www.wahlplakatshop.de/?wc-ajax=get_variation"
WPS_MIN, WPS_MAX = 10, 5000


def fetch_wps():
    out = []
    for qty in [q for q in QTYS if WPS_MIN <= q <= WPS_MAX]:
        r = session.post(WPS_AJAX, data={"product_id": "24", "attribute_menge": f"{qty} Stk."}, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        if not j or "display_price" not in j:
            raise RuntimeError(f"keine Variante für {qty} Stück")
        net = float(j["display_price"])  # netto inkl. Versand
        out.append(item("wps", "Hohlkammer-Stegplatte 2,5 mm", qty, net, net * VAT, WPS_URL))
    return out


# ------------------------------------------------------------------------------- jajabo
JJB_URL = "https://www.jajabo.de/wahlplakate.htm"


def fetch_jjb():
    """Staffelpreistabelle steht statisch im HTML (Format DIN A1 ist voreingestellt)."""
    r = session.get(JJB_URL, timeout=TIMEOUT)
    r.raise_for_status()
    if "DIN A1" not in r.text:
        raise RuntimeError("Format DIN A1 nicht auf der Seite gefunden")
    rows = re.findall(
        r'data-value="(\d+)"[^>]*>\s*<td class="quantity">[^<]*</td>\s*'
        r'<td class="price_netto">\s*([\d.,]+)\s*EUR</td>\s*'
        r'<td class="price_brutto">\s*([\d.,]+)\s*EUR</td>',
        r.text,
    )
    prices = {int(q): (de_number(n), de_number(g)) for q, n, g in rows}
    out = [
        item("jjb", "PP-Wellenstrukturplatte 3 mm", qty, prices[qty][0], prices[qty][1], JJB_URL)
        for qty in QTYS
        if qty in prices
    ]
    if not out:
        raise RuntimeError("Preistabelle nicht gefunden")
    return out


# --------------------------------------------------------------------------------- Main
SHOPS = {
    "fla": fetch_fla,
    "wmd": fetch_wmd,
    "sax": fetch_sax,
    "dn": fetch_dn,
    "h2p": fetch_h2p,
    "wps": fetch_wps,
    "jjb": fetch_jjb,
}

UNAVAILABLE = [
    {"shop": "wps", "qty": 1, "reason": "Mindestbestellmenge 10 Stück"},
    {"shop": "fla", "qty": 10000, "reason": "online höchstens 5.000 Stück"},
    {"shop": "sax", "qty": 10000, "reason": "online höchstens 1.000 Stück"},
    {"shop": "dn", "qty": 10000, "reason": "online höchstens 1.000 Stück"},
    {"shop": "wps", "qty": 10000, "reason": "online höchstens 5.000 Stück, größere Mengen auf Anfrage"},
]


def main() -> int:
    data = json.loads(DATA_FILE.read_text("utf-8")) if DATA_FILE.exists() else {"snapshots": []}
    snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])
    previous = snapshots[-1] if snapshots else None

    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()

    items, errors = [], []
    for shop, fn in SHOPS.items():
        try:
            got = fn()
            items.extend(got)
            print(f"OK   {shop}: {len(got)} Preise")
        except Exception as exc:  # noqa: BLE001 – ein Shop darf die anderen nicht stoppen
            traceback.print_exc()
            errors.append({"shop": shop, "message": str(exc)[:300]})
            old = [i for i in (previous or {}).get("items", []) if i["shop"] == shop]
            for i in old:
                i = dict(i)
                stale = "Abruf fehlgeschlagen, Preis vom letzten Datenstand"
                i["notes"] = [n for n in i.get("notes", []) if n != stale] + [stale]
                items.append(i)
            print(f"FEHLER {shop}: {exc} (übernehme {len(old)} alte Preise)")

    if len(errors) == len(SHOPS):
        print("Alle Shops fehlgeschlagen, Datei bleibt unverändert.")
        return 1

    snapshot = {"date": today, "updated": now.isoformat(timespec="seconds"), "items": items, "unavailable": UNAVAILABLE}
    if errors:
        snapshot["errors"] = errors
    snapshots = [s for s in snapshots if s["date"] != today] + [snapshot]
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps({"snapshots": snapshots}, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"Gespeichert: {today}, {len(items)} Preise, {len(errors)} Fehler")
    return 0


if __name__ == "__main__":
    sys.exit(main())
