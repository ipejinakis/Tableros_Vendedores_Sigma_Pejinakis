"""Pestañas de objetivos bimestrales (cobertura, Mis Ventas y Club Faro) dentro de "Objetivos".

Se edita el valor de cada objetivo existente. Los vendedores, las campañas y las líneas no se tocan desde acá.
La lógica, las validaciones y el historial están en `sigma_conn.config_bimestre` (con tests); acá solo hay pantalla.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import auth_ui
from sigma_conn import auth as A
from sigma_conn import config_bimestre as CB
from sigma_conn import config_objetivos as CO
from sigma_conn import negocio as N

# módulo -> (columna que va en las columnas de la matriz, columna de valor, título de la matriz)
_MATRIZ = {
    "cobertura": ("categoria", "objetivo", "Clientes con compra por vendedor y categoría"),
    "mis_ventas": ("panel", "target", "Target por vendedor y campaña (cobertura = clientes; volumen = unidades)"),
    "club_faro": ("linea", "objetivo", "Clientes (o pares cliente-SKU) por vendedor y línea"),
}


def _con_panel(modulo: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if modulo == "mis_ventas":
        df["panel"] = df["campana"].map(lambda c: N.CAMPANA_NOMBRE.get(c, c)) + " · " + df["tipo"].str.lower()
    elif modulo == "club_faro":
        df["linea"] = df["linea"].astype(str)
    return df


def _etiqueta_col(modulo: str, col: str) -> str:
    if modulo == "club_faro":
        return N.CLUB_FARO_LINEAS.get(col, {}).get("nombre", col)
    return col


def _bimestres(store: CB.ObjetivosBimestreStore, hoy: date) -> list[str]:
    actual = CB.bimestre_clave(hoy)
    return sorted({*store.bimestres_con_config(), actual, CB.siguiente_bimestre(actual)}, reverse=True)


def panel_modulo(modulo: str, base: pd.DataFrame | None, sesion: dict, nombres: dict, hoy: date | None = None) -> None:
    hoy = hoy or date.today()
    store = CB.store_por_defecto()
    actor = sesion.get("usuario", "?")
    col_x, col_val, titulo = _MATRIZ[modulo]
    claves, _valores = CB.MODULOS[modulo]

    bimestres = _bimestres(store, hoy)
    clave = st.selectbox("Bimestre", bimestres, index=bimestres.index(CB.bimestre_clave(hoy)), key=f"ob_bim_{modulo}",
                         format_func=CB.bimestre_texto)
    editable = store.es_editable(clave, hoy)
    df, origen, version = store.vigente(modulo, clave, base)
    if df is None or df.empty:
        st.info("Todavía no hay objetivos cargados para este módulo (correr scripts/etl/cargar_objetivos.py o cargar_club_faro.py).")
        return
    df = _con_panel(modulo, df)
    if modulo == "club_faro":
        df = df[df["vendedor_id"].astype(str) != ""]       # los nombres sin cruce con la base no se editan
        if df.empty:
            st.info("No hay vendedores con objetivo.")
            return

    if not editable:
        st.info(f"{CB.bimestre_texto(clave)} es un bimestre cerrado: solo se puede consultar.")
    else:
        if clave == CB.bimestre_clave(hoy):
            st.warning("Estás editando el bimestre en curso: al guardar, **se recalcula todo el bimestre** con los valores nuevos.")
        if origen == clave:
            st.caption(f"Este bimestre tiene tabla propia (versión {version} del archivo).")
        elif origen == "excel":
            st.caption("Este bimestre todavía no tiene tabla propia: rigen los objetivos cargados desde el Excel.")
        else:
            st.caption(f"Este bimestre todavía no tiene tabla propia: hereda la de {CB.bimestre_texto(origen)}. Al guardar se crea una propia.")

    # --- matriz vendedor × columna
    mat = df.pivot_table(index="vendedor_id", columns=col_x, values=col_val, aggfunc="first")
    orden = [c for c in (N.CATEGORIAS_COBERTURA if modulo == "cobertura" else
                         list(N.CLUB_FARO_LINEAS) if modulo == "club_faro" else sorted(mat.columns)) if c in mat.columns]
    mat = mat[orden]
    tabla = mat.reset_index()
    tabla.insert(1, "Vendedor", tabla["vendedor_id"].map(lambda v: nombres.get(str(v), str(v))))
    tabla = tabla.rename(columns={"vendedor_id": "Código", **{c: _etiqueta_col(modulo, c) for c in orden}})
    cols_val = [_etiqueta_col(modulo, c) for c in orden]
    clave_ui = f"{modulo}-{clave}-{version}"
    st.markdown(f"**{titulo}**")
    ed = st.data_editor(
        tabla, hide_index=True, use_container_width=True, num_rows="fixed", key=f"ob_mat_{clave_ui}",
        disabled=True if not editable else ("Código", "Vendedor"),
        column_config={c: st.column_config.NumberColumn(format="%.0f", min_value=0, step=1) for c in cols_val})
    if tabla[cols_val].isna().any().any():
        st.caption("Las celdas vacías son combinaciones sin objetivo: no se pueden completar desde acá.")

    tot_ed = None
    if modulo == "cobertura":
        tot = df.drop_duplicates("categoria").set_index("categoria")["total_distribuidora"].reindex(list(N.CATEGORIAS_COBERTURA))
        st.markdown("**Total de la distribuidora por categoría** (clientes con compra, toda la empresa)")
        tot_ed = st.data_editor(pd.DataFrame([tot.to_dict()]), hide_index=True, disabled=not editable, use_container_width=True,
                                key=f"ob_tot_{clave_ui}",
                                column_config={c: st.column_config.NumberColumn(format="%.0f", min_value=0, step=1) for c in tot.index})

    if editable:
        motivo = st.text_input("Motivo del cambio (opcional, queda en el historial)", key=f"ob_motivo_{clave_ui}", max_chars=200)
        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button("Guardar cambios", type="primary", key=f"ob_guardar_{clave_ui}"):
            try:
                largo = ed.rename(columns={"Código": "vendedor_id"}).drop(columns=["Vendedor"]).melt(
                    id_vars="vendedor_id", var_name="_col", value_name=col_val).dropna(subset=[col_val])
                inv = {_etiqueta_col(modulo, c): c for c in orden}
                largo[col_x] = largo["_col"].map(inv)
                base_x = df[["vendedor_id", col_x]].astype(str).apply(tuple, axis=1)
                existentes = set(base_x)
                if any((str(v), str(x)) not in existentes for v, x in zip(largo["vendedor_id"], largo[col_x])):
                    raise CO.ConfigError("Hay valores en celdas que no tienen objetivo: esas combinaciones no se pueden agregar.")
                nuevos = df.drop(columns=[col_val] + (["total_distribuidora"] if modulo == "cobertura" else []))
                nuevos = nuevos.merge(largo[["vendedor_id", col_x, col_val]], on=["vendedor_id", col_x], how="inner")
                if modulo == "cobertura":
                    nuevos["total_distribuidora"] = nuevos["categoria"].map(tot_ed.iloc[0].to_dict())
                store.guardar(actor, modulo, clave, nuevos, base, motivo, version_base=version, hoy=hoy)
                auth_ui._auditoria(A.UsuariosStore(A.ruta_usuarios())).registrar(
                    "objetivos_cambiados", actor, auth_ui._ip_cliente(), extra=f"{modulo} {clave}")
                st.session_state["_ob_ok"] = f"Guardado para el bimestre {CB.bimestre_texto(clave)}."
                st.cache_data.clear()
                st.rerun()
            except CO.ConfigError as e:      # incluye ConflictoError
                st.error(str(e))
        if origen == clave and c2.button("Volver a heredar", key=f"ob_heredar_{clave_ui}",
                                         help="Borra la tabla propia de este bimestre y vuelve a usar la anterior."):
            try:
                store.volver_a_heredar(actor, modulo, clave, motivo, hoy=hoy)
                st.session_state["_ob_ok"] = "Vuelve a heredar la tabla anterior."
                st.cache_data.clear()
                st.rerun()
            except CO.ConfigError as e:
                st.error(str(e))
    if st.session_state.get("_ob_ok"):
        st.success(st.session_state.pop("_ob_ok"))

    # --- historial
    st.markdown("**Historial de cambios**")
    todos = st.checkbox("Mostrar todos los bimestres", value=False, key=f"ob_hist_todos_{modulo}")
    hist = store.historial(modulo, None if todos else clave)
    if not hist:
        st.caption("Todavía no hay cambios registrados.")
        return
    filas = []
    for r in hist:
        for c in r["cambios"] or [{"campo": "(vuelve a heredar)", "antes": "", "despues": ""}]:
            filas.append({"Cuándo (UTC)": r["cuando"].replace("T", " ")[:16], "Quién": r["actor"],
                          "Bimestre": CB.bimestre_texto(r["bimestre"]), "Qué": c["campo"],
                          "Antes": CO_fmt(c["antes"]), "Después": CO_fmt(c["despues"]), "Motivo": r.get("motivo", "")})
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)


def CO_fmt(v) -> str:
    return f"{v:,.0f}".replace(",", ".") if isinstance(v, (int, float)) else str(v)
