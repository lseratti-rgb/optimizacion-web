# optimizacion-web

## Datos multi-tienda de Tiendanube

`tiendanube/tn.py` usa la API REST de Tiendanube (versión `2025-03`) para bajar pedidos, productos y clientes de **todas las tiendas vinculadas a la app** y los junta en CSV con una columna `tienda`. Usa solo la biblioteca estándar de Python 3, sin dependencias.

### Configuración

Cargar como variables de entorno (en Claude Code: menú del entorno → Edit → variables / API credentials). **No commitear tokens.**

| Variable | Ejemplo |
|---|---|
| `TIENDANUBE_STORES` | `[{"name":"Marca A","store_id":"123456","token":"..."}, ...]` |
| `TIENDANUBE_USER_AGENT` | `Mi App (contacto@midominio.com)` — la API lo exige |

`store_id` es el `user_id` y `token` es el `access_token` que devuelve el OAuth (`https://www.tiendanube.com/apps/authorize/token`). Los tokens no vencen, salvo que se desinstale la app o se genere uno nuevo.
Para trabajar en local también se puede usar `tiendanube/stores.json` (está en el .gitignore).

### Uso

```bash
python3 tiendanube/tn.py tiendas                                   # valida los tokens de cada tienda
python3 tiendanube/tn.py resumen  --desde 2026-09-01 --hasta 2026-09-30
python3 tiendanube/tn.py pedidos  --desde 2026-09-01 --hasta 2026-09-30 [--tienda "Marca A"]
python3 tiendanube/tn.py productos                                 # una fila por variante, con stock
python3 tiendanube/tn.py clientes
```

- `--estado-pago`: `paid` (por defecto), `pending`, `refunded`, `any`, etc. `resumen` excluye los pedidos cancelados.
- Las fechas son de creación del pedido, en hora de Argentina (-03:00), con `--hasta` inclusive.
- Salida: `datos/*.csv`.
- Respeta el límite de la API (bucket de 40 req, 2 req/s): reintenta ante 429 y errores 5xx.

## Informe de análisis de ventas

```bash
python3 tiendanube/tn.py crudo --tienda Desebia --estado-pago any          # pedidos completos en JSON
python3 analisis/analisis_ventas.py datos/pedidos_desebia_<id>.json datos/meta_desebia.json > datos/metricas.json
```

`analisis_ventas.py` calcula KPIs, recurrencia, corte VIP, recompra real (60+ días), tiempos de recompra, pago/cuotas/geografía, cruce con Meta por región y CPM, top productos y bundles. `informe_template.html` es la plantilla del informe (estilo Be Perfo), a la que se le inyectan las métricas en el lugar de `__DATA__`. Los textos de interpretación se escriben para cada tienda.
