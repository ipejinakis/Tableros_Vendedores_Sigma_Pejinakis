"""Exporta a Excel TODA la tabla de ventas de un mes (ítem por ítem) para explorar qué columnas hay.

Lee los parquet locales (no llama a la API). Une la venta con cabecera de factura, artículo, vendedor y
cliente, y abre el JSON de `pedido_datos_adicionales` en columnas `da_<clave>`.

Uso (desde la raíz del repo, con el venv activo):
    python scripts/analisis/exportar_ventas_mes.py --mes 2026-08
Genera `../ventas_2026-08.xlsx` (junto a la carpeta del repo) con 3 hojas:
    ventas            todas las filas (incluye anuladas; columna `es_valida`)
    columnas          resumen de cada columna: tipo, % con dato, distintos, ejemplos
    origen_vs_datos   cruce de `origen` contra las claves del JSON (para decidir Axum vs Compre Ahora)
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--mes", default="2026-08", help="AAAA-MM")
ap.add_argument("--salida", default=None, help="ruta del xlsx (default: ../ventas_<mes>.xlsx)")
a = ap.parse_args()

cfg = load_settings()
st = Store(cfg.data_dir, cfg.store_format)
anio, mes = (int(x) for x in a.mes.split("-"))
dde = pd.Timestamp(anio, mes, 1)
hta = (dde + pd.offsets.MonthEnd(0)).date()
v = st.read_facts("fact_ventas_item", dde.date(), hta)
if v.empty:
    sys.exit(f"No hay ventas de {a.mes} en {cfg.data_dir}")
print(f"{a.mes}: {len(v):,} ítems, {v['factura_id'].nunique():,} facturas")


def unir(base: pd.DataFrame, tabla: str, clave: str, cols: list[str] | None = None, prefijo: str = "") -> pd.DataFrame:
    """Left join de una dimensión por `clave`, sin pisar columnas existentes (las repetidas se saltean)."""
    try:
        d = st.read_table(tabla)
    except Exception as e:  # noqa: BLE001
        print(f"  (sin {tabla}: {e})")
        return base
    d = d.drop_duplicates(clave)
    keep = [c for c in (cols or d.columns) if c in d.columns and c != clave and c not in base.columns]
    if not keep:
        return base
    d = d[[clave] + keep].rename(columns={c: f"{prefijo}{c}" for c in keep})
    return base.merge(d, on=clave, how="left")


v = unir(v, "dim_articulo", "articulo_id", ["proveedor", "marca", "categoria_unilever", "categoria_cobertura",
                                           "unidades_por_bulto", "litros_unitarios", "suspendido", "desactivado"], "art_")
v = unir(v, "dim_vendedor", "vendedor_id", None, "vend_")
v = unir(v, "dim_cliente", "cliente_id", None, "cli_")
# cabecera de factura: columnas que no estén ya en la venta (subtotal, total, pendiente, etc.)
try:
    f = pd.concat([st._read(p) for p in sorted(st.fact_dir("dim_factura").glob(f"{a.mes}.*"))], ignore_index=True)
    v = v.merge(f.drop_duplicates("factura_id")[["factura_id"] + [c for c in f.columns
                         if c not in v.columns and c != "factura_id"]], on="factura_id", how="left")
except Exception as e:  # noqa: BLE001
    print(f"  (sin dim_factura del mes: {e})")

v["es_valida"] = v["estado"] != "anulada"

# --- JSON de datos adicionales del pedido -> columnas da_<clave>
def _json(x):
    if x is None or (isinstance(x, float) and pd.isna(x)) or x is pd.NA:
        return {}
    try:
        d = json.loads(x) if isinstance(x, str) else x
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


if "pedido_datos_adicionales" in v.columns:
    da = pd.DataFrame([_json(x) for x in v["pedido_datos_adicionales"]]).add_prefix("da_")
    da.index = v.index
    v = pd.concat([v, da], axis=1)
    claves = [c for c in da.columns]
    v["da_claves"] = [",".join(sorted(k[3:] for k in claves if pd.notna(r[k]))) or "(null)" for _, r in da.iterrows()]

# fechas sin zona horaria para Excel
for c in v.columns:
    if isinstance(v[c].dtype, pd.DatetimeTZDtype):
        v[c] = v[c].dt.tz_localize(None)

# --- hoja columnas
filas = []
for c in v.columns:
    s = v[c]
    ej = [str(x)[:40] for x in s.dropna().astype(str).unique()[:4]]
    filas.append({"columna": c, "tipo": str(s.dtype), "pct_con_dato": round(100 * s.notna().mean(), 1),
                  "distintos": s.nunique(dropna=True), "ejemplos": " | ".join(ej)})
resumen = pd.DataFrame(filas)

# --- hoja origen vs datos adicionales (solo ventas válidas)
vv = v[v["es_valida"]]
if "da_claves" in vv.columns:
    cruce = (vv.groupby(["origen", "da_claves"], dropna=False)
             .agg(items=("factura_id", "size"), facturas=("factura_id", "nunique"), clientes=("cliente_id", "nunique"),
                  vendedores=("vendedor_id", "nunique"), neto=("importe_neto", "sum"))
             .reset_index().sort_values("neto", ascending=False))
else:
    cruce = pd.DataFrame()

salida = Path(a.salida) if a.salida else Path(cfg.data_dir).resolve().parents[1] / f"ventas_{a.mes}.xlsx"
with pd.ExcelWriter(salida, engine="openpyxl") as xw:
    v.to_excel(xw, sheet_name="ventas", index=False)
    resumen.to_excel(xw, sheet_name="columnas", index=False)
    cruce.to_excel(xw, sheet_name="origen_vs_datos", index=False)
    for ws in xw.book.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
print(f"\nColumnas: {len(v.columns)}  ->  {salida}")
print(resumen[["columna", "tipo", "pct_con_dato", "distintos"]].to_string(index=False))
