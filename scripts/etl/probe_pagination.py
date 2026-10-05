#!/usr/bin/env python3
"""Prueba si la API respeta page/pagesize (en la muestra, pagesize sin page fue ignorado).

Uso:  python scripts/etl/probe_pagination.py
Hace 3 requests chicos y compara. Solo lectura.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sigma_conn import SigmaClient, load_settings  # noqa: E402


def main() -> int:
    c = SigmaClient(load_settings())
    n = 50
    todo = c.get_json("ExportVendedores")
    p1 = c.get_json("ExportVendedores", {"page": 1, "pagesize": n})
    p2 = c.get_json("ExportVendedores", {"page": 2, "pagesize": n})
    print(f"sin page      : {len(todo)} filas")
    print(f"page=1 size={n}: {len(p1)} filas")
    print(f"page=2 size={n}: {len(p2)} filas")
    ids = lambda rows: [r.get("id") for r in rows]  # noqa: E731
    if len(todo) > n and len(p1) == n and ids(p1) != ids(p2):
        print("=> La paginación FUNCIONA. Se puede poner SIGMA_PAGINATE=true.")
    elif ids(p1) == ids(todo):
        print("=> La API IGNORA page/pagesize. Dejar SIGMA_PAGINATE=false y cargar por ventanas de fechas.")
    else:
        print("=> Resultado ambiguo; pegar esta salida (sin token) para revisarlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
