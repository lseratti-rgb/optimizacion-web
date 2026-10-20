#!/usr/bin/env python3
"""Canjea el `code` que devuelve Tiendanube al instalar la app por el token de la tienda.

Al instalar la app, Tiendanube redirige a la URL de redirección con ?code=XXXX.
El code vence a los pocos minutos y sirve una sola vez: correr esto enseguida.

Uso:
  python3 tiendanube/oauth_token.py --code XXXX --nombre "Casa Eyvazian"

Credenciales de la app (panel de socios → tu app):
  TIENDANUBE_CLIENT_ID, TIENDANUBE_CLIENT_SECRET  (si faltan, se piden por consola sin mostrarlas)
  TIENDANUBE_USER_AGENT

Guarda/actualiza la tienda en tiendanube/stores.json (ignorado por git). El token no se imprime.
"""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://www.tiendanube.com/apps/authorize/token"
API_BASE = "https://api.tiendanube.com/2025-03"
STORES_FILE = Path(__file__).resolve().parent / "stores.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True, help="El code de la URL de redirección")
    ap.add_argument("--nombre", required=True, help="Nombre de la tienda para tn.py --tienda")
    args = ap.parse_args()

    user_agent = os.environ.get("TIENDANUBE_USER_AGENT") or sys.exit("Falta TIENDANUBE_USER_AGENT")
    client_id = os.environ.get("TIENDANUBE_CLIENT_ID") or input("client_id de la app: ").strip()
    client_secret = os.environ.get("TIENDANUBE_CLIENT_SECRET") or getpass.getpass("client_secret de la app: ").strip()

    body = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret,
                                   "grant_type": "authorization_code", "code": args.code.strip()}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} al canjear el code: {e.read().decode(errors='replace')}")
    if "access_token" not in data:
        sys.exit(f"Tiendanube no devolvió token (¿code vencido o ya usado?): {data}")

    store_id, token = str(data["user_id"]), data["access_token"]
    check = urllib.request.Request(f"{API_BASE}/{store_id}/store", headers={
        "Authentication": f"bearer {token}", "User-Agent": user_agent})
    with urllib.request.urlopen(check, timeout=30) as resp:
        store = json.loads(resp.read())
    name = store.get("name")
    print(f"OK  {args.nombre}  id={store_id}  ({name.get('es') if isinstance(name, dict) else name})")
    print(f"    permisos: {data.get('scope')}")

    stores = json.loads(STORES_FILE.read_text()) if STORES_FILE.exists() else []
    stores = [s for s in stores if str(s.get("store_id")) != store_id]
    stores.append({"name": args.nombre, "store_id": store_id, "token": token})
    STORES_FILE.write_text(json.dumps(stores, indent=2, ensure_ascii=False))
    os.chmod(STORES_FILE, 0o600)
    print(f"    guardada en {STORES_FILE} (token {token[:4]}…{token[-4:]})")


if __name__ == "__main__":
    main()
