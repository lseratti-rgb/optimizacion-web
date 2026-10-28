# Instrucciones para Claude

Repo de Be Perfo para consultar datos de las tiendas de Tiendanube de los clientes (pedidos, productos, clientes) y armar análisis de ventas.

## Credenciales

Están en la configuración del entorno, nunca en el repo ni en el chat:

- `TIENDANUBE_STORES`: JSON con la lista `[{"name": "...", "store_id": "...", "token": "..."}]`.
- `TIENDANUBE_USER_AGENT`: obligatorio para la API.

No pidas tokens por el chat. Si una tienda no aparece en `python3 tiendanube/tn.py tiendas`, explicá que hay que instalar la app en esa tienda (`https://<tienda>.mitiendanube.com/admin/apps/42381/authorize`) y sumar su token a `TIENDANUBE_STORES` en la configuración del entorno. La app de Railway guarda el token en Supabase, en la tabla `provider_connections`.

## Cómo consultar

```bash
python3 tiendanube/tn.py tiendas                                    # lista las tiendas y valida los tokens
python3 tiendanube/tn.py resumen --tienda "Nombre" --desde 2026-10-01 --hasta 2026-10-31
python3 tiendanube/tn.py crudo --tienda <store_id> --estado-pago any --desde 2026-01-01 --hasta 2026-12-31
```

`crudo` guarda el JSON completo en `datos/pedidos_<tienda>_<id>.json` para analizarlo con Python.

## Criterios

- Ventas válidas: `payment_status == "paid"` y `status != "cancelled"`.
- Fechas en hora de Argentina (UTC-3): agrupar por la fecha local, no por el `created_at` en UTC.
- La API no trae visitas: no las estimes; decí que salen del panel de Tiendanube (Estadísticas) o de GA4.
- Inversión en Meta y GA4: por los conectores de Meta Ads o Reporting Ninja.

## Datos de clientes

`datos/` y `tiendanube/stores.json` están en `.gitignore`. El repo es público: no subas datos de clientes ni tokens.
