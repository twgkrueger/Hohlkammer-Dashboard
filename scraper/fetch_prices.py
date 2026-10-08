"""Fragt die Preise für Hohlkammerplakate DIN A1 und DIN A0 (10 Bohrungen, 4/0) bei
elf Online-Druckereien ab und schreibt einen Datenstand nach data/prices.json.

Alle Preise sind netto bzw. brutto INKLUSIVE Standardversand innerhalb Deutschlands.
Schlägt ein Shop fehl, wird sein letzter bekannter Preis übernommen und der Fehler
im Datenstand vermerkt, damit das Dashboard vollständig bleibt.
"""

from __future__ import annotations

import json
import math
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "prices.json"
FORMATS = ["A1", "A0"]
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


def item(shop, fmt, material, qty, net, gross, url, notes=None):
    d = {"shop": shop, "format": fmt, "material": material, "qty": qty, "net": r2(net), "gross": r2(gross), "url": url}
    if notes:
        d["notes"] = notes
    return d


# --------------------------------------------------------------------------- Flyeralarm
FLA_URL = "https://www.flyeralarm.com/de/p/wahlplakate-9456837.html"
FLA_API = (
    "https://www.flyeralarm.com/de/p/9456837/variant?"
    "selection[att.format.conf]={fmt}"
    "&selection[att.material.conf]={mat}"
    "&selection[att.farbigkeit.conf]=value.40farbig.conf"
)
FLA_FORMATS = {"A1": "value.dinA1594X84Cm.conf", "A0": "value.dinA0.conf"}
FLA_MATERIALS = {
    "value.450GHohlkammerplatteBasic.conf": "450 g Hohlkammerplatte Basic",
    "value.450GHohlkammerplatte.conf": "450 g Hohlkammerplatte",
    "value.450GRecyclingHohlkammerplatte.conf": "450 g Recycling-Hohlkammerplatte",
}


def fetch_fla(fmt):
    out = []
    for mat, name in FLA_MATERIALS.items():
        url = FLA_API.format(fmt=FLA_FORMATS[fmt], mat=mat)
        r = session.get(url, timeout=TIMEOUT, headers={"Accept": "application/json"})
        r.raise_for_status()
        quantities = r.json()["variantPrice"]["quantities"]
        by_amount = {q["amount"]: q["deliveryTypes"]["standard"] for q in quantities}
        for qty in QTYS:
            p = by_amount.get(qty)
            if p:  # Preise in Cent
                out.append(item("fla", fmt, name, qty, p["salesPriceNet"] / 100, p["salesPriceGross"] / 100, FLA_URL))
    if not out:
        raise RuntimeError("keine Preise in der Antwort")
    return out


# ----------------------------------------------------------------------- WIRmachenDRUCK
WMD_URLS = {
    fmt: "https://www.wir-machen-druck.de/"
    f"wahlplakat-auf-hohlkammerplatte-din-{fmt.lower()}-einseitig-40farbig-bedruckt-mit-10-bohrungen.html"
    for fmt in FORMATS
}


def fetch_wmd(fmt):
    url = WMD_URLS[fmt]
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    prices = {}
    for qty_s, net_s in re.findall(r"([\d.]+) Stück \(([\d.,]+) Euro netto\)", r.text):
        prices.setdefault(int(qty_s.replace(".", "")), de_number(net_s))
    out = []
    for qty in QTYS:
        if qty in prices:
            net = prices[qty]
            out.append(item("wmd", fmt, "Hohlkammerplatte 3 mm", qty, net, net * VAT, url))
    if not out:
        raise RuntimeError("Auflagenliste nicht gefunden")
    return out


# ---------------------------------------------------------------------------- Saxoprint
SAX_URL = "https://www.saxoprint.de/plakate/hohlkammerplakate-drucken"
SAX_API = "https://api.saxoprint.de/product-configuration/get-product-prices"
SAX_MAX = 1000  # im Shop online höchstens 1.000 Stück
SAX_FORMATS = {"A1": 42, "A0": 41}  # propertyId 9 = Endformat
SAX_CONFIG = [
    (6, 1476), (44, None), (152, 1433), (9, None), (10, 120), (7, 76), (8, 1133), (48, 1436),
    (64, 1438), (153, 1477), (1, 222), (13, 205), (102, 1055), (2, 179), (27, 188),
]


