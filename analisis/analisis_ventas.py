#!/usr/bin/env python3
"""Métricas para el informe de ventas de una tienda (datos crudos de tn.py crudo + Meta).

Uso: python3 analisis/analisis_ventas.py datos/pedidos_desebia_5567036.json [datos/meta_desebia.json]
Salida: JSON con todas las métricas (stdout), sin datos personales de clientes.
"""

import json
import re
import statistics as st
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations

MERGE_DAYS = 2        # pedidos del mismo cliente dentro de 2 días = una misma ocasión de compra
MARGIN_DAYS = 60      # margen mínimo para medir recompra
COLORS = ["OFF WHITE", "WILD SKIN", "SNAKE SKIN", "BLOSSOM", "NEGRO", "NEGRA", "CHOCOLATE", "BLANCO",
          "CRUDO", "CRUDA", "UVA", "NUDE", "FOX", "MINK", "RACOON", "TOSTADO", "MARRON"]
PROV_TO_META = {
    "CAPITAL FEDERAL": "Ciudad Autónoma de Buenos Aires", "CABA": "Ciudad Autónoma de Buenos Aires",
    "CIUDAD AUTONOMA DE BUENOS AIRES": "Ciudad Autónoma de Buenos Aires", "BUENOS AIRES": "Buenos Aires",
    "CORDOBA": "Córdoba", "SANTA FE": "Santa Fe", "ENTRE RIOS": "Entre Rios", "MENDOZA": "Mendoza",
    "TUCUMAN": "Tucuman", "CHUBUT": "Chubut", "MISIONES": "Misiones", "NEUQUEN": "Neuquén",
    "RIO NEGRO": "Río Negro", "SALTA": "Salta", "SAN JUAN": "San Juan", "CATAMARCA": "Catamarca",
    "SAN LUIS": "San Luis", "CHACO": "Chaco", "CORRIENTES": "Corrientes",
    "SANTIAGO DEL ESTERO": "Santiago del Estero", "SANTA CRUZ": "Santa Cruz", "FORMOSA": "Formosa",
    "TIERRA DEL FUEGO": "Tierra del Fuego", "JUJUY": "Jujuy", "LA PAMPA": "La Pampa", "LA RIOJA": "La Rioja",
}
META_SHORT = {"Ciudad Autónoma de Buenos Aires": "CABA", "Buenos Aires": "Prov. Buenos Aires"}


def plain(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper()).strip()


