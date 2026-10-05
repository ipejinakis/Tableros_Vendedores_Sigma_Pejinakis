"""Busca artículos en la base (tabla `dim_articulo`, incluye desactivados) por texto o código.

Uso (desde la raíz del repo, venv activo):
    python scripts/admin/buscar_articulo.py torron          # todas las palabras deben estar en la descripción
    python scripts/admin/buscar_articulo.py elementos dce   # varias palabras (AND)
    python scripts/admin/buscar_articulo.py 1026            # por código
    python scripts/admin/buscar_articulo.py moras --meses 3 # además muestra unidades vendidas (sin anuladas) en los últimos N meses
"""
import argparse
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import tableros as TB  # noqa: E402


def _sin_tildes(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s).upper()) if unicodedata.category(c) != "Mn")


def buscar(dim_articulo: pd.DataFrame, palabras: list[str]) -> pd.DataFrame:
    d = dim_articulo.copy()
    d["articulo_id"] = d["articulo_id"].astype(str)
    ps = [_sin_tildes(p) for p in palabras]
    texto = d["descripcion"].map(_sin_tildes)
    m = pd.Series(True, index=d.index)
    for p in ps:
        m &= texto.str.contains(p, regex=False) | d["articulo_id"].eq(p)
    cols = [c for c in ("articulo_id", "descripcion", "proveedor", "linea", "grupo", "desactivado", "suspendido") if c in d.columns]
    return d[m][cols].sort_values("articulo_id")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("palabras", nargs="+")
    ap.add_argument("--meses", type=int, default=0, help="sumar unidades vendidas de los últimos N meses")
    a = ap.parse_args()
    store = TB.abrir_store()
    t = buscar(store.read_table("dim_articulo"), a.palabras)
    if a.meses and len(t):
        meses = TB.meses_disponibles(store)[-a.meses:]
        v = pd.concat([TB.cargar_ventas_mes(store, m) for m in meses], ignore_index=True)
        v = v[v["estado"].astype(str).str.lower() != "anulada"]
        v["articulo_id"] = v["articulo_id"].astype(str)
        t["unidades_vendidas"] = t["articulo_id"].map(v.groupby("articulo_id")["unidades"].sum()).fillna(0)
    pd.set_option("display.width", 200, "display.max_colwidth", 60)
    print(f"{len(t)} artículos\n" if len(t) else "Sin resultados\n")
    if len(t):
        print(t.to_string(index=False))


if __name__ == "__main__":
    main()