def fetch_sax(fmt):
    out = []
    for qty in [q for q in QTYS if q <= SAX_MAX]:
        values = {44: qty, 9: SAX_FORMATS[fmt]}
        body = {
            "productGroupId": 1476,
            "customerNumber": 0,
            "propertyConfiguration": [
                {"propertyId": pid, "value": values.get(pid, val)} for pid, val in SAX_CONFIG
            ],
            "printRuns": [],
            "deliverySplitPrintRuns": [],
        }
        r = session.post(SAX_API, json=body, timeout=TIMEOUT, headers={"Origin": "https://www.saxoprint.de"})
        r.raise_for_status()
        j = r.json()
        out.append(item("sax", fmt, "PP-Hohlkammerplatte 2,5 mm", qty, float(j["priceNet"]), float(j["priceGross"]), SAX_URL))
    return out


# -------------------------------------------------------------------------- Drucknische
DN_URLS = {
    "A1": "https://drucknische.de/products/hohlkammerplakate-din-a1",
    "A0": "https://drucknische.de/products/a0-plakat",
}
DN_MAX = 1000
DN_NOTES = ["12-fach statt 10-fach Lochung"]


def fetch_dn(fmt):
    """Der Preis wird im Browser berechnet (Rechner-Plugin), daher Playwright."""
    from playwright.sync_api import sync_playwright

    url = DN_URLS[fmt]
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="de-DE", user_agent=HEADERS["User-Agent"])
        page.goto(url, wait_until="networkidle", timeout=60000)
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
            out.append(item("dn", fmt, "PP-Hohlkammerplatte 2,5 mm", qty, gross / VAT, gross, url, DN_NOTES))
        browser.close()
    return out


# ------------------------------------------------------------------------ highway2print
H2P_AJAX = "https://www.highway2print.de/wp-admin/admin-ajax.php"
H2P_PRODUCTS = {
    # Format: (Produktseite, product_id, Gewicht pro Plakat in kg, Mindestmenge)
    "A1": ("https://www.highway2print.de/produkt/hohlkammerplakat-din-a1/", "180", 0.225, 1),
    "A0": ("https://www.highway2print.de/produkt/hohlkammerplakat-din-a0/", "177", 0.450, 2),
}
# Versand brutto laut https://www.highway2print.de/versandarten/ (Stand 10/2026)
H2P_DPD = [(3, 10.71), (10, 14.28), (15, 17.85), (20, 21.42), (25, 23.80), (30, 29.75)]
H2P_FREIGHT = [
    (100, 91.63), (200, 116.62), (300, 128.52), (400, 183.26), (500, 224.91), (600, 249.90),
    (700, 265.37), (800, 284.41), (900, 297.50), (1000, 314.16), (1250, 364.14), (1500, 383.18),
    (1750, 421.26), (2000, 458.15), (2500, 529.55),
]


def h2p_shipping_gross(kg):
    """Gibt (Versand brutto, Hinweistext) zurück."""
    for limit, price in H2P_DPD:
        if kg <= limit:
            return price, "Versand nach Gewichtstabelle berechnet"
    for limit, price in H2P_FREIGHT:
        if kg <= limit:
            return price, "Versand per Spedition, nach Gewichtstabelle berechnet"
    # Über 2.500 kg hat die Tabelle keinen Wert mehr: als mehrere volle Speditionssendungen schätzen.
    max_kg, max_price = H2P_FREIGHT[-1]
    n = math.ceil(kg / max_kg)
    return n * max_price, f"Versand geschätzt ({n} Speditionssendungen, über Versandtabelle hinaus)"


def fetch_h2p(fmt):
    url, product_id, kg_each, min_qty = H2P_PRODUCTS[fmt]
    page = session.get(url, timeout=TIMEOUT)
    page.raise_for_status()
    m = re.search(r'highwayOfferNonce\s*=\s*"([^"]+)"', page.text)
    if not m:
        raise RuntimeError("Nonce nicht gefunden")
    nonce = m.group(1)
    out = []
    for qty in [q for q in QTYS if q >= min_qty]:
        data = {
            "action": "highway_live_offer", "nonce": nonce, "product_id": product_id, "total_qty": str(qty),
            "motif_count": "1", "lochung": "10-fach-Lochung", "datencheck": "ohne",
        }
        r = session.post(H2P_AJAX, data=data, timeout=TIMEOUT, headers={"Referer": url})
        r.raise_for_status()
        j = r.json()
        if not j.get("success"):
            raise RuntimeError(f"Antwort ohne Erfolg für {qty} Stück: {str(j.get('data'))[:120]}")
        net_goods = de_number(re.sub(r"<[^>]+>|&nbsp;|&euro;|€", "", j["data"]["net_total"]))
        ship_gross, note = h2p_shipping_gross(qty * kg_each)
        net = net_goods + ship_gross / VAT
        out.append(item("h2p", fmt, "Hohlkammerplatte 2,5 mm", qty, net, net * VAT, url, [note]))
    return out


