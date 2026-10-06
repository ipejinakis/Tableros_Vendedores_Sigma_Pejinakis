"""Valida la base y los tableros contra el "Informe de ventas Detalladas" de SIGMA (Excel exportado de SIGMA ERP).

A diferencia del informe viejo, este trae el CÓDIGO de artículo, el proveedor, el canal del cliente, unidades, bultos,
comprobante y vendedor. Se pueden pasar varios archivos (p. ej. septiembre completo + octubre hasta hoy); se compara
SOLO el rango de fechas que cubre el reporte. No escribe nada: solo imprime resúmenes.

Secciones:
  A) Neto total y por vendedor (reporte vs base sin anuladas) y por proveedor.
  B) Diferencias por (fecha, cliente, artículo): solo en reporte / solo en base / distinto monto, explicando las anuladas.
  C) Canal del reporte vs rubro y canal de 11 Titulares según la base (¿el mapeo de canales coincide con SIGMA?).
  D) Club Faro: clientes con compra por vendedor y línea con los datos del reporte y de la base (misma función del tablero).
  E) 11 Titulares: CCC por línea y por canal con los datos del reporte y de la base (misma función del tablero).

Uso (desde la raíz del repo, venv activo):
    python scripts/analisis/validar_reporte_detallado.py "../Informe de venta detalladaSEP01-31.xlsx" "../Informe de venta detallaOCT01-06(mediodia).xlsx"
    python scripts/analisis/validar_reporte_detallado.py ... --top 30
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import negocio as N  # noqa: E402
from sigma_conn import tableros as TB  # noqa: E402
from sigma_conn import transform as T  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("reportes", nargs="+")
ap.add_argument("--top", type=int, default=15)
a = ap.parse_args()
pd.options.display.width = 250
pd.options.display.max_colwidth = 40
pd.options.display.max_rows = 200
pd.options.display.float_format = "{:,.2f}".format


# ------------------------------------------------------------------ lectura de los reportes
def _norm(c) -> str:
    return re.sub(r"[^a-z]", "", str(c).lower())          # "Código" y "C�digo" -> "cdigo"


def leer(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=2, dtype=str)
    raw.columns = [_norm(c) for c in raw.columns]
    faltan = {"cuenta", "tipo", "comprobante", "fecha", "cdigo", "descripcin", "proveedor", "unidades", "neto", "ven", "canal"} - set(raw.columns)
    if faltan:
        sys.exit(f"{path}: faltan columnas {sorted(faltan)} (encontré {list(raw.columns)})")
    raw = raw[raw["fecha"].notna() & raw["neto"].notna()].copy()
    out = pd.DataFrame({
        "canal_rep": raw["canal"].str.strip().str.upper(),
        "cliente_id": raw["cuenta"].str.strip(),
        "tipo": raw["tipo"].str.strip().str.upper(),
        "comprobante": raw["comprobante"].str.strip(),
        "fecha": pd.to_datetime(raw["fecha"]).dt.normalize(),
        "articulo_id": raw["cdigo"].str.strip(),
        "desc": raw["descripcin"].str.strip(),
        "proveedor": raw["proveedor"].str.strip(),
        "unidades": pd.to_numeric(raw["unidades"]),
        "neto": pd.to_numeric(raw["neto"]),
        "vendedor_id": raw["ven"].str.strip().str.lstrip("0"),
    })
    out["archivo"] = Path(path).name
    return out


rep = pd.concat([leer(p) for p in a.reportes], ignore_index=True)
dup = rep.duplicated(["tipo", "comprobante", "articulo_id", "cliente_id", "fecha", "unidades", "neto"], keep=False)
desde, hasta = rep["fecha"].min().date(), rep["fecha"].max().date()
print(f"Reporte: {len(rep)} líneas, {desde} a {hasta}, neto {rep['neto'].sum():,.2f}, vendedores {rep['vendedor_id'].nunique()}, "
      f"clientes {rep['cliente_id'].nunique()}")
if dup.any():
    print(f"AVISO: {int(dup.sum())} líneas repetidas entre archivos (¿se pisan las fechas?). Revisar antes de confiar en los totales.")

store = TB.abrir_store()
ven = store.read_facts("fact_ventas_item", desde, hasta)
dim_art, dim_cli, dim_vend = store.read_table("dim_articulo"), store.read_table("dim_cliente"), store.read_table("dim_vendedor")
for c in ("vendedor_id", "cliente_id", "articulo_id"):
    ven[c] = ven[c].astype(str)
# El informe trae solo algunos proveedores: se compara la base restringida a los mismos (los demás no están en el reporte).
_prov = dim_art.drop_duplicates("articulo_id").assign(articulo_id=lambda d: d["articulo_id"].astype(str)).set_index("articulo_id")["proveedor"].astype(str).str.strip()
provs = sorted(set(rep["proveedor"]))
print(f"Proveedores en el reporte: {provs} (la base se compara solo con esos)")
ven = ven[ven["articulo_id"].map(_prov).isin(provs)].copy()
db = T.ventas_validas(ven).copy()
anul = ven[ven["estado"] == T.ESTADO_ANULADA]
print(f"Base: {len(db)} ítems válidos, neto {db['importe_neto'].sum():,.2f} | anulados: {len(anul)} ítems, neto {anul['importe_neto'].sum():,.2f}")
ult = pd.to_datetime(db["fecha"]).max().date()
if ult < hasta:
    print(f"AVISO: la base llega hasta {ult} y el reporte hasta {hasta}: las diferencias de los últimos días son esperables (correr el ETL de ventas).")

# ------------------------------------------------------------------ A) totales
nombres = dim_vend.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype(str)).set_index("vendedor_id")["nombre"]
A = pd.concat([rep.groupby("vendedor_id")["neto"].sum().rename("reporte"), db.groupby("vendedor_id")["importe_neto"].sum().rename("base")], axis=1).fillna(0)
A["dif"] = A["reporte"] - A["base"]
A.insert(0, "vendedor", A.index.map(nombres))
print("\n== A) Neto por vendedor (reporte vs base sin anuladas) ==")
print(A.sort_values("dif", key=abs, ascending=False).head(a.top).to_string())
print(f"TOTAL reporte {A['reporte'].sum():,.2f} | base {A['base'].sum():,.2f} | dif {A['dif'].sum():,.2f} ({A['dif'].sum() / max(A['reporte'].sum(), 1) * 100:.3f}% del reporte)")
prov_db = db.merge(dim_art.drop_duplicates("articulo_id").assign(articulo_id=lambda d: d["articulo_id"].astype(str))[["articulo_id", "proveedor"]], on="articulo_id", how="left")
P = pd.concat([rep.groupby("proveedor")["neto"].sum().rename("reporte"), prov_db.groupby("proveedor")["importe_neto"].sum().rename("base")], axis=1).fillna(0)
P["dif"] = P["reporte"] - P["base"]
print("\nNeto por proveedor:")
print(P.sort_values("reporte", ascending=False).head(a.top).to_string())

# ------------------------------------------------------------------ B) por fecha-cliente-artículo
K = ["fecha", "cliente_id", "articulo_id"]
r_k = rep.groupby(K).agg(un_rep=("unidades", "sum"), neto_rep=("neto", "sum")).reset_index()
d_k = db.assign(fecha=pd.to_datetime(db["fecha"]).dt.normalize()).groupby(K).agg(un_db=("unidades", "sum"), neto_db=("importe_neto", "sum")).reset_index()
m = r_k.merge(d_k, on=K, how="outer", indicator=True)
anul_k = set(map(tuple, anul.assign(fecha=pd.to_datetime(anul["fecha"]).dt.normalize())[K].drop_duplicates().to_numpy()))
m["dif_neto"] = m["neto_rep"].fillna(0) - m["neto_db"].fillna(0)
m["dif_un"] = m["un_rep"].fillna(0) - m["un_db"].fillna(0)
solo_rep, solo_db = m[m["_merge"] == "left_only"], m[m["_merge"] == "right_only"]
distinto = m[(m["_merge"] == "both") & ((m["dif_neto"].abs() > 1) | (m["dif_un"].abs() > 0.001))]
en_anul = solo_rep[[tuple(x) in anul_k for x in solo_rep[K].to_numpy()]]
print("\n== B) Diferencias por (fecha, cliente, artículo) ==")
print(f"Combinaciones: reporte {len(r_k)} | base {len(d_k)} | iguales {int(((m['_merge'] == 'both') & ~m.index.isin(distinto.index)).sum())}")
print(f"  solo en el reporte: {len(solo_rep)} (neto {solo_rep['neto_rep'].sum():,.2f}); de esas, anuladas en la base: {len(en_anul)} (neto {en_anul['neto_rep'].sum():,.2f})")
print(f"  solo en la base:    {len(solo_db)} (neto {solo_db['neto_db'].sum():,.2f})")
print(f"  en las dos con distinta cantidad o monto: {len(distinto)} (dif neto {distinto['dif_neto'].sum():,.2f})")
cols = K + ["un_rep", "un_db", "neto_rep", "neto_db", "dif_neto"]
if len(solo_rep.drop(en_anul.index)):
    print("\nSolo en el reporte (no anuladas en la base) — mayores:")
    print(solo_rep.drop(en_anul.index).sort_values("neto_rep", key=abs, ascending=False)[cols].head(a.top).to_string(index=False))
if len(solo_db):
    print("\nSolo en la base — mayores:")
    print(solo_db.sort_values("neto_db", key=abs, ascending=False)[cols].head(a.top).to_string(index=False))
if len(distinto):
    print("\nDistinta cantidad o monto — mayores:")
    print(distinto.sort_values("dif_neto", key=abs, ascending=False)[cols].head(a.top).to_string(index=False))

# ------------------------------------------------------------------ C) canal del reporte vs rubro/canal de la base
dc = dim_cli.drop_duplicates("cliente_id").assign(cliente_id=lambda d: d["cliente_id"].astype(str)).set_index("cliente_id")
cli_rep = rep.drop_duplicates("cliente_id").set_index("cliente_id")
cx = pd.DataFrame({"canal_reporte": cli_rep["canal_rep"], "rubro_base": cli_rep.index.map(dc["rubro"].astype(str).str.upper()),
                   "canal_11t": cli_rep.index.map(dc["rubro_cod"].astype(str).map(N.canal_titulares))})
print("\n== C) Canal del reporte vs rubro y canal de 11 Titulares (clientes distintos) ==")
print(pd.crosstab(cx["canal_reporte"], cx["canal_11t"], margins=True).to_string())
print("\nCanal del reporte × rubro de la base (los 40 pares más frecuentes):")
print(cx.value_counts(["canal_reporte", "rubro_base"]).head(40).to_string())
print(f"Clientes del reporte que no están en dim_cliente: {int(cx['rubro_base'].isin(['NAN', 'NONE', '<NA>']).sum())}")

# ------------------------------------------------------------------ reporte con forma de ventas (para usar las funciones de los tableros)
rep_v = pd.DataFrame({"fecha": rep["fecha"], "vendedor_id": rep["vendedor_id"], "cliente_id": rep["cliente_id"], "articulo_id": rep["articulo_id"],
                      "unidades": rep["unidades"], "es_nc": rep["tipo"].eq("NC"), "estado": "impaga", "importe_neto": rep["neto"]})
sin_art = rep.loc[~rep["articulo_id"].isin(set(dim_art["articulo_id"].astype(str))), "articulo_id"].unique()
if len(sin_art):
    print(f"\nAVISO: códigos del reporte que no existen en dim_articulo: {list(sin_art)[:10]}")
ven_f = ven.assign(es_nc=ven["es_nc"].astype(bool) if "es_nc" in ven.columns else ven["unidades"] < 0)

# ------------------------------------------------------------------ D) Club Faro
try:
    cfg_cf = store.read_table("cfg_club_faro_articulo")
except FileNotFoundError:
    cfg_cf = None
    print("\n(No hay cfg_club_faro_articulo: correr scripts/etl/cargar_club_faro.py)")
if cfg_cf is not None:
    ini = max(desde, TB.bimestre_de(f"{desde:%Y-%m}")[0])
    cr = TB.club_faro_compras(rep_v, dim_art, dim_cli, cfg_cf, ini, hasta)
    cd = TB.club_faro_compras(ven_f, dim_art, dim_cli, cfg_cf, ini, hasta)

    def _res(c: pd.DataFrame, col: str) -> pd.Series:
        out = {}
        for (vid, linea), g in c.groupby(["vendedor_id", "linea"]):
            out[(str(vid), linea)] = g["cliente_id"].nunique() if N.CLUB_FARO_LINEAS[linea]["modo"] == "clientes" else len(g)
        return pd.Series(out, name=col, dtype="float64")
    D = pd.concat([_res(cr, "reporte"), _res(cd, "base")], axis=1).fillna(0)
    print(f"\n== D) Club Faro ({ini} a {hasta}): clientes (o pares cliente-SKU en blancos dulces) por vendedor y línea ==")
    if len(D):
        D["dif"] = D["reporte"] - D["base"]
        D.index.names = ["vendedor_id", "linea"]
        print(D.to_string())
        print(f"Filas con diferencia: {int((D['dif'] != 0).sum())} de {len(D)} | totales por línea:")
        print(D.groupby(level="linea")[["reporte", "base", "dif"]].sum().to_string())
    kk = ["vendedor_id", "linea", "cliente_id", "articulo_id"]
    mm = cr.merge(cd, on=kk, how="outer", indicator=True)
    solo = mm[mm["_merge"] != "both"]
    print(f"Compras que están en un lado y no en el otro: {len(solo)}")
    if len(solo):
        print(solo.assign(solo_en=solo["_merge"].map({"left_only": "reporte", "right_only": "base"})).drop(columns="_merge").head(a.top * 2).to_string(index=False))

# ------------------------------------------------------------------ E) 11 Titulares
try:
    cfg_t = store.read_table("cfg_11_titulares_articulo")
except FileNotFoundError:
    cfg_t = None
    print("\n(No hay cfg_11_titulares_articulo: correr scripts/etl/cargar_11_titulares.py)")
if cfg_t is not None:
    ini, fin = TB.bimestre_de(f"{desde:%Y-%m}")
    rr = TB.titulares_resumen(rep_v, dim_art, dim_cli, cfg_t, ini, fin, hasta)
    rb = TB.titulares_resumen(ven_f, dim_art, dim_cli, cfg_t, ini, fin, hasta)
    print(f"\n== E) 11 Titulares ({ini} a {hasta}): clientes con compra (CCC), reporte vs base ==")
    E = pd.concat([rr["lineas"].assign(tipo="línea"), rr["canales"].assign(tipo="canal"), rr["subcanales"].assign(tipo="OP & VTK")])[["tipo", "nombre", "objetivo", "logrado"]].rename(columns={"logrado": "reporte"})
    E["base"] = pd.concat([rb["lineas"], rb["canales"], rb["subcanales"]])["logrado"].to_numpy()
    E["dif"] = E["reporte"] - E["base"]
    print(E.to_string(index=False))
    # sensibilidad de la regla de unidades: ¿cuánto cambian las líneas si el mínimo no fuera 1 bulto / 3 unidades?
    print("\nSensibilidad (base): CCC por línea si alcanzara con CUALQUIER compra (1 unidad):")
    sv = ven_f.copy()
    tmp = TB.titulares_compras(sv, dim_art.assign(unidades_por_bulto=1), dim_cli, cfg_t, ini, hasta)
    N_old = N.TITULARES_UNIDADES_NO_AS
    N.TITULARES_UNIDADES_NO_AS = 1
    try:
        tmp = TB.titulares_compras(sv, dim_art.assign(unidades_por_bulto=1), dim_cli, cfg_t, ini, hasta)
    finally:
        N.TITULARES_UNIDADES_NO_AS = N_old
    print(tmp.groupby("linea")["cliente_id"].nunique().rename("con_1_unidad").to_frame().join(
        rb["lineas"].set_index("linea")["logrado"].rename("regla_actual")).to_string())
