"""Vista del vendedor: solo sus propios números (facturación y premio, ritmo, cobertura y Mis Ventas).

Se abre desde `dashboards/app.py` cuando el usuario tiene rol vendedor. **El vendedor se toma SIEMPRE de la sesión
(`vendedor_id` del usuario), nunca de un control de la pantalla**, y todo se filtra antes de dibujar o descargar.
Toda la lógica está en `sigma_conn.tableros` (con tests); acá solo hay diseño.
"""
import sys
from datetime import date
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:  # pragma: no cover
    HERE = Path.cwd() / "dashboards"
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit.errors import StreamlitAPIException  # noqa: E402

from estilo import AZUL, GRIS_MARCA, TXT, esc, mostrar_logo, texto_grande  # noqa: E402
from sigma_conn import negocio as N  # noqa: E402
from sigma_conn import objetivos as O  # noqa: E402
from sigma_conn import tableros as TB  # noqa: E402
from sigma_conn.store import Store  # noqa: E402

try:
    st.set_page_config(page_title="Mis ventas", layout="wide")
except StreamlitAPIException:
    pass

_sesion = st.session_state.get("usuario")
if not _sesion or _sesion.get("rol") != "vendedor" or not _sesion.get("vendedor_id") or _sesion.get("debe_cambiar"):
    st.error("Acceso restringido: entrá por dashboards/app.py con tu usuario y clave.")
    st.stop()
VID = str(_sesion["vendedor_id"])          # el único vendedor que esta sesión puede ver


# ----------------------------------------------------------------------------- datos (caché de 5 minutos)
@st.cache_data(ttl=300, show_spinner="Leyendo datos…")
def cargar(data_dir: str, fmt: str, desde: date, hasta: date):
    """Ventas del rango + dimensiones y objetivos (los que falten vienen como None)."""
    store = Store(Path(data_dir), fmt)
    ventas = TB.cargar_ventas_rango(store, desde, hasta)
    tablas = {}
    for nombre in ("dim_articulo", "dim_vendedor", "dim_cliente", "obj_cobertura", "obj_mis_ventas", "cfg_campana_articulo",
                   "obj_club_faro", "cfg_club_faro_articulo"):
        try:
            tablas[nombre] = store.read_table(nombre)
        except FileNotFoundError:
            tablas[nombre] = None
    return ventas, tablas, store.read_meta()


store = TB.abrir_store()
meses = TB.meses_disponibles(store)
if not meses:
    st.error("No hay ventas cargadas todavía.")
    st.stop()

sb = st.sidebar
mes = sb.selectbox("Mes", list(reversed(meses)))
inicio_b, fin_b = TB.bimestre_de(mes)
anio, m = (int(x) for x in mes.split("-"))
inicio_m = date(anio, m, 1)
fin_m = (pd.Timestamp(inicio_m) + pd.offsets.MonthEnd(0)).date()
try:
    ventas, tablas, meta = cargar(str(store.root), store.fmt, min(inicio_m, inicio_b), max(fin_m, fin_b))
except FileNotFoundError as exc:
    st.error(f"Falta una tabla: {exc}")
    st.stop()
dim_art, dim_vend = tablas["dim_articulo"], tablas["dim_vendedor"]
if dim_art is None or dim_vend is None:
    st.error("Faltan las tablas de artículos o vendedores. Avisar al administrador.")
    st.stop()

ventas_mes = ventas[(pd.to_datetime(ventas["fecha"]) >= pd.Timestamp(inicio_m)) & (pd.to_datetime(ventas["fecha"]) <= pd.Timestamp(fin_m))]
ultimo = TB.ultimo_dia_con_ventas(ventas_mes)
corte = sb.date_input("Corte (día inclusive)", value=min(ultimo or inicio_m, fin_m), min_value=inicio_m, max_value=fin_m)

# ----------------------------------------------------------------------------- facturación (solo este vendedor)
tabla_total, _ = TB.facturacion_vendedores(ventas_mes, dim_art, dim_vend, corte)
fila = tabla_total[tabla_total["vendedor_id"] == VID]
if fila.empty:
    st.error("Tu usuario no tiene una escala de facturación asociada. Avisar al administrador.")
    st.stop()
f = fila.iloc[0]
del tabla_total                            # a partir de acá solo existe la fila propia