# ----------------------------------------------------------------------- wahlplakatshop
WPS_AJAX = "https://www.wahlplakatshop.de/?wc-ajax=get_variation"
WPS_PRODUCTS = {
    # Format: (Produktseite, product_id, Hinweise)
    "A1": ("https://www.wahlplakatshop.de/product/hohlkammerplakate-a1/", "24", None),
    "A0": ("https://www.wahlplakatshop.de/product/hohlkammerplakate-a0/", "75", ["12-fach statt 10-fach Lochung"]),
}
WPS_MIN, WPS_MAX = 10, 5000


def fetch_wps(fmt):
    url, product_id, notes = WPS_PRODUCTS[fmt]
    out = []
    for qty in [q for q in QTYS if WPS_MIN <= q <= WPS_MAX]:
        r = session.post(WPS_AJAX, data={"product_id": product_id, "attribute_menge": f"{qty} Stk."}, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        if not j or "display_price" not in j:
            raise RuntimeError(f"keine Variante für {qty} Stück")
        net = float(j["display_price"])  # netto inkl. Versand
        out.append(item("wps", fmt, "Hohlkammer-Stegplatte 2,5 mm", qty, net, net * VAT, url, notes))
    return out


# ------------------------------------------------------------------------------- jajabo
JJB_URL = "https://www.jajabo.de/wahlplakate.htm"
JJB_FORMATS = {"A1": "8468", "A0": "8469"}  # Parameter "sorten"


def fetch_jjb(fmt):
    """Staffelpreistabelle steht statisch im HTML; das Format wählt der Parameter ?sorten=."""
    sorte = JJB_FORMATS[fmt]
    r = session.get(JJB_URL, params={"sorten": sorte}, timeout=TIMEOUT)
    r.raise_for_status()
    if not re.search(rf"addSelectedListValue\('sorten',\s*{sorte},\s*'DIN {fmt}'", r.text):
        raise RuntimeError(f"Format DIN {fmt} ist auf der Seite nicht ausgewählt")
    rows = re.findall(
        r'data-value="(\d+)"[^>]*>\s*<td class="quantity">[^<]*</td>\s*'
        r'<td class="price_netto">\s*([\d.,]+)\s*EUR</td>\s*'
        r'<td class="price_brutto">\s*([\d.,]+)\s*EUR</td>',
        r.text,
    )
    prices = {int(q): (de_number(n), de_number(g)) for q, n, g in rows}
    out = [
        item("jjb", fmt, "PP-Wellenstrukturplatte 3 mm", qty, prices[qty][0], prices[qty][1], f"{JJB_URL}?sorten={sorte}")
        for qty in QTYS
        if qty in prices
    ]
    if not out:
        raise RuntimeError("Preistabelle nicht gefunden")
    return out


# --------------------------------------------------------------------------- print24
P24_URL = "https://print24.com/de/druckprodukte/plakate/wahlplakate"
P24_API = "https://print24.com/api/de/"
P24_FORMATS = {"A1": "184", "A0": "314"}  # Eigenschaft "format"
P24_QTY_IDS = {1: "340", 100: "400", 500: "350", 1000: "444", 10000: "399"}
P24_PROPERTIES = [  # Konfiguration: Hohlkammerplatte 450 g, 10-fach Lochung 7 mm, 4/0, ohne Zubehör/Proof
    ("availability", "3765"), ("quality", "4560"), ("format", None), ("aspect_ratio", "6309"),
    ("material_spec", "7953"), ("farben", "115"), ("verarbeitung", "7954"), ("finishing", "6307"),
    ("finishing_desc", "24"), ("finishing_size", "4016"), ("accessories", "6003"), ("proofformat", "823"),
    ("proofpages", "840"), ("motive", "27"),
]


def fetch_p24(fmt):
    headers = {"portal": "print24", "Accept": "application/json, text/plain, */*"}
    tok = session.get(P24_API + "token/create/expiry", headers=headers, timeout=TIMEOUT)
    tok.raise_for_status()
    headers = dict(headers, auth=tok.json()["token"])
    body = {
        "delivery_country_code": "DE",
        "product_alias_id": 111,
        "properties": [{"id": P24_FORMATS[fmt] if pid is None else pid, "name": name} for name, pid in P24_PROPERTIES],
        "quantities": [P24_QTY_IDS[q] for q in QTYS],
        "premium_file_check": 0,
    }
    r = session.post(P24_API + "itemmaster/calculation/price-matrix", json=body, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for row in r.json():
        types = row["quantity"]["shipping_type"]
        std = next((t for t in types if t.get("delivery_type") == "standard"), types[0])
        price = std["price"]
        qty = int(price["quantity_value"])
        fp = price["final_prices"]  # total_* = inkl. Versand
        if qty in QTYS:
            out.append(item("p24", fmt, "Hohlkammerplatte 450 g, 2,5 mm", qty, fp["total_net_value"], fp["total_gross_value"], P24_URL))
    if not out:
        raise RuntimeError("keine Preise in der Antwort")
    return out


# ------------------------------------------------------------------------------- maxxprint
MX_URL = "https://maxxprint.de/wahlplakate?number=SW10054"
MX_VARIANT = "https://maxxprint.de/wahlplakate"
MX_EVAL = "https://maxxprint.de/evaluator/price"
MX_FORMATS = {"A1": ("1383", 594, 841), "A0": ("1384", 841, 1189)}  # Option, Breite, Höhe (mm)
MX_SHIPPING_OPTION = "1529"  # Standardversand
MX_MAX_PER_MOTIF = 100


def fetch_mx(fmt):
    option, width, height = MX_FORMATS[fmt]
    params = {"group[7]": option, "input-product-motive": "1", "input-product-auflage": "1",
              "group[68]": MX_SHIPPING_OPTION, "template": "ajax"}
    page = session.get(MX_VARIANT, params=params, timeout=TIMEOUT)
    page.raise_for_status()

    def option_rule(value):
        m = re.search(rf'value="{value}"[^>]*?data-maxx_price_rule="([^"]*)"[^>]*?data-maxx_surcharge_once="([^"]*)"', page.text)
        if not m:
            raise RuntimeError(f"Preisregel für Option {value} nicht gefunden")
        return m.group(1), m.group(2)

    fmt_rule, once = option_rule(option)
    ship_rule, _ = option_rule(MX_SHIPPING_OPTION)
    art = re.search(r'data-art_price_rule="([^"]*)"', page.text)
    rules = [fmt_rule, "multstueck{}", art.group(1) if art else "motive{3.00}", once or "0", ship_rule]
    out = []
    for qty in [q for q in QTYS if q <= MX_MAX_PER_MOTIF]:
        data = {"fictionalPrice": "false", "basePrice": "0", "anzahl": str(qty), "motive": "1", "auflage": str(qty),
                "width": str(width), "height": str(height), "unit": "mm", "sender": "skycoPriceBox"}
        data.update({f"priceRule-{i}": rule for i, rule in enumerate(rules)})
        r = session.post(MX_EVAL, data=data, timeout=TIMEOUT, headers={"X-Requested-With": "XMLHttpRequest", "Referer": MX_URL})
        r.raise_for_status()
        net = sum(float(t["res"]) for t in r.json()["data"]["trackback"])  # inkl. Versand
        out.append(item("mx", fmt, "Hohlkammerplatte", qty, net, net * VAT, MX_URL))
    return out


# ------------------------------------------------------------------------------ Bannerkönig
BK_URL = "https://www.bannerkoenig.de/shop/wahlplakat-hohlkammerplatte/"
BK_CALC = "https://www.bannerkoenig.de/"
BK_FORMATS = {"A1": "din_a1", "A0": "din_a0"}
BK_SHIP_MIN_NET = 6.90  # Mindestversand laut Versandseite; genaue Kosten erst im Warenkorb
BK_NOTES = ["ohne Lochung (nicht wählbar)", "Versand: nur Mindestbetrag 6,90 € eingerechnet"]


def fetch_bk(fmt):
    page = session.get(BK_URL, timeout=TIMEOUT)
    page.raise_for_status()
    m = re.search(r'bkcmz_core_ajax\s*=\s*\{[^}]*"nonce":"([a-f0-9]+)"', page.text)
    if not m:
        raise RuntimeError("Nonce nicht gefunden")
    out = []
    for qty in QTYS:
        data = {"product_id": "2558888", "erp_cpo_material": "hohlkammerplatte_3mm", "erp_cpo_druck": "einseitiger_druck",
                "erp_cpo_groesse": BK_FORMATS[fmt], "erp_cpo_menge": str(qty)}
        r = session.post(BK_CALC, params={"bkcmz_perform_calculations": "1", "nonce": m.group(1)}, data=data,
                         timeout=TIMEOUT, headers={"Referer": BK_URL})
        r.raise_for_status()
        j = r.json()
        if not j.get("success"):
            raise RuntimeError(f"Berechnung fehlgeschlagen für {qty} Stück")
        net = float(j["data"]["price_netto"]) + BK_SHIP_MIN_NET
        out.append(item("bk", fmt, "Hohlkammerplatte 3 mm", qty, net, net * VAT, BK_URL, BK_NOTES))
    return out


# ------------------------------------------------------------------------------ myDisplays
MD_URL = "https://www.mydisplays.net/wahlplakat-hohlkammer"
MD_API = "https://www.mydisplays.net/website_product_configurator/onchange"
MD_TEMPLATE = 3926
MD_FORMATS = {"A1": (1099, 0.225), "A0": (1100, 0.45)}  # Größen-ID, geschätztes Gewicht pro Stück (kg)
MD_FIXED = [643, 370, 567, 380, 316]  # Konfektion, Zuschnitt rechteckig, 2,5 mm Platte, ohne Bohrungen, Basis-Datencheck
MD_SHIP_PER_30KG = 9.90  # Standardversand Deutschland je Paket bis 30 kg (https://www.mydisplays.net/versandkosten)
MD_NOTES = ["ohne Lochung (nur 4 Eckbohrungen wählbar)", "Versand geschätzt (9,90 € je 30-kg-Paket)"]


def fetch_md(fmt):
    size_id, kg_each = MD_FORMATS[fmt]
    out = []
    for qty in QTYS:
        payload = {"id": 1, "jsonrpc": "2.0", "method": "call", "params": {
            "product_id": MD_TEMPLATE, "selected_ids": MD_FIXED + [size_id],
            "custom_values": {"52": str(qty), "56": "1", "93": False}}}
        r = session.post(MD_API, json=payload, timeout=TIMEOUT, headers={"Referer": MD_URL})
        r.raise_for_status()
        res = r.json().get("result")
        if not res:
            raise RuntimeError(f"keine Antwort für {qty} Stück")
        goods = float(res["prices"]["price"])
        ship = math.ceil(qty * kg_each / 30) * MD_SHIP_PER_30KG
        net = goods + ship
        out.append(item("md", fmt, "Hohlkammerplatte 2,5 mm", qty, net, net * VAT, MD_URL, MD_NOTES))
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
    "p24": fetch_p24,
    "mx": fetch_mx,
    "bk": fetch_bk,
    "md": fetch_md,
}


def _na(shop, qty, reason, formats=("A1", "A0")):
    return [{"shop": shop, "format": f, "qty": qty, "reason": reason} for f in formats]


UNAVAILABLE = [
    *_na("wps", 1, "Mindestbestellmenge 10 Stück"),
    *_na("h2p", 1, "Mindestbestellmenge 2 Stück", formats=("A0",)),
    *_na("fla", 10000, "online höchstens 5.000 Stück"),
    *_na("sax", 10000, "online höchstens 1.000 Stück"),
    *_na("dn", 10000, "online höchstens 1.000 Stück"),
    *_na("wps", 10000, "online höchstens 5.000 Stück, größere Mengen auf Anfrage"),
    *_na("mx", 500, "online höchstens 100 Stück je Motiv"),
    *_na("mx", 1000, "online höchstens 100 Stück je Motiv"),
    *_na("mx", 10000, "online höchstens 100 Stück je Motiv"),
]


def main() -> int:
    data = json.loads(DATA_FILE.read_text("utf-8")) if DATA_FILE.exists() else {"snapshots": []}
    snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])
    previous = snapshots[-1] if snapshots else None

    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()

    items, errors = [], []
    for fmt in FORMATS:
        for shop, fn in SHOPS.items():
            try:
                got = fn(fmt)
                items.extend(got)
                print(f"OK     {fmt} {shop}: {len(got)} Preise")
            except Exception as exc:  # noqa: BLE001 – ein Shop darf die anderen nicht stoppen
                traceback.print_exc()
                errors.append({"shop": shop, "format": fmt, "message": str(exc)[:300]})
                old = [
                    i for i in (previous or {}).get("items", [])
                    if i["shop"] == shop and i.get("format", "A1") == fmt
                ]
                stale = "Abruf fehlgeschlagen, Preis vom letzten Datenstand"
                for i in old:
                    i = dict(i, format=fmt)
                    i["notes"] = [n for n in i.get("notes", []) if n != stale] + [stale]
                    items.append(i)
                print(f"FEHLER {fmt} {shop}: {exc} (übernehme {len(old)} alte Preise)")

    if len(errors) == len(SHOPS) * len(FORMATS):
        print("Alle Abfragen fehlgeschlagen, Datei bleibt unverändert.")
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