def base_product(name):
    n = plain(name).replace('"', "").replace("“", "").replace("”", "")
    n = re.sub(r"-?\s*PRE[- ]ORDER", "", n).replace(" - ", " ").strip(" -")
    stripped = n
    for c in COLORS:
        stripped = re.sub(rf"\b{c}\b", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped if len(stripped.split()) >= 2 else n


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def quantile(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def parse_dt(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S") - timedelta(hours=3)  # UTC -> AR


def order_features(o):
    ful = (o.get("fulfillments") or [{}])[0].get("shipping") or {}
    opt = (ful.get("option") or {}).get("name") or ""
    ship_type = ful.get("type")
    if ship_type == "pickup":
        entrega = "Retiro (showroom/pickup)"
    elif "sucursal" in opt.lower():
        entrega = "Envío a sucursal"
    elif ship_type == "ship":
        entrega = "Envío a domicilio"
    else:
        entrega = "Otro"
    pd = o.get("payment_details") or {}
    method = {"credit_card": "Tarjeta de crédito", "wire_transfer": "Transferencia", "wallet": "Billetera virtual",
              "debit_card": "Tarjeta de débito"}.get(pd.get("method"), "Otro")
    inst = pd.get("installments") or 1
    prov = plain(o.get("billing_province") or (o.get("shipping_address") or {}).get("province") or "")
    zona = "CABA" if prov in ("CAPITAL FEDERAL", "CABA", "CIUDAD AUTONOMA DE BUENOS AIRES") else (
        "Prov. Buenos Aires" if prov == "BUENOS AIRES" else "Interior")
    return {
        "entrega": entrega, "envio_opcion": opt, "pago": method,
        "cuotas": "1 pago" if inst <= 1 else ("3 cuotas" if inst == 3 else f"{'6+' if inst >= 6 else inst} cuotas"),
        "cupon": "Con cupón" if o.get("coupon") else "Sin cupón",
        "dispositivo": "Mobile" if o.get("storefront") == "mobile" else "Desktop",
        "provincia": prov, "zona": zona,
    }


def main(orders_path, meta_path=None):
    raw = json.load(open(orders_path))
    orders = [o for o in raw if o["payment_status"] == "paid" and o["status"] != "cancelled"]
    for o in orders:
        o["_dt"] = parse_dt(o["created_at"])
        o["_ars"] = float(o["total"])
        o["_usd"] = float(o.get("total_usd") or 0)
        o["_cust"] = str((o.get("customer") or {}).get("id") or plain(o.get("contact_email")))
        o["_f"] = order_features(o)
        o["_bases"] = sorted({base_product(p.get("name_without_variants") or p.get("name"))
                              for p in o["products"]})
    orders.sort(key=lambda o: o["_dt"])
    end = max(o["_dt"] for o in orders)
    start = min(o["_dt"] for o in orders)
    R = {"tienda": "Desebia", "periodo": [start.date().isoformat(), end.date().isoformat()],
         "pedidos_crudos": len(raw), "pedidos_validos": len(orders),
         "excluidos": dict(Counter((o["payment_status"], o["status"]) for o in raw
                                   if not (o["payment_status"] == "paid" and o["status"] != "cancelled")).most_common())}
    R["excluidos"] = {f"{k[0]}/{k[1]}": v for k, v in R["excluidos"].items()}

    # --- ocasiones de compra por cliente (se unen pedidos a <= MERGE_DAYS)
    by_cust = defaultdict(list)
    for o in orders:
        by_cust[o["_cust"]].append(o)
    occasions = {}
    merged = 0
    for c, os_ in by_cust.items():
        occ = []
        for o in os_:
            if occ and (o["_dt"] - occ[-1][-1]["_dt"]).days <= MERGE_DAYS:
                occ[-1].append(o)
                merged += 1
            else:
                occ.append([o])
        occasions[c] = occ
    R["pedidos_unidos_misma_ocasion"] = merged

    n_cust = len(by_cust)
    freq = Counter(len(v) for v in occasions.values())
    repeaters = sum(1 for v in occasions.values() if len(v) >= 2)
    rev_ars = sum(o["_ars"] for o in orders)
    rev_usd = sum(o["_usd"] for o in orders)
    R["kpis"] = {
        "facturacion_ars": round(rev_ars), "facturacion_usd": round(rev_usd), "ordenes": len(orders),
        "clientes": n_cust, "ticket_ars": round(rev_ars / len(orders)), "ticket_usd": round(rev_usd / len(orders)),
        "tasa_recompra_bruta": pct(repeaters, n_cust),
        "unidades": sum(int(p["quantity"]) for o in orders for p in o["products"]),
        "meses": len({o["_dt"].strftime("%Y-%m") for o in orders}),
    }

    # --- evolución mensual
    monthly = defaultdict(lambda: {"ordenes": 0, "ars": 0.0, "usd": 0.0, "nuevos": 0, "recurrentes": 0})
    first_seen = {c: occ[0][0]["_dt"] for c, occ in occasions.items()}
    for o in orders:
        m = monthly[o["_dt"].strftime("%Y-%m")]
        m["ordenes"] += 1
        m["ars"] += o["_ars"]
        m["usd"] += o["_usd"]
        if o["_dt"] == first_seen[o["_cust"]]:
            m["nuevos"] += 1
        else:
            m["recurrentes"] += 1
    months = []
    cur = datetime(start.year, start.month, 1)
    while cur <= end:
        k = cur.strftime("%Y-%m")
        m = monthly.get(k, {"ordenes": 0, "ars": 0.0, "usd": 0.0, "nuevos": 0, "recurrentes": 0})
        months.append({"mes": k, "ordenes": m["ordenes"], "ars": round(m["ars"]), "usd": round(m["usd"]),
                       "nuevos": m["nuevos"], "recurrentes": m["recurrentes"]})
        cur = datetime(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)
    R["mensual"] = months
    full = [m for m in months if m["mes"] != end.strftime("%Y-%m") or end.day >= 28]
    full = [m for m in full if m["mes"] >= "2025-03"]  # antes: tienda arrancando (1 pedido/mes)
    R["mejor_mes_usd"] = max(full, key=lambda m: m["usd"])
    R["peor_mes_usd"] = min(full, key=lambda m: m["usd"])

    # --- comparación interanual (abr-sep)
    def window(a, b):
        sel = [o for o in orders if a <= o["_dt"].strftime("%Y-%m") <= b]
        custs = {o["_cust"] for o in sel}
        new = {c for c in custs if a <= first_seen[c].strftime("%Y-%m") <= b}
        ars, usd = sum(o["_ars"] for o in sel), sum(o["_usd"] for o in sel)
        return {"ordenes": len(sel), "ars": round(ars), "usd": round(usd), "clientes": len(custs),
                "nuevos": len(new), "ticket_usd": round(usd / len(sel)) if sel else 0,
                "pct_ordenes_recurrentes": pct(sum(1 for o in sel if o["_dt"] > first_seen[o["_cust"]]), len(sel))}
    R["comparacion"] = {"actual": {"label": "Abr–Sep 2026", **window("2026-04", "2026-09")},
                        "anterior": {"label": "Abr–Sep 2025", **window("2025-04", "2025-09")}}

    # --- recurrencia
    dist = []
    for k in [1, 2, 3, 4]:
        dist.append({"compras": str(k), "clientes": freq.get(k, 0), "pct": pct(freq.get(k, 0), n_cust)})
    five = sum(v for k, v in freq.items() if k >= 5)
    dist.append({"compras": "5+", "clientes": five, "pct": pct(five, n_cust)})
    R["recurrencia"] = dist
    R["recurrencia_max"] = max(freq)
    umbrales = []
    for k in range(1, 7):
        n = sum(v for kk, v in freq.items() if kk >= k)
        umbrales.append({"n": k, "clientes": n, "pct": pct(n, n_cust)})
    R["umbrales"] = umbrales
    # quiebre: mayor caída relativa entre niveles consecutivos con base >= 5 clientes, desde 2+
    drops = []
    for a, b in zip(umbrales[1:], umbrales[2:]):
        if a["clientes"] >= 5:
            drops.append({"de": a["n"], "a": b["n"], "retiene": pct(b["clientes"], a["clientes"])})
    R["vip_drops"] = drops

    # valor por segmento
    seg_val = defaultdict(lambda: {"clientes": 0, "usd": 0.0, "ars": 0.0})
    for c, occ in occasions.items():
        k = len(occ)
        seg = "1" if k == 1 else ("2" if k == 2 else "3+")
        seg_val[seg]["clientes"] += 1
        seg_val[seg]["usd"] += sum(o["_usd"] for oc in occ for o in oc)
        seg_val[seg]["ars"] += sum(o["_ars"] for oc in occ for o in oc)
    R["valor_segmento"] = {k: {"clientes": v["clientes"], "usd": round(v["usd"]), "pct_fact": pct(v["usd"], rev_usd),
                               "ltv_usd": round(v["usd"] / v["clientes"])} for k, v in seg_val.items()}

    # --- recompra real y correlaciones (primera compra con >= 60 días de margen)
    elig = {c: occ for c, occ in occasions.items() if (end - occ[0][0]["_dt"]).days >= MARGIN_DAYS}
    rep = {c for c, occ in elig.items() if len(occ) >= 2}
    R["recompra_real"] = {"elegibles": len(elig), "recompraron": len(rep), "tasa": pct(len(rep), len(elig)),
                          "corte": (end - timedelta(days=MARGIN_DAYS)).date().isoformat()}
    within = sum(1 for c in rep if (elig[c][1][0]["_dt"] - elig[c][0][0]["_dt"]).days <= 90)
    R["recompra_real"]["en_90_dias"] = pct(within, len(elig))

    first_tickets = sorted(sum(o["_usd"] for o in occ[0]) for occ in elig.values())
    q1, q2, q3 = (quantile(first_tickets, q) for q in (0.25, 0.5, 0.75))

    def ticket_band(v):
        return (f"Q1 (< USD {q1:.0f})" if v < q1 else f"Q2 (USD {q1:.0f}–{q2:.0f})" if v < q2
                else f"Q3 (USD {q2:.0f}–{q3:.0f})" if v < q3 else f"Q4 (> USD {q3:.0f})")

    corr = {}
    for var in ["cupon", "entrega", "pago", "cuotas", "dispositivo", "zona", "ticket"]:
        g = defaultdict(lambda: [0, 0])
        for c, occ in elig.items():
            first = occ[0][0]
            val = ticket_band(sum(o["_usd"] for o in occ[0])) if var == "ticket" else first["_f"][var]
            g[val][0] += 1
            g[val][1] += c in rep
        corr[var] = sorted([{"valor": k, "clientes": v[0], "recompra": pct(v[1], v[0])} for k, v in g.items()],
                           key=lambda x: -x["clientes"])
    R["correlaciones"] = corr
    # multi-producto en primera compra
    g = defaultdict(lambda: [0, 0])
    for c, occ in elig.items():
        units = sum(int(p["quantity"]) for o in occ[0] for p in o["products"])
        g["1 unidad" if units == 1 else "2+ unidades"][0] += 1
        g["1 unidad" if units == 1 else "2+ unidades"][1] += c in rep
    R["correlaciones"]["unidades"] = [{"valor": k, "clientes": v[0], "recompra": pct(v[1], v[0])} for k, v in g.items()]

    # --- tiempo hasta volver
    d12 = [(occ[1][0]["_dt"] - occ[0][0]["_dt"]).days for occ in occasions.values() if len(occ) >= 2]
    gaps = [(occ[i + 1][0]["_dt"] - occ[i][0]["_dt"]).days for occ in occasions.values()
            for i in range(len(occ) - 1)]
    R["tiempo_recompra"] = {
        "n": len(d12), "mediana": quantile(d12, 0.5), "p25": quantile(d12, 0.25), "p75": quantile(d12, 0.75),
        "p90": quantile(d12, 0.9), "max": max(d12) if d12 else None, "promedio": round(st.mean(d12)) if d12 else None,
        "gaps_n": len(gaps), "gaps_mediana": quantile(gaps, 0.5),
        "hist": [{"rango": lbl, "n": sum(1 for d in d12 if lo <= d < hi)} for lbl, lo, hi in
                 [("0–15", 0, 15), ("15–30", 15, 30), ("30–60", 30, 60), ("60–90", 60, 90), ("90–120", 90, 120),
                  ("120–180", 120, 180), ("180–270", 180, 270), ("270+", 270, 10 ** 6)]],
    }
    # base disponible hoy para cada ventana: clientes de 1 compra según días desde su compra
    one = [(end - occ[0][0]["_dt"]).days for occ in occasions.values() if len(occ) == 1]
    R["base_una_compra_dias"] = one

    # --- pago, cuotas, geografía
    def share(key):
        c = Counter(o["_f"][key] for o in orders)
        usd = defaultdict(float)
        for o in orders:
            usd[o["_f"][key]] += o["_usd"]
        return [{"valor": k, "ordenes": v, "pct": pct(v, len(orders)), "ticket_usd": round(usd[k] / v)}
                for k, v in c.most_common()]
    R["pago"] = share("pago")
    R["cuotas"] = share("cuotas")
    R["entrega"] = share("entrega")
    R["zona"] = share("zona")
    R["dispositivo"] = share("dispositivo")
    R["cupones"] = {"ordenes": sum(1 for o in orders if o.get("coupon")),
                    "codigos": Counter(c.get("code") for o in orders for c in o.get("coupon") or []).most_common(10)}
    prov = Counter(o["_f"]["provincia"] for o in orders)
    R["provincias"] = [{"provincia": k.title(), "ordenes": v, "pct": pct(v, len(orders))} for k, v in prov.most_common()]

    # --- productos base
    units, ords, usd_p = Counter(), Counter(), defaultdict(float)
    for o in orders:
        for p in o["products"]:
            b = base_product(p.get("name_without_variants") or p.get("name"))
            units[b] += int(p["quantity"])
            usd_p[b] += float(p["price"]) * int(p["quantity"]) * (o["_usd"] / o["_ars"] if o["_ars"] else 0)
        for b in o["_bases"]:
            ords[b] += 1
    tot_units = sum(units.values())
    R["productos"] = [{"producto": b.title(), "unidades": u, "pct_unidades": pct(u, tot_units), "ordenes": ords[b],
                       "usd": round(usd_p[b])} for b, u in units.most_common(15)]
    R["productos_total_base"] = len(units)
    # producto de entrada de recompradores
    entry = Counter(b for c, occ in elig.items() for b in occ[0][0]["_bases"])
    entry_rep = Counter(b for c in rep for b in elig[c][0][0]["_bases"])
    R["producto_entrada"] = sorted([{"producto": b.title(), "clientes": n, "recompra": pct(entry_rep[b], n)}
                                    for b, n in entry.items() if n >= 12], key=lambda x: -x["recompra"])

    # --- bundles
    multi = [o for o in orders if len(o["_bases"]) >= 2]
    single = [o for o in orders if len(o["_bases"]) == 1]
    pair_c = Counter()
    pair_usd = defaultdict(float)
    for o in multi:
        for a, b in combinations(o["_bases"], 2):
            pair_c[(a, b)] += 1
            pair_usd[(a, b)] += o["_usd"]
    R["bundles_resumen"] = {"ordenes_multi": len(multi), "pct_multi": pct(len(multi), len(orders)),
                            "ticket_multi_usd": round(st.mean(o["_usd"] for o in multi)) if multi else 0,
                            "ticket_single_usd": round(st.mean(o["_usd"] for o in single)) if single else 0}
    bundles = []
    for (a, b), n in pair_c.most_common(12):
        if n < 2:
            break
        base = max(ords[a], ords[b])
        lead, other = (a, b) if ords[a] <= ords[b] else (b, a)
        bundles.append({"a": lead.title(), "b": other.title(), "ordenes": n,
                        "pct_sobre_a": pct(n, ords[lead]), "base_a": ords[lead],
                        "ticket_combo_usd": round(pair_usd[(a, b)] / n), "solido": n >= 5})
    R["bundles"] = bundles

    # --- Meta
    if meta_path:
        meta = json.load(open(meta_path))
        mm = {r[0]: {"spend": r[1], "impr": r[2], "cpm": r[3], "roas_meta": r[4]} for r in meta["mensual"]}
        cpm_rows = []
        for m in months:
            if m["mes"] in mm:
                x = mm[m["mes"]]
                cpm_rows.append({"mes": m["mes"], "spend": x["spend"], "cpm": x["cpm"], "impr": x["impr"],
                                 "roas_meta": x["roas_meta"], "ordenes": m["ordenes"], "usd": m["usd"],
                                 "cpa_est": round(x["spend"] / m["ordenes"], 1) if m["ordenes"] else None,
                                 "roas_est": round(m["usd"] / x["spend"], 1) if x["spend"] else None})
        R["cpm"] = cpm_rows
        # geografía desde el primer mes con datos de Meta
        since = min(mm)
        sel = [o for o in orders if o["_dt"].strftime("%Y-%m") >= since]
        geo_o, geo_u = Counter(), defaultdict(float)
        for o in sel:
            reg = PROV_TO_META.get(o["_f"]["provincia"], "Otras")
            geo_o[reg] += 1
            geo_u[reg] += o["_usd"]
        spend = meta["region"]
        tot_s, tot_o, tot_u = sum(spend.values()), len(sel), sum(geo_u.values())
        rows = []
        for reg in sorted(set(spend) | set(geo_o), key=lambda r: -spend.get(r, 0)):
            s = spend.get(reg, 0)
            if s < 30 and geo_o[reg] < 3:
                continue
            rows.append({"region": META_SHORT.get(reg, reg), "pct_inversion": pct(s, tot_s), "spend": round(s),
                         "ordenes": geo_o[reg], "pct_facturacion": pct(geo_u[reg], tot_u), "usd": round(geo_u[reg]),
                         "cpa_est": round(s / geo_o[reg], 1) if geo_o[reg] else None,
                         "roas_est": round(geo_u[reg] / s, 1) if s else None})
        R["geo"] = {"desde": since, "rows": rows, "spend_total": round(tot_s), "ordenes": tot_o, "usd": round(tot_u),
                    "roas_total": round(tot_u / tot_s, 1), "cpa_total": round(tot_s / tot_o, 1)}

    print(json.dumps(R, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:3])