mostrar_logo(180)
st.title(f"Hola, {_sesion['nombre']}")
st.caption(f"Mes {mes} · corte {corte:%d/%m/%Y} · datos actualizados {(meta or {}).get('written_at', 's/d')} · "
           "neto sin IVA, todos los canales (las notas de crédito restan).")
if ultimo and corte > ultimo:
    st.warning(f"No hay ventas posteriores al {ultimo:%d/%m/%Y}.")

c1, c2, c3 = st.columns(3)
c1.metric("Tu venta neta del mes", TB.fmt_millones(f["vendido"]), help="Neto sin IVA, hasta el día de corte.")
c1.caption(f"{O.dias_transcurridos(corte)} días de venta pasados · {O.dias_restantes(corte)} por venir")
c2.metric("Premio ganado hoy", TB.fmt_pesos(f["premio"]), help="El premio del escalón más alto que ya alcanzaste.")
c2.caption(f"Escalón {int(f['escalon'])}" if f["escalon"] else "Todavía sin escalón")
c3.metric("Premio a fin de mes", TB.fmt_pesos(f["premio_proyectado"]), help="Si seguís vendiendo al ritmo de hoy.")
c3.caption("Si seguís al ritmo actual")
st.markdown(f"### {f['estado_txt']}")

if f["siguiente_escalon"] == f["siguiente_escalon"] and f["siguiente_escalon"] is not None:
    sig = int(f["siguiente_escalon"])
    premio_sig = N.PREMIOS_ESCALON[sig - 1]
    premio_hoy = N.PREMIOS_ESCALON[sig - 2] if sig > 1 else 0
    falta = TB.fmt_millones(f["faltante_siguiente"])
    if premio_hoy:
        incentivo = (f"🎯 Te faltan <b>{falta}</b> para el escalón {sig}: tu premio sube de {TB.fmt_pesos(premio_hoy)} "
                     f"a <b>{TB.fmt_pesos(premio_sig)}</b> (+{TB.fmt_pesos(premio_sig - premio_hoy)}).")
    else:
        incentivo = f"🎯 Te faltan <b>{falta}</b> para el escalón 1 y ganar tu primer premio de <b>{TB.fmt_pesos(premio_sig)}</b>."
    texto_grande(incentivo)
    if f["media_necesaria"] is None or f["media_necesaria"] != f["media_necesaria"]:
        st.caption("Ya no quedan días de venta este mes.")
    else:
        st.caption(esc(f"Para llegar necesitás vender {TB.fmt_millones(f['media_necesaria'], 2)} por día de venta "
                       f"(tu ritmo actual es {TB.fmt_millones(f['ritmo_diario'], 2)} por día)."))
else:
    texto_grande(f"🏆 ¡Llegaste al último escalón! Tu premio es de <b>{TB.fmt_pesos(N.PREMIOS_ESCALON[-1])}</b>.")

escalones = pd.DataFrame({
    "escalon": [f"Escalón {i}" for i in (1, 2, 3)], "corto": ["E1", "E2", "E3"],
    "objetivo_m": [f["objetivo_esc1"] / 1e6, f["objetivo_esc2"] / 1e6, f["objetivo_esc3"] / 1e6],
    "premio_txt": [TB.fmt_pesos(p) for p in N.PREMIOS_ESCALON],
})
escalones["objetivo_txt"] = escalones["objetivo_m"].map(lambda x: f"{x:,.0f} M$".replace(",", "."))
escalones["etiqueta"] = escalones["escalon"] + " · " + escalones["objetivo_txt"]
tope = max(escalones["objetivo_m"].max() * 1.08, f["vendido"] / 1e6 * 1.05)
x = alt.X("x:Q", scale=alt.Scale(domain=[0, tope]), title="Venta neta del mes (M$)")
vend_df = pd.DataFrame({"x": [f["vendido"] / 1e6], "y": [""], "venta_txt": [TB.fmt_millones(f["vendido"])]})
barra = alt.Chart(vend_df).mark_bar(size=26, cornerRadiusEnd=4, color=TB.ESTADO_COLOR[f["estado"]]).encode(
    x=x, y=alt.Y("y:N", title=None, axis=None), tooltip=[alt.Tooltip("venta_txt:N", title="Vendido")])
