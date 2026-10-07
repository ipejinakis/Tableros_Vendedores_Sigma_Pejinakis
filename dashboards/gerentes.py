"""Tablero de gerentes: facturación por vendedor frente a su escala del mes, premios y corte por canal.

Correr (desde la raíz del repo, con el venv activo), con ingreso por usuario y clave:
    streamlit run dashboards/app.py

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

from estilo import esc, mostrar_logo  # noqa: E402
from sigma_conn import negocio as N  # noqa: E402
from sigma_conn import tableros as TB  # noqa: E402
from sigma_conn.store import Store  # noqa: E402

AZUL = "#2a78d6"      # serie única (azul de la paleta de referencia)
GRIS_MARCA = "#8a8a85"  # marcas de escalón: gris neutro, legible en claro y oscuro


# Color de las etiquetas de texto dentro de los gráficos. Altair dibuja el texto en negro por defecto (invisible en el
# tema oscuro) y detectar el tema desde Python no es confiable (st.context.theme se atrasa un rerun al cambiarlo, y
# dejaba el texto claro sobre fondo claro). Un gris medio fijo se lee en los dos temas: contraste 4,4:1 sobre fondo
# blanco y 4,3:1 sobre el fondo oscuro de Streamlit (#0e1117).
TXT = "#787878"   # todo mark_text debe llevar color=TXT (nunca dejar el color por defecto)

try:  # lo normal es entrar por app.py, que ya configuró la página
    st.set_page_config(page_title="Tablero de gerentes", layout="wide")
except StreamlitAPIException:
    pass

# Acceso: solo gerentes y supervisores con sesión iniciada (entrar por dashboards/app.py)
_sesion = st.session_state.get("usuario")
if not _sesion or _sesion.get("rol") not in ("gerente", "supervisor") or _sesion.get("debe_cambiar"):
    st.error("Acceso restringido: entrá por dashboards/app.py con tu usuario y clave.")
    st.stop()


# ----------------------------------------------------------------------------- datos (con caché de 5 minutos)
@st.cache_data(ttl=300, show_spinner="Leyendo datos…")
def cargar(data_dir: str, fmt: str, mes: str):
    store = Store(Path(data_dir), fmt)
    ventas = TB.cargar_ventas_mes(store, mes)
    return ventas, store.read_table("dim_articulo"), store.read_table("dim_vendedor"), store.read_meta()


@st.cache_data(ttl=300, show_spinner="Leyendo cobertura…")
def cargar_cobertura(data_dir: str, fmt: str, desde: date, hasta: date):
    store = Store(Path(data_dir), fmt)
    ventas = TB.cargar_ventas_rango(store, desde, hasta)
    try:
        obj = store.read_table("obj_cobertura")
    except FileNotFoundError:
        obj = None
    return ventas, obj


@st.cache_data(ttl=300, show_spinner="Leyendo Mis Ventas…")
def cargar_mis_ventas(data_dir: str, fmt: str):
    store = Store(Path(data_dir), fmt)
    faltan = []
    out = []
    for nombre in ("obj_mis_ventas", "cfg_campana_articulo"):
        try:
            out.append(store.read_table(nombre))
        except FileNotFoundError:
            out.append(None)
            faltan.append(nombre)
    return out[0], out[1], faltan


@st.cache_data(ttl=300, show_spinner="Leyendo Club Faro…")
def cargar_club_faro(data_dir: str, fmt: str):
    store = Store(Path(data_dir), fmt)
    faltan, out = [], []
    for nombre in ("obj_club_faro", "cfg_club_faro_articulo", "dim_cliente"):
        try:
            out.append(store.read_table(nombre))
        except FileNotFoundError:
            out.append(None)
            faltan.append(nombre)
    return out[0], out[1], out[2], faltan


@st.cache_data(ttl=300, show_spinner="Leyendo 11 Titulares…")
def cargar_titulares(data_dir: str, fmt: str):
    store = Store(Path(data_dir), fmt)
    faltan, out = [], []
    for nombre in ("cfg_11_titulares_articulo", "dim_cliente"):
        try:
            out.append(store.read_table(nombre))
        except FileNotFoundError:
            out.append(None)
            faltan.append(nombre)
    return out[0], out[1], faltan


store = TB.abrir_store()
meses = TB.meses_disponibles(store)
if not meses:
    st.error("No hay ventas cargadas. Correr el ETL (scripts/etl/run_etl.py).")
    st.stop()

# ----------------------------------------------------------------------------- filtros
sb = st.sidebar
sb.header("Filtros")
mes = sb.selectbox("Mes (Facturación, Ritmo y Por canal)", list(reversed(meses)))
try:
    ventas, dim_art, dim_vend, meta = cargar(str(store.root), store.fmt, mes)
except FileNotFoundError as exc:
    st.error(f"Falta una tabla: {exc}")
    st.stop()

anio, m = (int(x) for x in mes.split("-"))
inicio = date(anio, m, 1)
fin = (pd.Timestamp(inicio) + pd.offsets.MonthEnd(0)).date()
ultimo = TB.ultimo_dia_con_ventas(ventas)
corte = sb.date_input("Corte del mes (día inclusive)", value=min(ultimo or inicio, fin), min_value=inicio, max_value=fin)

# Los objetivos de Cobertura, Mis Ventas, Club Faro y 11 Titulares son BIMESTRALES: tienen su propio período y su propio corte.
MESES_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
bimestres = sorted({TB.bimestre_de(x)[0] for x in meses}, reverse=True)
sb.divider()
bim_sel = sb.selectbox("Bimestre (Cobertura, Mis Ventas, Club Faro y 11 Titulares)", bimestres,
                       format_func=lambda d: f"{MESES_ES[d.month - 1]}–{MESES_ES[d.month]} {d.year}")
ini_bim, fin_bim = TB.bimestre_de(f"{bim_sel:%Y-%m}")
try:
    _vb, _ = cargar_cobertura(str(store.root), store.fmt, ini_bim, fin_bim)
    ultimo_b = TB.ultimo_dia_con_ventas(_vb)
except FileNotFoundError:
    ultimo_b = None
corte_b = sb.date_input("Corte del bimestre (día inclusive)", value=min(ultimo_b or ini_bim, fin_bim), min_value=ini_bim, max_value=fin_bim)
sb.divider()

tabla_total, resumen = TB.facturacion_vendedores(ventas, dim_art, dim_vend, corte)
supervisores = sorted(s for s in tabla_total["supervisor"].unique() if s)
# Supervisores sin escala de preventa (p. ej. GERENCIA SLA): solo los ven los gerentes, como venta sin escalones
extra_sup = sorted(N.SUPERVISOR_SIN_ESCALA) if _sesion.get("rol") == "gerente" else []
sup_todos = sb.multiselect("Supervisor", supervisores + extra_sup, default=supervisores)
sup_sel = [s for s in sup_todos if s in supervisores]
sup_extra_sel = [s for s in sup_todos if s in extra_sup]
perfiles = [N.PERFIL_GENERAL, N.PERFIL_AASS, N.PERFIL_INTERIOR]
perfil_sel = sb.multiselect("Perfil de escala", perfiles, default=perfiles)
solo_con_venta = sb.checkbox("Ocultar vendedores sin ventas", value=False)

tabla = tabla_total[tabla_total["supervisor"].isin(sup_sel) & tabla_total["perfil"].isin(perfil_sel)]
if solo_con_venta:
    tabla = tabla[tabla["vendido"] != 0]

# ----------------------------------------------------------------------------- encabezado
mostrar_logo(180)
st.title("Facturación por vendedor")
datos_al = TB.fmt_actualizado(meta)
st.caption(
    f"Mes {mes} · corte {corte:%d/%m/%Y} · datos actualizados {datos_al} · neto sin IVA, todos los canales "
    "(Axum, Compre Ahora y Directa; las notas de crédito restan). No cuenta anuladas, Depósito Morillo ni "
    "heladeras y muebles de Unilever.")
if ultimo and corte > ultimo:
    st.warning(f"No hay ventas posteriores al {ultimo:%d/%m/%Y}: el corte es mayor que el último día con datos.")

def mostrar_sin_escala():
    """Venta de los vendedores de los supervisores sin escala (GERENCIA SLA) elegidos en el filtro: sin escalones ni premio."""
    for sup in sup_extra_sel:
        d = TB.ventas_sin_escala(ventas, dim_art, dim_vend, corte, N.SUPERVISOR_SIN_ESCALA[sup])
        st.subheader(f"{sup}: venta sin escala")
        st.caption(esc(f"Mes {mes} · corte {corte:%d/%m/%Y} · neto sin IVA, todos los canales. Sin escalones ni premio "
                       f"(no tienen escala de preventa). Total: {TB.fmt_millones(d['vendido'].sum())}"))
        st.dataframe(d.assign(**{"Venta neta (M$)": d["vendido"] / 1e6, "Axum (M$)": d["Axum"] / 1e6,
                                 "Compre Ahora (M$)": d["Compre Ahora"] / 1e6, "Directa (M$)": d["Directa"] / 1e6,
                                 "Otro (M$)": d["Otro"] / 1e6}).rename(columns={"vendedor_id": "Código", "vendedor": "Vendedor"})[
            ["Código", "Vendedor", "Venta neta (M$)", "Axum (M$)", "Compre Ahora (M$)", "Directa (M$)", "Otro (M$)"]],
            hide_index=True, column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                                            ("Venta neta (M$)", "Axum (M$)", "Compre Ahora (M$)", "Directa (M$)", "Otro (M$)")})


if tabla.empty:
    if sup_extra_sel:
        mostrar_sin_escala()
    else:
        st.info("No hay vendedores con esos filtros.")
    st.stop()

ne = tabla["estado"].value_counts()
n_esc = int((tabla["escalon"] > 0).sum())

# Fila 1: plata
c1, c2, c3, c4 = st.columns(4)
c1.metric("Venta neta del mes", TB.fmt_millones(tabla["vendido"].sum()), help="Neto sin IVA, todos los canales, hasta el día de corte.")
c1.caption(f"{resumen['dias_transcurridos']} días de venta pasados · {resumen['dias_restantes']} por venir")
c2.metric("Vendedores con escalón", f"{n_esc} de {len(tabla)}", help="Cuántos ya alcanzaron al menos el escalón 1 de su escala.")
c2.caption("Alcanzaron al menos el escalón 1")
c3.metric("Premios ganados hoy", TB.fmt_pesos(tabla["premio"].sum()), help="Suma de los premios de los escalones ya alcanzados.")
c3.caption("Con lo vendido hasta el corte")
c4.metric("Premios a fin de mes", TB.fmt_pesos(tabla["premio_proyectado"].sum()), help="Si cada vendedor sigue vendiendo al ritmo de hoy.")
c4.caption("Si siguen al ritmo actual")

# Fila 2: semáforo (ícono + texto, nunca solo color)
s1, s2, s3 = st.columns(3)
s1.metric(TB.ESTADO_TXT["verde"], int(ne.get("verde", 0)), help="Ya alcanzaron al menos el escalón 1.")
s2.metric(TB.ESTADO_TXT["amarillo"], int(ne.get("amarillo", 0)), help="Todavía no lo alcanzaron, pero al ritmo actual llegan al escalón 1.")
s3.metric(TB.ESTADO_TXT["rojo"], int(ne.get("rojo", 0)), help="Al ritmo actual no llegan al escalón 1.")

tab_fact, tab_ritmo, tab_cob, tab_mv, tab_cf, tab_11t, tab_canal, tab_escalas = st.tabs(
    ["Facturación", "Ritmo", "Cobertura", "Mis Ventas", "Club Faro", "11 Titulares", "Por canal", "Escalas y premios"])

# ----------------------------------------------------------------------------- pestaña facturación
with tab_fact:
    graf = tabla.assign(
        etiqueta=tabla["estado_txt"].str[0] + " " + tabla["vendedor"],      # ícono + nombre: el estado nunca va solo en color
        venta_txt=tabla["vendido"].map(TB.fmt_millones),
        escalon_txt=tabla["escalon"].map(lambda e: f"Escalón {e}" if e else "Sin escalón"),
        premio_txt=tabla["premio"].map(TB.fmt_pesos),
        proy_txt=tabla["proyeccion"].map(TB.fmt_millones),
        falta_txt=tabla["faltante_siguiente"].map(TB.fmt_millones),
    )
    tope = max(1.15, float(graf["pct_esc3"].max()) * 1.15)
    y = alt.Y("etiqueta:N", sort=alt.EncodingSortField("pct_esc3", order="descending"), title=None)
    x_dom = alt.Scale(domain=[0, tope])
    color_estado = alt.Color("estado_txt:N", title="Estado", sort=list(TB.ESTADO_TXT.values()),
                             scale=alt.Scale(domain=list(TB.ESTADO_TXT.values()), range=[TB.ESTADO_COLOR[e] for e in TB.ESTADO_TXT]),
                             legend=alt.Legend(orient="top"))
    detalle = [alt.Tooltip("vendedor:N", title="Vendedor"), alt.Tooltip("perfil:N", title="Perfil"),
               alt.Tooltip("venta_txt:N", title="Venta neta"), alt.Tooltip("estado_txt:N", title="Estado"),
               alt.Tooltip("escalon_txt:N", title="Escalón"), alt.Tooltip("premio_txt:N", title="Premio alcanzado"),
               alt.Tooltip("proy_txt:N", title="Proyección"), alt.Tooltip("falta_txt:N", title="Falta p/ siguiente")]
    barras = alt.Chart(graf).mark_bar(size=14, cornerRadiusEnd=4).encode(
        y=y, x=alt.X("pct_esc3:Q", scale=x_dom, axis=alt.Axis(format="%", title="Avance sobre el escalón 3 (100 % = último escalón)")),
        color=color_estado, tooltip=detalle)
    valor = alt.Chart(graf).mark_text(align="left", dx=6, fontSize=11, color=TXT).encode(y=y, x=alt.X("pct_esc3:Q", scale=x_dom), text="venta_txt:N")
    marca1 = alt.Chart(graf).mark_tick(color=GRIS_MARCA, thickness=2, size=20).encode(y=y, x=alt.X("tick_esc1:Q", scale=x_dom))
    marca2 = alt.Chart(graf).mark_tick(color=GRIS_MARCA, thickness=2, size=20).encode(y=y, x=alt.X("tick_esc2:Q", scale=x_dom))
    marca3 = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color=GRIS_MARCA, strokeDash=[4, 3]).encode(x=alt.X("x:Q", scale=x_dom))
    alto = 28 * len(graf) + 80
    st.altair_chart((barras + valor + marca1 + marca2 + marca3).properties(height=alto, width="container"))
    st.caption("Cada barra es lo vendido (color = estado del semáforo). Las marcas grises verticales son los escalones 1 y 2 "
               "de ese vendedor y la línea punteada es el escalón 3. Verde: ya alcanzó el escalón 1; amarillo: todavía no, "
               "pero al ritmo actual lo alcanza; rojo: al ritmo actual no llega. Pasá el mouse por una barra para ver el detalle.")

    disp = pd.DataFrame({
        "Vendedor": tabla["vendedor"], "Supervisor": tabla["supervisor"], "Perfil": tabla["perfil"],
        "Venta neta (M$)": tabla["vendido"] / 1e6,
        "% del escalón 1": tabla["avance_esc1"] * 100,
        "Estado": tabla["estado_txt"],
        "Escalón": tabla["escalon"].map(lambda e: str(e) if e else "—"),
        "Premio alcanzado": tabla["premio"].map(TB.fmt_pesos),
        "Premio al ritmo actual": tabla["premio_proyectado"].map(TB.fmt_pesos),
        "Proyección (M$)": tabla["proyeccion"] / 1e6,
        "Ritmo (M$/día)": tabla["ritmo_diario"] / 1e6,
        "Falta p/ siguiente (M$)": tabla["faltante_siguiente"] / 1e6,
        "Necesita (M$/día)": tabla["media_necesaria"] / 1e6,
    }).sort_values("Venta neta (M$)", ascending=False)
    st.dataframe(disp, hide_index=True, column_config={
        "Venta neta (M$)": st.column_config.NumberColumn(format="%.1f"),
        "% del escalón 1": st.column_config.NumberColumn(format="%.0f%%"),
        "Proyección (M$)": st.column_config.NumberColumn(format="%.1f"),
        "Ritmo (M$/día)": st.column_config.NumberColumn(format="%.2f"),
        "Falta p/ siguiente (M$)": st.column_config.NumberColumn(format="%.1f"),
        "Necesita (M$/día)": st.column_config.NumberColumn(format="%.2f"),
    })
    st.download_button("Descargar tabla (CSV)", tabla.to_csv(index=False).encode("utf-8"),
                       file_name=f"facturacion_{mes}_{corte:%Y%m%d}.csv", mime="text/csv")

    sin = resumen["sin_escala"]
    with st.expander(esc(f"Ventas de vendedores sin escala de preventa: {TB.fmt_millones(resumen['total_sin_escala'])}")):
        st.write("Entran en el total de la empresa pero no tienen escalones ni premio.")
        if sin.empty:
            st.write("Ninguno en este período.")
        else:
            st.dataframe(sin.assign(**{"Venta neta (M$)": sin["vendido"] / 1e6})[["vendedor_id", "vendedor", "Venta neta (M$)"]]
                         .rename(columns={"vendedor_id": "Código", "vendedor": "Vendedor"}), hide_index=True,
                         column_config={"Venta neta (M$)": st.column_config.NumberColumn(format="%.1f")})
        st.caption(esc(f"Total empresa (con y sin escala): {TB.fmt_millones(resumen['total_empresa'])}"))
    mostrar_sin_escala()

# ----------------------------------------------------------------------------- pestaña ritmo
with tab_ritmo:
    opciones = {"Todo el equipo (vendedores con escala)": None}
    opciones.update({f"{r.vendedor} ({r.vendedor_id})": [r.vendedor_id] for r in tabla.itertuples()})
    elegido = st.selectbox("Ver", list(opciones))
    ids = opciones[elegido] or list(tabla["vendedor_id"])
    rit = TB.ritmo_mes(ventas, dim_art, corte, ids)
    nombres = {"acumulado": "Vendido acumulado", "esc1": "Ruta escalón 1", "esc2": "Ruta escalón 2", "esc3": "Ruta escalón 3"}
    largo = rit.melt(id_vars="fecha", value_vars=list(nombres), var_name="clave", value_name="monto").dropna()
    largo["serie"] = largo["clave"].map(nombres)
    largo["monto_txt"] = largo["monto"].map(TB.fmt_millones)
    orden = list(nombres.values())
    color = alt.Color("serie:N", title=None, sort=orden, legend=alt.Legend(orient="top"),
                      scale=alt.Scale(domain=orden, range=[AZUL, GRIS_MARCA, GRIS_MARCA, GRIS_MARCA]))
    trazo = alt.StrokeDash("serie:N", sort=orden, legend=None,
                           scale=alt.Scale(domain=orden, range=[[1, 0], [2, 2], [6, 3], [10, 4]]))
    x = alt.X("fecha:T", title=None, axis=alt.Axis(format="%d/%m"))
    y_ = alt.Y("monto:Q", title="Neto s/IVA acumulado ($)", axis=alt.Axis(format="~s"))
    base = alt.Chart(largo)
    lineas = base.mark_line(strokeWidth=2).encode(x=x, y=y_, color=color, strokeDash=trazo)
    puntos = base.mark_circle(size=140, opacity=0).encode(
        x=x, y=y_, tooltip=[alt.Tooltip("fecha:T", title="Día", format="%d/%m/%Y"), alt.Tooltip("serie:N", title="Serie"),
                            alt.Tooltip("monto_txt:N", title="Monto")])
    ultimos = largo[largo["fecha"] == largo[largo["serie"] != nombres["acumulado"]]["fecha"].max()]
    etiquetas = alt.Chart(ultimos[ultimos["serie"] != nombres["acumulado"]]).mark_text(align="left", dx=6, fontSize=11, color=TXT).encode(
        x=alt.X("fecha:T"), y=alt.Y("monto:Q"), text="serie:N")
    st.altair_chart((lineas + puntos + etiquetas).properties(height=380, width="container"))
    st.caption("La línea azul es lo vendido día a día hasta el corte. Las líneas grises son el camino recto hacia cada escalón "
               "(objetivo × días de venta transcurridos / 26): si la azul va por encima de una, ese escalón va en camino. "
               "En el equipo, las rutas suman a todos los vendedores mostrados.")

# ----------------------------------------------------------------------------- pestaña cobertura
with tab_cob:
    ini_b, fin_b = ini_bim, fin_bim
    try:
        ventas_b, obj_cob = cargar_cobertura(str(store.root), store.fmt, ini_b, fin_b)
    except FileNotFoundError as exc:
        ventas_b, obj_cob = None, None
        st.error(f"Falta una tabla: {exc}")
    if obj_cob is None and ventas_b is not None:
        st.info("Faltan los objetivos de cobertura. Correr: python scripts/etl/cargar_objetivos.py")
    elif obj_cob is not None:
        tc_total, rc = TB.cobertura_vendedores(ventas_b, dim_art, dim_vend, obj_cob, ini_b, fin_b, corte_b)
        tc = tc_total[tc_total["vendedor_id"].isin(tabla["vendedor_id"])].copy()
        st.subheader("Cobertura: clientes con compra por categoría")
        st.caption(f"Bimestre {ini_b:%d/%m/%Y} – {fin_b:%d/%m/%Y} · corte {corte_b:%d/%m/%Y}. Un cliente cuenta una vez por categoría "
                   "si compró al menos una vez en el bimestre (los combos suman a su categoría; no cuentan anuladas, notas de "
                   f"crédito ni Depósito Morillo). Avance esperado a hoy: {rc['esperado_pct'] * 100:.0f}% (por días de venta).")
        if rc["periodo"] and rc["periodo"] != f"{ini_b:%Y-%m}/{fin_b:%Y-%m}":
            st.warning(f"Los objetivos cargados son del período {rc['periodo']}, no de este bimestre.")

        k = st.columns(len(N.CATEGORIAS_COBERTURA))
        for col, cat in zip(k, N.CATEGORIAS_COBERTURA):
            d = rc["por_categoria"][cat]
            col.metric(f"{cat} · toda la distribuidora", f"{d['clientes']:,} de {d['objetivo']:,.0f}".replace(",", "."),
                       help="Clientes distintos con compra de la categoría en el bimestre, contra el objetivo total.")
            col.caption(f"{TB.ESTADO_AVANCE_TXT[d['estado']]} · esperado a hoy: {d['esperado_clientes']:,.0f}".replace(",", "."))

        if tc.empty:
            st.info("No hay vendedores con esos filtros.")
        else:
            g = tc.assign(
                etiqueta=tc["estado_txt"].str[0] + " " + tc["clientes"].astype(str) + " / " + tc["objetivo"].map("{:.0f}".format),
                avance_pct=tc["avance"].clip(upper=1.5), avance_txt=(tc["avance"] * 100).map("{:.0f}%".format),
                esperado_txt=tc["esperado_clientes"].map("{:.0f}".format), faltan_txt=tc["faltan"].map("{:.0f}".format))
            orden = list(dict.fromkeys(tc.sort_values("vendedor")["vendedor"]))
            yv = alt.Y("vendedor:N", sort=orden, title=None)
            xv = alt.X("avance_pct:Q", scale=alt.Scale(domain=[0, 1.6]),
                       axis=alt.Axis(format="%", values=[0, 0.5, 1.0, 1.5], title="Avance sobre el objetivo"))
            color_c = alt.Color("estado_txt:N", title="Estado", sort=list(TB.ESTADO_AVANCE_TXT.values()),
                                scale=alt.Scale(domain=list(TB.ESTADO_AVANCE_TXT.values()),
                                                range=[TB.ESTADO_COLOR[e] for e in TB.ESTADO_AVANCE_TXT]),
                                legend=alt.Legend(orient="top"))
            tips = [alt.Tooltip("vendedor:N", title="Vendedor"), alt.Tooltip("categoria:N", title="Categoría"),
                    alt.Tooltip("clientes:Q", title="Clientes con compra"), alt.Tooltip("objetivo:Q", title="Objetivo", format=".0f"),
                    alt.Tooltip("avance_txt:N", title="Avance"), alt.Tooltip("esperado_txt:N", title="Esperado a hoy"),
                    alt.Tooltip("faltan_txt:N", title="Faltan"), alt.Tooltip("estado_txt:N", title="Estado")]
            barras_c = alt.Chart().mark_bar(size=12, cornerRadiusEnd=4).encode(y=yv, x=xv, color=color_c, tooltip=tips)
            texto_c = alt.Chart().mark_text(align="left", dx=5, fontSize=11, color=TXT).encode(y=yv, x=xv, text="etiqueta:N")
            esp = alt.Chart().mark_tick(color=GRIS_MARCA, thickness=2, size=18).encode(y=yv, x=alt.X("esperado_pct:Q"))
            graf_c = alt.layer(barras_c, texto_c, esp, data=g).properties(width=330, height=22 * len(orden) + 10).facet(
                facet=alt.Facet("categoria:N", sort=list(N.CATEGORIAS_COBERTURA), title=None), columns=2, spacing=24)
            st.altair_chart(graf_c)
            st.caption("La barra es el avance sobre el objetivo de ese vendedor; la marca gris es el avance esperado a hoy "
                       "(proporcional a los días de venta del bimestre). Texto: clientes con compra / objetivo.")

            wide = g.pivot(index="vendedor", columns="categoria", values="etiqueta").reindex(orden)
            wide = wide[[c for c in N.CATEGORIAS_COBERTURA if c in wide.columns]].reset_index().rename(columns={"vendedor": "Vendedor"})
            st.dataframe(wide, hide_index=True)
            st.download_button("Descargar cobertura (CSV)", tc.to_csv(index=False).encode("utf-8"),
                               file_name=f"cobertura_{ini_b:%Y%m}_{corte_b:%Y%m%d}.csv", mime="text/csv")
        sin_asig = dim_art.loc[dim_art["categoria_cobertura"] == "COMBO_SIN_ASIGNAR", "articulo_id"].astype(str).tolist() \
            if "categoria_cobertura" in dim_art.columns else []
        if sin_asig:
            st.warning("Hay combos sin categoría asignada (no suman a la cobertura): " + ", ".join(sin_asig) +
                       ". Agregarlos a COMBO_CATEGORIA en transform.py.")
        st.caption("Semáforo: ✔ en ritmo = va en o por encima del avance esperado (o ya cumplió); ▲ algo atrasado = entre 80 % y 100 % "
                   "de lo esperado; ✖ atrasado = por debajo del 80 % de lo esperado.")

# ----------------------------------------------------------------------------- pestaña Mis Ventas
with tab_mv:
    ini_m, fin_m = ini_bim, fin_bim
    obj_mv, cfg_camp, faltan_mv = cargar_mis_ventas(str(store.root), store.fmt)
    if faltan_mv:
        st.info("Faltan tablas: " + ", ".join(faltan_mv) + ". Correr scripts/etl/cargar_objetivos.py y scripts/etl/cargar_campanas.py")
    else:
        ventas_m, _ = cargar_cobertura(str(store.root), store.fmt, ini_m, fin_m)
        mv = TB.mis_ventas_vendedores(ventas_m, dim_art, dim_vend, obj_mv, cfg_camp, ini_m, fin_m, corte_b)
        mv = mv[mv["vendedor_id"].isin(tabla["vendedor_id"])].copy()
        st.subheader("Mis Ventas: campañas Unilever del bimestre")
        esp = TB.fraccion_esperada(ini_m, fin_m, corte_b)
        st.caption(f"Bimestre {ini_m:%d/%m/%Y} – {fin_m:%d/%m/%Y} · corte {corte_b:%d/%m/%Y} · avance esperado a hoy: {esp * 100:.0f}% "
                   "(por días de venta). Cobertura = clientes distintos con compra de la campaña; volumen = unidades netas "
                   "(las notas de crédito restan).")
        por_def = int((cfg_camp["fuente"] == "por defecto (S)").sum())
        if por_def:
            st.warning(f"{por_def} de {len(cfg_camp)} artículos de campaña cuentan como S por defecto (INCLUIR vacío en el Excel). "
                       "Los resultados son provisorios hasta que se marquen S o N.")
        if mv.empty:
            st.info("No hay vendedores con esos filtros.")
        else:
            k = st.columns(3)
            k[0].metric("Objetivos en ritmo", f"{int((mv['estado'] == 'verde').sum())} de {len(mv)}", help="Objetivos de campaña que van en o por encima del avance esperado.")
            k[1].metric("Algo atrasados", int((mv["estado"] == "amarillo").sum()))
            k[2].metric("Atrasados", int((mv["estado"] == "rojo").sum()))

            g = mv.assign(
                etiqueta=mv["estado_txt"].str[0] + " " + mv["logrado"].map("{:,.0f}".format).str.replace(",", ".") + " / "
                + mv["target"].map("{:,.0f}".format).str.replace(",", "."),
                avance_pct=mv["avance"].clip(upper=1.5), avance_txt=(mv["avance"] * 100).map("{:.0f}%".format),
                esperado_txt=mv["esperado_valor"].map("{:,.0f}".format).str.replace(",", "."),
                faltan_txt=mv["faltan"].map("{:,.0f}".format).str.replace(",", "."))
            orden_v = list(dict.fromkeys(mv.sort_values("vendedor")["vendedor"]))
            orden_p = list(dict.fromkeys(mv.sort_values(["campana", "tipo"])["panel"]))
            yv = alt.Y("vendedor:N", sort=orden_v, title=None)
            xv = alt.X("avance_pct:Q", scale=alt.Scale(domain=[0, 1.7]),
                       axis=alt.Axis(format="%", values=[0, 0.5, 1.0, 1.5], title="Avance sobre el target"))
            color_m = alt.Color("estado_txt:N", title="Estado", sort=list(TB.ESTADO_AVANCE_TXT.values()),
                                scale=alt.Scale(domain=list(TB.ESTADO_AVANCE_TXT.values()),
                                                range=[TB.ESTADO_COLOR[e] for e in TB.ESTADO_AVANCE_TXT]),
                                legend=alt.Legend(orient="top"))
            tips = [alt.Tooltip("vendedor:N", title="Vendedor"), alt.Tooltip("panel:N", title="Campaña"),
                    alt.Tooltip("etiqueta:N", title="Logrado / target"), alt.Tooltip("avance_txt:N", title="Avance"),
                    alt.Tooltip("esperado_txt:N", title="Esperado a hoy"), alt.Tooltip("faltan_txt:N", title="Faltan"),
                    alt.Tooltip("estado_txt:N", title="Estado")]
            b_m = alt.Chart().mark_bar(size=12, cornerRadiusEnd=4).encode(y=yv, x=xv, color=color_m, tooltip=tips)
            t_m = alt.Chart().mark_text(align="left", dx=5, fontSize=11, color=TXT).encode(y=yv, x=xv, text="etiqueta:N")
            e_m = alt.Chart().mark_tick(color=GRIS_MARCA, thickness=2, size=18).encode(y=yv, x=alt.X("esperado_pct:Q"))
            st.altair_chart(alt.layer(b_m, t_m, e_m, data=g).properties(width=330, height=22 * len(orden_v) + 10).facet(
                facet=alt.Facet("panel:N", sort=orden_p, title=None, header=alt.Header(labelLimit=330)), columns=2, spacing=24))
            st.caption("La barra es el avance sobre el target; la marca gris es el avance esperado a hoy. Texto: logrado / target. "
                       "Un vendedor aparece solo en las campañas donde tiene target (el 111 no tiene).")
            tabla_mv = g.rename(columns={"vendedor": "Vendedor", "panel": "Campaña", "estado_txt": "Estado"})
            tabla_mv = tabla_mv.assign(**{"Logrado": g["logrado"], "Target": g["target"], "Avance (%)": g["avance"] * 100})
            st.dataframe(tabla_mv[["Vendedor", "Campaña", "Estado", "Logrado", "Target", "Avance (%)"]].sort_values(["Campaña", "Vendedor"]),
                         hide_index=True, column_config={"Avance (%)": st.column_config.NumberColumn(format="%.0f%%"),
                                                         "Logrado": st.column_config.NumberColumn(format="%.0f"),
                                                         "Target": st.column_config.NumberColumn(format="%.0f")})
            st.download_button("Descargar Mis Ventas (CSV)", mv.to_csv(index=False).encode("utf-8"),
                               file_name=f"mis_ventas_{ini_m:%Y%m}_{corte_b:%Y%m%d}.csv", mime="text/csv")

# ----------------------------------------------------------------------------- pestaña Club Faro
with tab_cf:
    ini_f, fin_f = ini_bim, fin_bim
    obj_cf, cfg_cf, dim_cli, faltan_cf = cargar_club_faro(str(store.root), store.fmt)
    if faltan_cf:
        st.info("Faltan tablas: " + ", ".join(faltan_cf) + ". Correr scripts/etl/cargar_club_faro.py (y el ETL completo para dim_cliente).")
    else:
        ventas_f, _ = cargar_cobertura(str(store.root), store.fmt, ini_f, fin_f)
        cf, rcf = TB.club_faro_vendedores(ventas_f, dim_art, dim_cli, dim_vend, cfg_cf, obj_cf, ini_f, fin_f, corte_b)
        st.subheader("Club Faro (Peñaflor): clientes con compra por línea")
        st.caption(f"Bimestre {ini_f:%d/%m/%Y} – {fin_f:%d/%m/%Y} · corte {corte_b:%d/%m/%Y} · avance esperado a hoy: "
                   f"{rcf['esperado_pct'] * 100:.0f}% (por días de venta). Con comprar 1 unidad de un artículo de la línea el cliente "
                   "ya suma. Las líneas K+T cuentan clientes tradicionales (kioscos, almacenes, etc.); las AS, autoservicios "
                   "(rubros Autoservicio, AAS Gold y Cadena SAR). En blancos dulces cada SKU distinto por cliente suma 1.")
        por_def = int((cfg_cf["fuente"] == "por defecto (S)").sum())
        if por_def:
            st.warning(f"{por_def} de {len(cfg_cf)} artículos de Club Faro cuentan por defecto (INCLUIR vacío en el Excel): "
                       "los resultados son provisorios hasta que se marquen S o N.")
        if cf.empty:
            st.info("No hay objetivos de Club Faro cargados.")
        else:
            if cf["supuesto"].any():
                st.warning("Vendedores cruzados con la base por nombre aproximado (revisar): " + ", ".join(
                    f"{r.nombre_excel} (Excel) = {r.vendedor} ({r.vendedor_id})"
                    for r in cf[cf["supuesto"]].drop_duplicates("vendedor_id").itertuples()) + ".")
            sin_obj = cf[cf["estado"] == "sin_objetivo"]
            cf = cf[cf["estado"] != "sin_objetivo"]     # en el gráfico y las tarjetas solo van los que tienen objetivo
            k = st.columns(len(N.CLUB_FARO_LINEAS))
            for col, (linea, info) in zip(k, N.CLUB_FARO_LINEAS.items()):
                d = rcf["por_linea"][linea]
                col.metric(info["nombre"], f"{d['logrado']:,.0f} de {d['objetivo']:,.0f}".replace(",", "."),
                           help="Suma de todos los vendedores con objetivo en la línea.")
                col.caption(f"{TB.ESTADO_AVANCE_TXT[d['estado']]} · faltan {d['faltan']:,.0f} · esperado a hoy: "
                            f"{d['esperado_valor']:,.0f}".replace(",", "."))
            g = cf.assign(
                etiqueta=cf["estado_txt"].str[0] + " " + cf["logrado"].astype(str) + " / " + cf["objetivo"].map(lambda o: f"{o:.0f}" if o else "s/obj."),
                avance_pct=cf["avance"].clip(upper=1.5), avance_txt=(cf["avance"] * 100).map("{:.0f}%".format),
                esperado_txt=cf["esperado_valor"].map("{:.0f}".format), faltan_txt=cf["faltan"].map("{:.0f}".format))
            orden_v = list(dict.fromkeys(cf.sort_values("vendedor")["vendedor"]))
            orden_p = [info["nombre"] for info in N.CLUB_FARO_LINEAS.values()]
            yv = alt.Y("vendedor:N", sort=orden_v, title=None)
            xv = alt.X("avance_pct:Q", scale=alt.Scale(domain=[0, 1.7]),
                       axis=alt.Axis(format="%", values=[0, 0.5, 1.0, 1.5], title="Avance sobre el objetivo"))
            color_f = alt.Color("estado_txt:N", title="Estado", sort=list(TB.ESTADO_CF_TXT.values()),
                                scale=alt.Scale(domain=list(TB.ESTADO_CF_TXT.values()),
                                                range=[TB.ESTADO_COLOR[e] for e in TB.ESTADO_CF_TXT]),
                                legend=alt.Legend(orient="top"))
            tips = [alt.Tooltip("vendedor:N", title="Vendedor"), alt.Tooltip("panel:N", title="Línea"),
                    alt.Tooltip("etiqueta:N", title="Logrado / objetivo"), alt.Tooltip("avance_txt:N", title="Avance"),
                    alt.Tooltip("esperado_txt:N", title="Esperado a hoy"), alt.Tooltip("faltan_txt:N", title="Faltan"),
                    alt.Tooltip("estado_txt:N", title="Estado")]
            b_f = alt.Chart().mark_bar(size=12, cornerRadiusEnd=4).encode(y=yv, x=xv, color=color_f, tooltip=tips)
            t_f = alt.Chart().mark_text(align="left", dx=5, fontSize=11, color=TXT).encode(y=yv, x=xv, text="etiqueta:N")
            e_f = alt.Chart().mark_tick(color=GRIS_MARCA, thickness=2, size=18).encode(y=yv, x=alt.X("esperado_pct:Q"))
            st.altair_chart(alt.layer(b_f, t_f, e_f, data=g).properties(width=330, height=22 * len(orden_v) + 10).facet(
                facet=alt.Facet("panel:N", sort=orden_p, title=None, header=alt.Header(labelLimit=330)), columns=2, spacing=24))
            st.caption("La barra es el avance sobre el objetivo de ese vendedor; la marca gris es el avance esperado a hoy. "
                       "Texto: clientes con compra / objetivo. Lo que falta es lo que hay que conseguir hasta fin de octubre.")
            tabla_f = g.rename(columns={"vendedor": "Vendedor", "supervisor": "Supervisor", "panel": "Línea", "estado_txt": "Estado"})
            tabla_f = tabla_f.assign(**{"Logrado": g["logrado"], "Objetivo": g["objetivo"], "Faltan": g["faltan"],
                                        "Avance (%)": g["avance"] * 100})
            st.dataframe(tabla_f[["Vendedor", "Supervisor", "Línea", "Estado", "Logrado", "Objetivo", "Faltan", "Avance (%)"]]
                         .sort_values(["Línea", "Vendedor"]), hide_index=True,
                         column_config={"Avance (%)": st.column_config.NumberColumn(format="%.0f%%"),
                                        "Logrado": st.column_config.NumberColumn(format="%.0f"),
                                        "Objetivo": st.column_config.NumberColumn(format="%.0f"),
                                        "Faltan": st.column_config.NumberColumn(format="%.0f")})
            st.download_button("Descargar Club Faro (CSV)", cf.to_csv(index=False).encode("utf-8"),
                               file_name=f"club_faro_{ini_f:%Y%m}_{corte_b:%Y%m%d}.csv", mime="text/csv")
            st.caption("Semáforo: ✔ en ritmo = va en o por encima del avance esperado (o ya cumplió); ▲ algo atrasado = entre 80 % y "
                       "100 % de lo esperado; ✖ atrasado = por debajo del 80 % de lo esperado.")
            if len(sin_obj):
                ids_so = sin_obj["vendedor_id"].astype(str).drop_duplicates()
                dv = dim_vend.assign(vendedor_id=dim_vend["vendedor_id"].astype(str)).drop_duplicates("vendedor_id").set_index("vendedor_id")
                dni_col = dv["dni"] if "dni" in dv.columns else pd.Series(dtype="object")
                sin_df = pd.DataFrame({"Vendedor": [dv["nombre"].get(v, v) for v in ids_so], "ID": list(ids_so),
                                       "DNI": [(dni_col.get(v) if v in dni_col.index and pd.notna(dni_col.get(v)) else "—") for v in ids_so]}
                                      ).sort_values("Vendedor")
                st.warning("Hay vendedores sin objetivo de Club Faro: no se ven en el gráfico, pero son parte de la cartera de vendedores "
                           "de Pejinakis (vendieron estas líneas en el período).")
                st.dataframe(sin_df, hide_index=True)
                if (sin_df["DNI"] == "—").all():
                    st.caption("DNI sin dato: la tabla de vendedores de la base todavía no lo trae (el ETL completo lo carga si SIGMA lo informa).")

# ----------------------------------------------------------------------------- pestaña 11 Titulares
with tab_11t:
    ini_t, fin_t = ini_bim, fin_bim
    cfg_t, dim_cli_t, faltan_t = cargar_titulares(str(store.root), store.fmt)
    if faltan_t:
        st.info("Faltan tablas: " + ", ".join(faltan_t) + ". Correr scripts/etl/cargar_11_titulares.py (y el ETL completo para dim_cliente).")
    else:
        ventas_t, _ = cargar_cobertura(str(store.root), store.fmt, ini_t, fin_t)
        rt = TB.titulares_resumen(ventas_t, dim_art, dim_cli_t, cfg_t, ini_t, fin_t, corte_b)
        st.subheader("11 Titulares (Peñaflor): clientes con compra del distribuidor")
        st.caption(f"Período {ini_t:%d/%m/%Y} – {fin_t:%d/%m/%Y} · corte {corte_b:%d/%m/%Y} · avance esperado a hoy: "
                   f"{rt['esperado_pct'] * 100:.0f}% (por días de venta). Los objetivos son del distribuidor entero, no por vendedor. "
                   "Un cliente cuenta en una línea si compró, en un mismo artículo de la línea, 1 caja cerrada o bulto (autoservicios y "
                   "OP & VTK) o 3 unidades iguales (tradicionales). Canal según el rubro del cliente en SIGMA.")
        por_def_t = int((cfg_t["fuente"] == "por defecto (S)").sum())
        if por_def_t:
            st.warning(f"{por_def_t} de {len(cfg_t)} artículos de 11 Titulares cuentan por defecto (INCLUIR vacío en el Excel): "
                       "los resultados son provisorios hasta que se marquen S o N.")

        def graf_t(df, leyenda=True):
            d = df.assign(avance_pct=df["avance"].clip(upper=1.5), etiqueta=df["estado_txt"].str[0] + " " + df["logrado"].astype(str)
                          + " / " + df["objetivo"].map("{:.0f}".format),
                          avance_txt=(df["avance"] * 100).map("{:.0f}%".format), faltan_txt=df["faltan"].map("{:.0f}".format),
                          esperado_txt=df["esperado_valor"].map("{:.0f}".format),
                          esperado_pct=rt["esperado_pct"])
            orden = list(d["nombre"])
            y = alt.Y("nombre:N", sort=orden, title=None, axis=alt.Axis(labelOverlap=False, labelLimit=220))
            x = alt.X("avance_pct:Q", scale=alt.Scale(domain=[0, 1.7]),
                      axis=alt.Axis(format="%", values=[0, 0.5, 1.0, 1.5], title="Avance sobre el objetivo"))
            col = alt.Color("estado_txt:N", title="Estado", sort=list(TB.ESTADO_CF_TXT.values()),
                            scale=alt.Scale(domain=list(TB.ESTADO_CF_TXT.values()), range=[TB.ESTADO_COLOR[e] for e in TB.ESTADO_CF_TXT]),
                            legend=alt.Legend(orient="top") if leyenda else None)
            tips = [alt.Tooltip("nombre:N", title="Línea / canal"), alt.Tooltip("etiqueta:N", title="Logrado / objetivo"),
                    alt.Tooltip("avance_txt:N", title="Avance"), alt.Tooltip("esperado_txt:N", title="Esperado a hoy"),
                    alt.Tooltip("faltan_txt:N", title="Faltan"), alt.Tooltip("estado_txt:N", title="Estado")]
            b = alt.Chart(d).mark_bar(size=16, cornerRadiusEnd=4).encode(y=y, x=x, color=col, tooltip=tips)
            t = alt.Chart(d).mark_text(align="left", dx=5, fontSize=11, color=TXT).encode(y=y, x=x, text="etiqueta:N")
            e = alt.Chart(d).mark_tick(color=GRIS_MARCA, thickness=2, size=20).encode(y=y, x=alt.X("esperado_pct:Q"))
            st.altair_chart(alt.layer(b, t, e).properties(height=alt.Step(36)), use_container_width=True)

        ct = rt["canales"]
        kt = st.columns(len(ct))
        for colm, r in zip(kt, ct.itertuples()):
            colm.metric(r.nombre, f"{r.logrado} de {r.objetivo:.0f}", help="Clientes distintos que califican en al menos una línea.")
            colm.caption(f"{r.estado_txt} · faltan {r.faltan:.0f} · esperado a hoy: {r.esperado_valor:.0f}")
        st.markdown("**Por línea**")
        graf_t(rt["lineas"])
        st.markdown("**Por canal**")
        graf_t(rt["canales"])
        st.markdown("**Detalle de OP & VTK**")
        st.caption("Los cuatro subcanales con rubro en la base más Catering (sin rubro). Cada cliente cuenta en un solo subcanal.")
        graf_t(rt["subcanales"], leyenda=False)
        st.caption("La barra es el avance sobre el objetivo; la marca gris es el avance esperado a hoy. Catering no tiene rubro en "
                   "la base (queda en 0). Sin objetivo (0) no hay semáforo.")
        tabla_t = pd.concat([rt["lineas"].assign(Tipo="Línea"), rt["canales"].assign(Tipo="Canal"),
                             rt["subcanales"].assign(Tipo="OP & VTK")], ignore_index=True)
        st.dataframe(tabla_t.rename(columns={"nombre": "Nombre", "estado_txt": "Estado", "logrado": "Logrado", "objetivo": "Objetivo",
                                             "faltan": "Faltan"}).assign(**{"Avance (%)": tabla_t["avance"] * 100})[
            ["Tipo", "Nombre", "Estado", "Logrado", "Objetivo", "Faltan", "Avance (%)"]], hide_index=True,
            column_config={"Avance (%)": st.column_config.NumberColumn(format="%.0f%%"),
                           "Logrado": st.column_config.NumberColumn(format="%.0f"),
                           "Objetivo": st.column_config.NumberColumn(format="%.0f"),
                           "Faltan": st.column_config.NumberColumn(format="%.0f")})
        st.download_button("Descargar 11 Titulares (CSV)", tabla_t.to_csv(index=False).encode("utf-8"),
                           file_name=f"11_titulares_{ini_t:%Y%m}_{corte_b:%Y%m%d}.csv", mime="text/csv")

# ----------------------------------------------------------------------------- pestaña por canal
with tab_canal:
    k1, k2, k3 = st.columns(3)
    pc = resumen["por_canal_empresa"]
    tot = sum(pc.values()) or 1.0
    for col, canal in zip((k1, k2, k3), ("Axum", "Compre Ahora", "Directa")):
        col.metric(f"{canal} (toda la empresa)", TB.fmt_millones(pc[canal]), f"{pc[canal] / tot * 100:.0f}% del total", delta_color="off")
    st.caption("Directa = cargas hechas directamente en SIGMA y todas las notas de crédito. Los objetivos se miden sobre el total.")
    canales = pd.DataFrame({
        "Vendedor": tabla["vendedor"], "Axum (M$)": tabla["Axum"] / 1e6, "Compre Ahora (M$)": tabla["Compre Ahora"] / 1e6,
        "Directa (M$)": tabla["Directa"] / 1e6, "Total (M$)": tabla["vendido"] / 1e6,
    })
    for sup in sup_extra_sel:       # vendedores sin escala de los supervisores elegidos (p. ej. GERENCIA SLA): solo gerentes
        d = TB.ventas_sin_escala(ventas, dim_art, dim_vend, corte, N.SUPERVISOR_SIN_ESCALA[sup])
        canales = pd.concat([canales, pd.DataFrame({
            "Vendedor": d["vendedor"] + " (sin escala)", "Axum (M$)": d["Axum"] / 1e6, "Compre Ahora (M$)": d["Compre Ahora"] / 1e6,
            "Directa (M$)": d["Directa"] / 1e6, "Total (M$)": d["vendido"] / 1e6})], ignore_index=True)
    canales = canales.sort_values("Total (M$)", ascending=False)
    st.dataframe(canales, hide_index=True, column_config={c: st.column_config.NumberColumn(format="%.1f")
                                                         for c in canales.columns if c != "Vendedor"})

# ----------------------------------------------------------------------------- pestaña escalas
with tab_escalas:
    tabla_esc = pd.DataFrame([{"Perfil": p, "Escalón 1 (M$)": e[0] / 1e6, "Escalón 2 (M$)": e[1] / 1e6, "Escalón 3 (M$)": e[2] / 1e6,
                         "Vendedores": ", ".join(v for v, pp in sorted(N.VENDEDOR_PERFIL.items()) if pp == p)}
                        for p, e in N.ESCALAS_FACTURACION.items()])
    st.dataframe(tabla_esc, hide_index=True, column_config={c: st.column_config.NumberColumn(format="%.0f")
                                                     for c in ("Escalón 1 (M$)", "Escalón 2 (M$)", "Escalón 3 (M$)")})
    st.write("Premio por escalón alcanzado: " + esc(" · ".join(
        f"escalón {i}: {TB.fmt_pesos(p)}" for i, p in enumerate(N.PREMIOS_ESCALON, start=1))) + ".")
    st.caption("Escalas de venta neta mensual sin IVA por vendedor, vigentes para septiembre y octubre de 2026. "
               "El objetivo diario es el mensual dividido 26 (se vende de lunes a sábado).")
