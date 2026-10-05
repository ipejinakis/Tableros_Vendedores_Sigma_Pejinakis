"""Lista TODOS los vendedores de la base (tabla `dim_vendedor`) con supervisor, estado y lo que vendieron.

Sirve para cruzar nombres de otros archivos (Excel de Club Faro, etc.) contra los códigos de SIGMA.

Uso (desde la raíz del repo, venv activo):
    python scripts/admin/listar_vendedores.py                    # todos, con ventas de los últimos 2 meses
    python scripts/admin/listar_vendedores.py --buscar aguirre   # filtra por nombre, código o supervisor
    python scripts/admin/listar_vendedores.py --solo-con-ventas  # solo los que vendieron en el período
    python scripts/admin/listar_vendedores.py --meses 1 --csv vendedores.csv
"""
import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import tableros as TB  # noqa: E402
from sigma_conn import transform as T  # noqa: E402


def armar_tabla(dim_vendedor: pd.DataFrame, ventas: pd.DataFrame | None, dim_articulo: pd.DataFrame | None) -> pd.DataFrame:
    """Una fila por vendedor de `dim_vendedor` + neto vendido (M$, sin anuladas) por proveedor principal."""
    t = dim_vendedor.copy()
    t["vendedor_id"] = t["vendedor_id"].astype(str)
    cols = [c for c in ("vendedor_id", "nombre", "activo", "supervisor_id", "supervisor", "sucursal", "email") if c in t.columns]
    t = t[cols].copy()
    for c in ("neto_unilever", "neto_penaflor", "neto_otros", "neto_total", "clientes"):
        t[c] = 0.0
    if ventas is not None and len(ventas) and dim_articulo is not None:
        v = T.ventas_validas(ventas)
        prov = dim_articulo.drop_duplicates("articulo_id").set_index("articulo_id")["proveedor"].astype("string").str.upper()
        v = v.assign(vendedor_id=v["vendedor_id"].astype(str), proveedor=v["articulo_id"].map(prov).fillna(""))
        v["grupo"] = v["proveedor"].map(lambda p: "neto_unilever" if "UNILEVER" in p else "neto_penaflor" if "PEÑAFLOR" in p or "PENAFLOR" in p else "neto_otros")
        pv = v.pivot_table(index="vendedor_id", columns="grupo", values="importe_neto", aggfunc="sum", fill_value=0.0)
        cl = v.groupby("vendedor_id")["cliente_id"].nunique()
        t = t.set_index("vendedor_id")
        for c in pv.columns:
            t[c] = pv[c].reindex(t.index).fillna(0.0)
        t["clientes"] = cl.reindex(t.index).fillna(0).astype(int)
        # vendedores con ventas que no están en dim_vendedor (por si el filtro de la API los dejó afuera)
        faltan = sorted(set(v["vendedor_id"]) - set(t.index))
        if faltan:
            extra = pd.DataFrame({"vendedor_id": faltan, "nombre": "(NO ESTÁ EN dim_vendedor)", "activo": True}).set_index("vendedor_id")
            extra["neto_total"] = 0.0
            t = pd.concat([t, extra]).fillna({"supervisor": "", "supervisor_id": ""})
            for c in pv.columns:
                t.loc[faltan, c] = pv[c].reindex(faltan).fillna(0.0)
            t.loc[faltan, "clientes"] = cl.reindex(faltan).fillna(0).astype(int)
        t = t.reset_index()
    t["neto_total"] = t[["neto_unilever", "neto_penaflor", "neto_otros"]].sum(axis=1)
    return t.sort_values(["activo", "neto_total", "vendedor_id"], ascending=[False, False, True]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--buscar", help="texto a buscar en código, nombre o supervisor (sin distinguir mayúsculas ni tildes)")
    ap.add_argument("--meses", type=int, default=2, help="cuántos meses recientes de ventas cruzar (0 = no cruzar)")
    ap.add_argument("--solo-con-ventas", action="store_true")
    ap.add_argument("--csv", help="guardar además en este CSV")
    a = ap.parse_args()

    warnings.filterwarnings("ignore")
    store = TB.abrir_store()
    dim_v = store.read_table("dim_vendedor")
    ventas = dim_a = None
    if a.meses > 0:
        meses = TB.meses_disponibles(store)[-a.meses:]
        if meses:
            ventas = pd.concat([TB.cargar_ventas_mes(store, m) for m in meses], ignore_index=True)
            dim_a = store.read_table("dim_articulo")
            print(f"Ventas cruzadas: {', '.join(meses)}\n")
    t = armar_tabla(dim_v, ventas, dim_a)
    if a.solo_con_ventas:
        t = t[t["neto_total"] != 0]
    if a.buscar:
        from sigma_conn.negocio import clave_nombre
        q = clave_nombre(a.buscar).split()
        lista = (t["vendedor_id"].astype(str) + " " + t["nombre"].fillna("") + " " + t.get("supervisor", "").fillna("")).map(clave_nombre)
        t = t[lista.map(lambda s: all(w in s for w in q))]

    print(f"{len(t)} vendedores (dim_vendedor tiene {len(dim_v)})\n")
    vista = t.assign(**{c: (t[c] / 1e6).round(2) for c in ("neto_unilever", "neto_penaflor", "neto_otros", "neto_total")}) \
        .rename(columns={"neto_unilever": "Unilever M$", "neto_penaflor": "Peñaflor M$", "neto_otros": "Otros M$", "neto_total": "Total M$"})
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_columns", 30)
    print(vista.drop(columns=[c for c in ("email", "supervisor_id") if c in vista.columns]).to_string(index=False))
    if a.csv:
        t.to_csv(a.csv, index=False, encoding="utf-8-sig")
        print(f"\nGuardado: {a.csv}")


if __name__ == "__main__":
    main()