marcas = alt.Chart(escalones.assign(x=escalones["objetivo_m"], y="")).mark_tick(color=GRIS_MARCA, thickness=3, size=40).encode(
    x=x, y=alt.Y("y:N", title=None, axis=None),
    tooltip=[alt.Tooltip("etiqueta:N", title="Objetivo"), alt.Tooltip("premio_txt:N", title="Premio")])
rotulos = alt.Chart(escalones.assign(x=escalones["objetivo_m"], y="")).mark_text(dy=-30, fontSize=11, color=TXT).encode(
    x=x, y=alt.Y("y:N", title=None, axis=None), text="corto:N")
st.altair_chart((barra + marcas + rotulos).properties(height=110, width="container"))
st.caption("La barra es lo que vendiste (color = tu estado); las marcas grises E1, E2 y E3 son los tres escalones del mes.")

_obj_cf = tablas["obj_club_faro"]
_tiene_cf = _obj_cf is not None and not _obj_cf[_obj_cf["vendedor_id"].astype(str) == VID].empty
_nombres_tabs = ["Mi ritmo", "Mi cobertura", "Mis campañas"] + (["Club Faro"] if _tiene_cf else []) + ["Mis canales"]
_tabs = dict(zip(_nombres_tabs, st.tabs(_nombres_tabs)))
tab_ritmo, tab_cob, tab_mv, tab_canal = _tabs["Mi ritmo"], _tabs["Mi cobertura"], _tabs["Mis campañas"], _tabs["Mis canales"]

# ----------------------------------------------------------------------------- ritmo
with tab_ritmo:
    rit = TB.ritmo_mes(ventas_mes, dim_art, corte, [VID])
    nombres = {"acumulado": "Vendido acumulado", "esc1": "Ruta escalón 1", "esc2": "Ruta escalón 2", "esc3": "Ruta escalón 3"}
    largo = rit.melt(id_vars="fecha", value_vars=list(nombres), var_name="clave", value_name="monto").dropna()
    largo["serie"] = largo["clave"].map(nombres)
    largo["monto_txt"] = largo["monto"].map(TB.fmt_millones)
    orden = list(nombres.values())
    color = alt.Color("serie:N", title=None, sort=orden, legend=alt.Legend(orient="top"),
                      scale=alt.Scale(domain=orden, range=[AZUL, GRIS_MARCA, GRIS_MARCA, GRIS_MARCA]))
    trazo = alt.StrokeDash("serie:N", sort=orden, legend=None,
                           scale=alt.Scale(domain=orden, range=[[1, 0], [2, 2], [6, 3], [10, 4]]))
    xx = alt.X("fecha:T", title=None, axis=alt.Axis(format="%d/%m"))
    yy = alt.Y("monto:Q", title="Neto s/IVA acumulado ($)", axis=alt.Axis(format="~s"))
    base = alt.Chart(largo)
    lineas = base.mark_line(strokeWidth=2).encode(x=xx, y=yy, color=color, strokeDash=trazo)
    puntos = base.mark_circle(size=140, opacity=0).encode(
        x=xx, y=yy, tooltip=[alt.Tooltip("fecha:T", title="Día", format="%d/%m/%Y"), alt.Tooltip("serie:N", title="Serie"),
                             alt.Tooltip("monto_txt:N", title="Monto")])
    st.altair_chart((lineas + puntos).properties(height=340, width="container"))
    st.caption("La línea azul es lo que vendiste día a día. Las grises son el camino recto hacia cada escalón: si la azul va "
               "por encima de una, vas en camino a ese escalón.")


