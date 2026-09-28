#!/usr/bin/env python3
"""Extrae datos de varias tiendas de Tiendanube vía la API REST (2025-03).

Credenciales (nunca se commitean):
  TIENDANUBE_STORES      JSON con las tiendas:
                         [{"name": "Marca A", "store_id": "123", "token": "..."}]
                         (alternativa: archivo tiendanube/stores.json con el mismo formato)
  TIENDANUBE_USER_AGENT  Obligatorio para la API, ej: "Mi App (contacto@midominio.com)"

Uso:
  python3 tiendanube/tn.py tiendas
  python3 tiendanube/tn.py pedidos   --desde 2026-09-01 --hasta 2026-09-30 [--tienda "Marca A"]
  python3 tiendanube/tn.py productos
  python3 tiendanube/tn.py clientes
  python3 tiendanube/tn.py resumen   --desde 2026-09-01 --hasta 2026-09-30

Los CSV se guardan en datos/ (ignorado por git), con una columna "tienda".
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

API_BASE = "https://api.tiendanube.com/2025-03"
PER_PAGE = 200  # máximo permitido por la API
TZ = "-03:00"
ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT.parent / "datos"


def load_stores():
    raw = os.environ.get("TIENDANUBE_STORES")
    if not raw and (ROOT / "stores.json").exists():
        raw = (ROOT / "stores.json").read_text()
    if not raw:
        sys.exit("Falta TIENDANUBE_STORES (o tiendanube/stores.json). Ver README.")
    stores = json.loads(raw)
    for s in stores:
        missing = {"store_id", "token"} - s.keys()
        if missing:
            sys.exit(f"Tienda mal configurada ({s.get('name')}): falta {missing}")
        s.setdefault("name", str(s["store_id"]))
    return stores


def txt(value):
    """Los nombres vienen por idioma: {"es": "...", "pt": "..."}."""
    if isinstance(value, dict):
        return value.get("es") or next(iter(value.values()), "")
    return value or ""


class Client:
    def __init__(self, store_id, token, user_agent):
        self.base = f"{API_BASE}/{store_id}"
        self.headers = {
            "Authentication": f"bearer {token}",
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
            "Content-Type": "application/json; charset=utf-8",
        }

    def get(self, path, params=None, retries=5):
        url = f"{self.base}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(retries):
            req = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    remaining = resp.headers.get("x-rate-limit-remaining")
                    if remaining is not None and int(remaining) <= 2:
                        time.sleep(1)  # el bucket se vacía a 2 req/s
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    reset_ms = int(e.headers.get("x-rate-limit-reset") or 1000)
                    time.sleep(min(reset_ms / 1000, 20) + 0.5)
                    continue
                if e.code >= 500 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                if e.code == 404 and params and params.get("page", 1) > 1:
                    return []  # pasamos la última página
                body = e.read().decode(errors="replace")[:300]
                raise RuntimeError(f"HTTP {e.code} en {path}: {body}") from None
            except urllib.error.URLError:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Sin respuesta tras {retries} intentos: {path}")

    def paginate(self, path, params=None):
        params = dict(params or {}, per_page=PER_PAGE)
        page = 1
        while True:
            items = self.get(path, dict(params, page=page))
            if not items:
                return
            yield from items
            if len(items) < PER_PAGE:
                return
            page += 1


def date_params(args):
    params = {}
    if args.desde:
        params["created_at_min"] = f"{args.desde}T00:00:00{TZ}"
    if args.hasta:
        params["created_at_max"] = f"{args.hasta}T23:59:59{TZ}"
    return params


def fetch_orders(client, args):
    params = date_params(args)
    if args.estado_pago != "any":
        params["payment_status"] = args.estado_pago
    return list(client.paginate("orders", params))


def write_csv(name, rows):
    if not rows:
        print(f"  (sin filas para {name})")
        return
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / name
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"  -> {path.relative_to(ROOT.parent)} ({len(rows)} filas)")


def cmd_tiendas(clients, args):
    for store, c in clients:
        try:
            info = c.get("store")
            print(f"OK  {store['name']:<25} id={store['store_id']:<10} "
                  f"{txt(info.get('name'))} ({info.get('main_currency')}, {info.get('plan_name')})")
        except Exception as e:  # noqa: BLE001 - reportamos y seguimos con las demás
            print(f"ERR {store['name']:<25} id={store['store_id']:<10} {e}")


def cmd_pedidos(clients, args):
    orders_rows, items_rows = [], []
    for store, c in clients:
        orders = fetch_orders(c, args)
        print(f"{store['name']}: {len(orders)} pedidos")
        for o in orders:
            customer = o.get("customer") or {}
            orders_rows.append({
                "tienda": store["name"],
                "numero": o.get("number"),
                "creado": o.get("created_at"),
                "pagado": o.get("paid_at"),
                "estado": o.get("status"),
                "estado_pago": o.get("payment_status"),
                "estado_envio": o.get("shipping_status"),
                "moneda": o.get("currency"),
                "subtotal": o.get("subtotal"),
                "descuento": o.get("discount"),
                "envio": o.get("shipping_cost_customer"),
                "total": o.get("total"),
                "medio_pago": o.get("gateway_name") or o.get("gateway"),
                "canal": o.get("storefront"),
                "cupon": ",".join(cp.get("code", "") for cp in o.get("coupon") or []),
                "cliente": o.get("contact_name") or customer.get("name"),
                "email": o.get("contact_email") or customer.get("email"),
                "provincia": (o.get("billing_province") or ""),
            })
            for p in o.get("products") or []:
                items_rows.append({
                    "tienda": store["name"],
                    "numero": o.get("number"),
                    "creado": o.get("created_at"),
                    "estado_pago": o.get("payment_status"),
                    "product_id": p.get("product_id"),
                    "variant_id": p.get("variant_id"),
                    "producto": txt(p.get("name")),
                    "variante": " / ".join(map(str, p.get("variant_values") or [])),
                    "sku": p.get("sku"),
                    "cantidad": p.get("quantity"),
                    "precio": p.get("price"),
                })
    write_csv("pedidos.csv", orders_rows)
    write_csv("pedidos_items.csv", items_rows)


def cmd_productos(clients, args):
    rows = []
    for store, c in clients:
        products = list(c.paginate("products"))
        print(f"{store['name']}: {len(products)} productos")
        for p in products:
            for v in p.get("variants") or [{}]:
                rows.append({
                    "tienda": store["name"],
                    "product_id": p.get("id"),
                    "variant_id": v.get("id"),
                    "producto": txt(p.get("name")),
                    "variante": " / ".join(txt(x) for x in v.get("values") or []),
                    "sku": v.get("sku"),
                    "precio": v.get("price"),
                    "precio_promo": v.get("promotional_price"),
                    "costo": v.get("cost"),
                    "stock": v.get("stock"),  # None = stock infinito
                    "publicado": p.get("published"),
                    "marca": p.get("brand"),
                    "categorias": ", ".join(txt(cat.get("name")) for cat in p.get("categories") or []),
                    "url": p.get("canonical_url"),
                })
    write_csv("productos.csv", rows)


def cmd_clientes(clients, args):
    rows = []
    for store, c in clients:
        customers = list(c.paginate("customers", date_params(args)))
        print(f"{store['name']}: {len(customers)} clientes")
        for cu in customers:
            rows.append({
                "tienda": store["name"],
                "customer_id": cu.get("id"),
                "nombre": cu.get("name"),
                "email": cu.get("email"),
                "telefono": cu.get("phone"),
                "total_gastado": cu.get("total_spent"),
                "moneda": cu.get("total_spent_currency"),
                "ultimo_pedido": cu.get("last_order_id"),
                "acepta_marketing": cu.get("accepts_marketing"),
                "creado": cu.get("created_at"),
            })
    write_csv("clientes.csv", rows)


def cmd_resumen(clients, args):
    rows = []
    for store, c in clients:
        orders = [o for o in fetch_orders(c, args) if o.get("status") != "cancelled"]
        by_currency = defaultdict(lambda: {"pedidos": 0, "facturacion": 0.0, "unidades": 0})
        for o in orders:
            agg = by_currency[o.get("currency")]
            agg["pedidos"] += 1
            agg["facturacion"] += float(o.get("total") or 0)
            agg["unidades"] += sum(int(p.get("quantity") or 0) for p in o.get("products") or [])
        if not by_currency:
            by_currency[""]  # tienda sin ventas en el período
        for currency, agg in by_currency.items():
            rows.append({
                "tienda": store["name"],
                "moneda": currency,
                "pedidos": agg["pedidos"],
                "facturacion": round(agg["facturacion"], 2),
                "ticket_promedio": round(agg["facturacion"] / agg["pedidos"], 2) if agg["pedidos"] else 0,
                "unidades": agg["unidades"],
            })
    print(f"\nPeríodo {args.desde or '...'} a {args.hasta or '...'} | pago: {args.estado_pago}\n")
    print(f"{'Tienda':<25}{'Mon':<5}{'Pedidos':>9}{'Facturación':>16}{'Ticket prom.':>14}{'Unid.':>8}")
    for r in rows:
        print(f"{r['tienda']:<25}{r['moneda'] or '-':<5}{r['pedidos']:>9}"
              f"{r['facturacion']:>16,.0f}{r['ticket_promedio']:>14,.0f}{r['unidades']:>8}")
    write_csv("resumen.csv", rows)


def main():
    parser = argparse.ArgumentParser(description="Datos multi-tienda de Tiendanube")
    parser.add_argument("comando", choices=["tiendas", "pedidos", "productos", "clientes", "resumen"])
    parser.add_argument("--desde", help="YYYY-MM-DD (fecha de creación)")
    parser.add_argument("--hasta", help="YYYY-MM-DD, inclusive")
    parser.add_argument("--tienda", action="append", help="Filtrar por nombre o store_id (repetible)")
    parser.add_argument("--estado-pago", default="paid",
                        help="paid (default), pending, authorized, refunded, voided, abandoned o any")
    args = parser.parse_args()

    user_agent = os.environ.get("TIENDANUBE_USER_AGENT")
    if not user_agent:
        sys.exit('Falta TIENDANUBE_USER_AGENT, ej: "Mi App (contacto@midominio.com)"')

    stores = load_stores()
    if args.tienda:
        wanted = {t.lower() for t in args.tienda}
        stores = [s for s in stores if s["name"].lower() in wanted or str(s["store_id"]) in wanted]
        if not stores:
            sys.exit("Ninguna tienda coincide con --tienda")

    clients = [(s, Client(s["store_id"], s["token"], user_agent)) for s in stores]
    {"tiendas": cmd_tiendas, "pedidos": cmd_pedidos, "productos": cmd_productos,
     "clientes": cmd_clientes, "resumen": cmd_resumen}[args.comando](clients, args)


if __name__ == "__main__":
    main()
