"""Diagnóstico: compara una campaña de Mis Ventas con un reporte de SIGMA, vendedor por vendedor.

Uso (desde la raíz del repo, venv activo):
    python scripts/analisis/comparar_campana.py "DOVE" 2026-09-01 2026-10-15 [vendedor_id[,vendedor_id...]] [articulo_id,articulo_id,...]

Si pasás la lista de artículos (5.º argumento) se compara contra esa campaña y no se imprime el listado largo.

Muestra (1) todos los artículos cuya descripción contiene el texto y si están en la campaña,
(2) unidades por vendedor con distintos criterios, para ver de dónde sale la diferencia con el reporte.
Solo lee: no modifica datos.
"""
import sys
from pathlib import Path
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
from sigma_conn import transform as T  # noqa: E402

texto = sys.argv[1].upper()
ini, fin = pd.Timestamp(sys.argv[2]), pd.Timestamp(sys.argv[3])
solo = [x for x in sys.argv[4].split(",") if x] if len(sys.argv) > 4 and sys.argv[4] != "-" else None
ids_dados = [x for x in sys.argv[5].split(",") if x] if len(sys.argv) > 5 else None
silver = RAIZ / "data" / "silver"

v = pd.concat([pd.read_parquet(f) for f in sorted((silver / "fact_ventas_item").glob("*.parquet"))])
v["fecha"] = pd.to_datetime(v["fecha"])
v = v[(v["fecha"] >= ini) & (v["fecha"] <= fin)]
art = pd.read_parquet(silver / "dim_articulo.parquet").drop_duplicates("articulo_id")
vend = pd.read_parquet(silver / "dim_vendedor.parquet").drop_duplicates("vendedor_id")
cfg = pd.read_parquet(silver / "cfg_campana_articulo.parquet")
print("Última fecha en la base:", v["fecha"].max().date(), "| estados:", v["estado"].value_counts().to_dict())

a = art[art["descripcion"].astype(str).str.upper().str.contains(texto, na=False)].copy()
en_camp = set(cfg[cfg["incluir"].astype(bool)]["articulo_id"].astype(str))
# la campaña vigente (ids) sale también de data/config/campanas_bimestre.json
import json
try:
    j = json.load(open(RAIZ / "data" / "config" / "campanas_bimestre.json"))
    for per, d in j["datos"]["mis_ventas"].items():
        for k, ids in d["definicion"]["articulos"].items():
            if texto[:4] in k.upper():
                print(f"Campaña {k} ({per}) en config:", ids)
                en_camp |= set(map(str, ids))
except Exception as e:
    print("sin config de campañas:", e)
a["en_campana"] = a["articulo_id"].astype(str).isin(en_camp)
u = v[v["articulo_id"].isin(a["articulo_id"])].groupby("articulo_id")["unidades"].sum()
a["unidades_periodo"] = a["articulo_id"].map(u).fillna(0)
cols = [c for c in ["articulo_id", "descripcion", "proveedor", "division", "en_campana", "unidades_periodo"] if c in a.columns]
if not ids_dados:
    print("\n(1) Artículos que contienen", texto); print(a[cols].to_string(index=False))

ids_all = set(a["articulo_id"]); ids_camp = set(a[a["en_campana"]]["articulo_id"])
def por_vendedor(df, ids, nc="neto"):
    d = df[df["articulo_id"].isin(ids)]
    if nc == "sin_nc":
        d = d[~d["es_nc"].astype(bool)]
    return d.groupby("vendedor_id")["unidades"].sum()
vo = T.ventas_para_objetivos(v, art)           # base del dashboard
vv = T.ventas_validas(v)                       # sin anuladas, sin filtros de objetivos
res = pd.DataFrame({
    "dashboard(campaña, neto)": por_vendedor(vo, ids_camp),
    "campaña sin restar NC": por_vendedor(vo, ids_camp, "sin_nc"),
    "todos los '"+texto+"' (neto)": por_vendedor(vo, ids_all),
    "todos, sin filtros objetivos": por_vendedor(vv, ids_all),
    "todos, incl. anuladas": por_vendedor(v, ids_all),
}).fillna(0)
if ids_dados:
    res["campaña completa (ids dados, neto)"] = por_vendedor(vo, set(ids_dados))
    res = res.fillna(0)
res.insert(0, "vendedor", [vend.set_index("vendedor_id")["nombre"].to_dict().get(i, i) for i in res.index])
if solo: res = res[res.index.astype(str).isin(solo)]
print("\n(2) Unidades por vendedor"); print(res.to_string())
if solo and len(solo) == 1:
    solo = solo[0]
    d = vv[(vv["vendedor_id"].astype(str) == solo) & vv["articulo_id"].isin(ids_all)]
    print("\n(3) Detalle del vendedor", solo)
    print(d.groupby(["articulo_id", "es_nc"])["unidades"].agg(["sum", "count"]).to_string())

    if ids_dados:
        u = vv[(vv["vendedor_id"].astype(str) == solo) & vv["articulo_id"].isin(ids_dados)]
        u = u[u["fecha"] >= fin - pd.Timedelta(days=4)]
        cols_u = [c for c in ["fecha", "articulo_id", "es_nc", "unidades", "cliente_id", "estado"] if c in u.columns]
        print("\n(4) Líneas de la campaña en los últimos 5 días (hasta el corte)")
        print(u.sort_values("fecha")[cols_u].to_string(index=False))
        nc = vv[(vv["vendedor_id"].astype(str) == solo) & vv["articulo_id"].isin(ids_dados) & vv["es_nc"].astype(bool)]
        print("\n(5) Todas las NC de la campaña del vendedor")
        print(nc.sort_values("fecha")[cols_u].to_string(index=False))