def _barras_avance(df: pd.DataFrame, y_col: str, orden_y: list[str]) -> alt.LayerChart:
    g = df.assign(
        etiqueta=df["estado_txt"].str[0] + " " + df["logrado"].map("{:,.0f}".format).str.replace(",", ".") + " / "
        + df["objetivo"].map("{:,.0f}".format).str.replace(",", "."),
        avance_pct=df["avance"].clip(upper=1.5), avance_txt=(df["avance"] * 100).map("{:.0f}%".format),
        esperado_txt=df["esperado_valor"].map("{:,.0f}".format).str.replace(",", "."),
        faltan_txt=df["faltan"].map("{:,.0f}".format).str.replace(",", "."))
    yv = alt.Y(f"{y_col}:N", sort=orden_y, title=None, axis=alt.Axis(labelLimit=260))
    xv = alt.X("avance_pct:Q", scale=alt.Scale(domain=[0, 1.7]),
               axis=alt.Axis(format="%", values=[0, 0.5, 1.0, 1.5], title="Avance sobre el objetivo"))
    col = alt.Color("estado_txt:N", title="Estado", sort=list(TB.ESTADO_AVANCE_TXT.values()),
                    scale=alt.Scale(domain=list(TB.ESTADO_AVANCE_TXT.values()),
                                    range=[TB.ESTADO_COLOR[e] for e in TB.ESTADO_AVANCE_TXT]),
                    legend=alt.Legend(orient="top"))
    tips = [alt.Tooltip(f"{y_col}:N", title="Objetivo"), alt.Tooltip("etiqueta:N", title="Logrado / objetivo"),
            alt.Tooltip("avance_txt:N", title="Avance"), alt.Tooltip("esperado_txt:N", title="Esperado a hoy"),
            alt.Tooltip("faltan_txt:N", title="Faltan"), alt.Tooltip("estado_txt:N", title="Estado")]
    barras = alt.Chart(g).mark_bar(size=18, cornerRadiusEnd=4).encode(y=yv, x=xv, color=col, tooltip=tips)
    texto = alt.Chart(g).mark_text(align="left", dx=5, fontSize=11, color=TXT).encode(y=yv, x=xv, text="etiqueta:N")
    esperado = alt.Chart(g).mark_tick(color=GRIS_MARCA, thickness=2, size=26).encode(y=yv, x=alt.X("esperado_pct:Q"))
    return (barras + texto + esperado).properties(height=60 * len(orden_y) + 40, width="container")


# ----------------------------------------------------------------------------- cobertura
with tab_cob:
    obj_cob = tablas["obj_cobertura"]
    if obj_cob is None:
        st.info("Todavía no están cargados los objetivos de cobertura.")
    else:
        mis_obj = obj_cob[obj_cob["vendedor_id"].astype(str) == VID]
        if mis_obj.empty:
            st.info("No tenés objetivos de cobertura asignados.")
        else:
            tc, rc = TB.cobertura_vendedores(ventas, dim_art, dim_vend, mis_obj, inicio_b, fin_b, corte)
            tc = tc.rename(columns={"clientes": "logrado"}).assign(esperado_valor=lambda d: d["esperado_clientes"])
            st.write(f"Clientes distintos que te compraron cada categoría en el bimestre {inicio_b:%d/%m} – {fin_b:%d/%m/%Y}. "
                     f"Avance esperado a hoy: **{rc['esperado_pct'] * 100:.0f}%**.")
            st.altair_chart(_barras_avance(tc, "categoria", list(N.CATEGORIAS_COBERTURA)))
            st.caption("La barra es tu avance sobre el objetivo; la marca gris es lo que deberías llevar a hoy. "
                       "✔ en ritmo · ▲ algo atrasado (80 % a 100 % de lo esperado) · ✖ atrasado.")
            st.dataframe(tc.assign(**{"Avance (%)": tc["avance"] * 100})[["categoria", "logrado", "objetivo", "Avance (%)", "estado_txt"]]
                         .rename(columns={"categoria": "Categoría", "logrado": "Clientes con compra", "objetivo": "Objetivo",
                                          "estado_txt": "Estado"}), hide_index=True,
                         column_config={"Objetivo": st.column_config.NumberColumn(format="%.0f"),
                                        "Avance (%)": st.column_config.NumberColumn(format="%.0f%%")})

