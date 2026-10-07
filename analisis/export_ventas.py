#!/usr/bin/env python3
"""Export de ventas con el formato del export de Tiendanube (una fila por producto).

Uso: python3 analisis/export_ventas.py datos/pedidos_<tienda>_<id>.json datos/export_<tienda>.csv
Entrada: JSON de `tn.py crudo`. Salida: CSV con ";" y coma decimal (abre bien en Excel en español).
"""

import csv
import json
import sys
from datetime import datetime, timedelta

ESTADO = {"open": "Abierta", "closed": "Cerrada", "cancelled": "Cancelada"}
PAGO = {"paid": "Pagado", "pending": "Pendiente", "authorized": "Autorizado", "voided": "Anulado",
        "refunded": "Reembolsado", "partially_refunded": "Reembolsado parcialmente",
        "partially_paid": "Pagado parcialmente", "abandoned": "Abandonado"}
ENVIO = {"unpacked": "No empaquetado", "unshipped": "No enviado", "shipped": "Enviado",
         "unfulfilled": "No enviado", "fulfilled": "Enviado", "delivered": "Entregado"}

COLS = ["Número de orden", "Email", "Fecha", "Estado de la orden", "Estado del pago", "Estado del envío",
        "Moneda", "Subtotal de productos", "Descuento", "Costo de envío", "Total", "Nombre del comprador",
        "DNI / CUIT", "Teléfono", "Nombre para el envío", "Dirección", "Número", "Piso", "Localidad", "Ciudad",
        "Código postal", "Provincia o estado", "País", "Medio de envío", "Medio de pago", "Cuotas",
        "Cupón de descuento", "Notas del comprador", "Notas del vendedor", "Fecha de pago",
        "Nombre del producto", "Precio del producto", "Cantidad del producto", "SKU", "Canal",
        "Código de tracking del envío", "Identificador de la orden", "Fecha de cancelación",
        "Motivo de cancelación", "UTM source", "UTM medium", "UTM campaign"]


def fecha(s):
    if not s:
        return ""
    return (datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S") - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")


def num(v):
    return "" if v in (None, "") else f"{float(v):.2f}".replace(".", ",")


def main(src, dst):
    orders = sorted(json.load(open(src)), key=lambda o: o["created_at"])
    rows = 0
    with open(dst, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLS)
        for o in orders:
            a = o.get("shipping_address") or {}
            c = o.get("customer") or {}
            ful = (o.get("fulfillments") or [{}])[0]
            ship = ful.get("shipping") or {}
            pd = o.get("payment_details") or {}
            utm = (o.get("customer_visit") or {}).get("utm_parameters") or {}
            subtotal = float(o.get("subtotal") or 0)
            discount = float(o.get("discount") or 0)
            shipping = o.get("shipping_cost_customer")
            if shipping is None:
                shipping = round(float(o.get("total") or 0) - subtotal + discount, 2)
            head = [
                o.get("number"), o.get("contact_email") or c.get("email"), fecha(o.get("created_at")),
                ESTADO.get(o.get("status"), o.get("status")), PAGO.get(o.get("payment_status"), o.get("payment_status")),
                ENVIO.get(o.get("shipping_status"), o.get("shipping_status")), o.get("currency"),
                num(subtotal), num(discount), num(shipping), num(o.get("total")),
                o.get("contact_name") or c.get("name"), o.get("contact_identification") or c.get("identification"),
                o.get("contact_phone") or c.get("phone"), a.get("name"), a.get("address"), a.get("number"),
                a.get("floor"), a.get("locality"), a.get("city"), a.get("zipcode"), a.get("province"), a.get("country"),
                (ship.get("option") or {}).get("name") or (ship.get("carrier") or {}).get("name"),
                o.get("gateway_name"), pd.get("installments"),
                ", ".join(cp.get("code", "") for cp in o.get("coupon") or []), o.get("note"), o.get("owner_note"),
                fecha(o.get("paid_at")),
            ]
            tail = [o.get("storefront"), (ful.get("tracking_info") or {}).get("code"), o.get("id"),
                    fecha(o.get("cancelled_at")), o.get("cancel_reason"),
                    utm.get("utm_source"), utm.get("utm_medium"), utm.get("utm_campaign")]
            for p in o.get("products") or [{}]:
                w.writerow(head + [p.get("name"), num(p.get("price")), p.get("quantity"), p.get("sku")] + tail)
                rows += 1
    print(f"{len(orders)} pedidos, {rows} filas -> {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