# ----------------------------------------------------------------------------- Mis Ventas
with tab_mv:
    obj_mv, cfg_camp = tablas["obj_mis_ventas"], tablas["cfg_campana_articulo"]
    if obj_mv is None or cfg_camp is None:
        st.info("Todavía no están cargados los objetivos de campañas.")
    else:
        mis_mv = obj_mv[obj_mv["vendedor_id"].astype(str) == VID]
        if mis_mv.empty:
            st.info("No tenés objetivos de campañas asignados.")
        else:
            mv = TB.mis_ventas_vendedores(ventas, dim_art, dim_vend, mis_mv, cfg_camp, inicio_b, fin_b, corte)
            mv = mv.rename(columns={"logrado": "logrado", "target": "objetivo"})
            if int((cfg_camp["fuente"] == "por defecto (S)").sum()):
                st.warning("Resultados provisorios: todavía no están confirmados los artículos de cada campaña.")
            st.write(f"Campañas del bimestre {inicio_b:%d/%m} – {fin_b:%d/%m/%Y}. Cobertura = clientes distintos que compraron; "
                     "volumen = unidades vendidas (las notas de crédito restan).")
            st.altair_chart(_barras_avance(mv, "panel", list(mv.sort_values(["campana", "tipo"])["panel"])))
            st.dataframe(mv.assign(**{"Avance (%)": mv["avance"] * 100})[["panel", "logrado", "objetivo", "Avance (%)", "estado_txt"]]
                         .rename(columns={"panel": "Campaña", "logrado": "Logrado", "objetivo": "Objetivo", "estado_txt": "Estado"}),
                         hide_index=True, column_config={"Logrado": st.column_config.NumberColumn(format="%.0f"),
                                                         "Objetivo": st.column_config.NumberColumn(format="%.0f"),
                                                         "Avance (%)": st.column_config.NumberColumn(format="%.0f%%")})

# ----------------------------------------------------------------------------- Club Faro
if _tiene_cf:
    with _tabs["Club Faro"]:
        mis_cf = _obj_cf[_obj_cf["vendedor_id"].astype(str) == VID]
        cfg_cf, dim_cli = tablas["cfg_club_faro_articulo"], tablas["dim_cliente"]
        if cfg_cf is None or dim_cli is None:
            st.info("Todavía no están cargados los artículos de Club Faro.")
        else:
            cf, rcf = TB.club_faro_vendedores(ventas, dim_art, dim_cli, dim_vend, cfg_cf, mis_cf, inicio_b, fin_b, corte)
            cf = cf[(cf["vendedor_id"].astype(str) == VID) & (cf["estado"] != "sin_objetivo")]   # el panel del vendedor muestra solo lo que tiene objetivo
            if int((cfg_cf["fuente"] == "por defecto (S)").sum()):
                st.warning("Resultados provisorios: todavía no están confirmados los artículos de cada línea.")
            st.write(f"Clientes que te compraron cada línea de Club Faro en el bimestre {inicio_b:%d/%m} – {fin_b:%d/%m/%Y}. "
                     f"Con 1 unidad el cliente ya suma. Avance esperado a hoy: **{rcf['esperado_pct'] * 100:.0f}%**.")
            st.altair_chart(_barras_avance(cf, "panel", [i["nombre"] for i in N.CLUB_FARO_LINEAS.values() if i["nombre"] in set(cf["panel"])]))
            faltan_txt = " · ".join(f"{r.panel}: <b>{r.faltan:,.0f}</b>".replace(",", ".") for r in cf.itertuples() if r.faltan > 0)
            if faltan_txt:
                texto_grande(f"🎯 Te faltan clientes para cumplir: {faltan_txt}")
            else:
                texto_grande("🏆 ¡Cumpliste todos tus objetivos de Club Faro!")
            st.caption("La barra es tu avance sobre el objetivo; la marca gris es lo que deberías llevar a hoy. "
                       "✔ en ritmo · ▲ algo atrasado (80 % a 100 % de lo esperado) · ✖ atrasado.")
            st.dataframe(cf.assign(**{"Avance (%)": cf["avance"] * 100})[["panel", "logrado", "objetivo", "faltan", "Avance (%)", "estado_txt"]]
                         .rename(columns={"panel": "Línea", "logrado": "Clientes con compra", "objetivo": "Objetivo",
                                          "faltan": "Faltan", "estado_txt": "Estado"}), hide_index=True,
                         column_config={"Objetivo": st.column_config.NumberColumn(format="%.0f"),
                                        "Faltan": st.column_config.NumberColumn(format="%.0f"),
                                        "Avance (%)": st.column_config.NumberColumn(format="%.0f%%")})

# ----------------------------------------------------------------------------- canales
with tab_canal:
    canales = pd.DataFrame({"Canal": ["Axum", "Compre Ahora", "Directa"],
                            "Venta neta (M$)": [f["Axum"] / 1e6, f["Compre Ahora"] / 1e6, f["Directa"] / 1e6]})
    st.dataframe(canales, hide_index=True, column_config={"Venta neta (M$)": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Directa = cargas hechas directamente en SIGMA y notas de crédito. Tu objetivo se mide sobre el total de los tres.")
