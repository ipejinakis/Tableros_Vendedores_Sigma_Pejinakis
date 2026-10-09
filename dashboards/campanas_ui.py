"""Pestañas "Mis Ventas" y "Club Faro" de Objetivos: campañas/líneas del bimestre, sus artículos y los objetivos por vendedor.

Cada bimestre se arma de cero (o se copia del anterior): 1) qué campañas/líneas hay, 2) qué artículos tiene cada una,
3) cuánto tiene que lograr cada vendedor. Los vendedores no se editan acá. La lógica y las validaciones están en
`sigma_conn.config_campanas` (con tests); acá solo hay pantalla.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st

import auth_ui
from sigma_conn import auth as A
from sigma_conn import config_bimestre as CB
from sigma_conn import config_campanas as CS
from sigma_conn import config_objetivos as CO

_NOMBRE_MOD = {"mis_ventas": "campaña", "club_faro": "línea", "titulares": "línea"}
_PLURAL = {"mis_ventas": "campañas", "club_faro": "líneas", "titulares": "líneas"}


def _guardar(store, modulo, clave, d, semilla, motivo, version, hoy, texto_ok, copia=False):
    actor = st.session_state.get("usuario", {}).get("usuario", "?")
    try:
        store.guardar(actor, modulo, clave, d, semilla, motivo, version_base=version, hoy=hoy, copia=copia)
        auth_ui._auditoria(A.UsuariosStore(A.ruta_usuarios())).registrar(
            "objetivos_cambiados", actor, auth_ui._ip_cliente(), extra=f"{modulo} {clave}")
        st.session_state["_cp_ok"] = texto_ok
        st.cache_data.clear()
        st.rerun()
    except CO.ConfigError as e:       # incluye ConflictoError
        st.error(str(e))


def _clave_nueva(nombre: str, usadas: set[str]) -> str:
    base = CS.slug(nombre) or "NUEVA"
    k, i = base, 2
    while k in usadas:
        k, i = f"{base}_{i}"[:40], i + 1
    return k


def panel_campanas(modulo: str, base_obj, base_art, sesion: dict, nombres_vend: dict, dim_art: pd.DataFrame,
                   hoy: date | None = None) -> None:
    hoy = hoy or date.today()
    store = CS.store_por_defecto()
    semilla = CS.SEMILLAS[modulo](base_obj, base_art)
    palabra, plural = _NOMBRE_MOD[modulo], _PLURAL[modulo]

    bimestres = sorted({*store.bimestres_con_config(modulo), CB.bimestre_clave(hoy), CB.siguiente_bimestre(CB.bimestre_clave(hoy))},
                       reverse=True)
    clave = st.selectbox("Bimestre", bimestres, index=bimestres.index(CB.bimestre_clave(hoy)), key=f"cp_bim_{modulo}",
                         format_func=CB.bimestre_texto)
    editable = store.es_editable(clave, hoy)
    d, origen, version = store.vigente(modulo, clave, semilla)
    cat = d["catalogo"]

    if not editable:
        st.info(f"{CB.bimestre_texto(clave)} es un bimestre cerrado: solo se puede consultar.")
    else:
        if clave == CB.bimestre_clave(hoy):
            st.warning(f"Estás editando el bimestre en curso: al guardar, **se recalcula todo el bimestre** con las {plural} nuevas.")
        if origen == "propia":
            st.caption(f"Este bimestre tiene definición propia (versión {version} del archivo).")
        elif origen == "excel":
            st.caption("Este bimestre todavía no se editó en el tablero: rigen las "
                       f"{plural} cargadas desde el Excel. Al guardar cualquier cambio se crea la definición propia.")
        else:
            st.caption(f"Este bimestre todavía no tiene {plural} cargadas.")
    if st.session_state.get("_cp_ok"):
        st.success(st.session_state.pop("_cp_ok"))

    # --- copiar del bimestre anterior (un bimestre nuevo arranca vacío)
    if editable and origen == "vacia":
        previo = CS.bimestre_anterior(clave)
        d_prev, o_prev, _ = store.vigente(modulo, previo, semilla)
        if d_prev["catalogo"]:
            if st.button(f"Copiar {plural}, artículos y objetivos de {CB.bimestre_texto(previo)}", key=f"cp_copiar_{modulo}_{clave}",
                         help="Crea la definición de este bimestre como copia de la anterior; después la editás."):
                _guardar(store, modulo, clave, d_prev, semilla, f"copia de {CB.bimestre_texto(previo)}", version, hoy,
                         f"Copiado de {CB.bimestre_texto(previo)}.", copia=True)

    ck = f"{modulo}-{clave}-{version}"        # al guardar cambia la versión y los editores se reinician con lo nuevo

    # ------------------------------------------------------------------ 1) catálogo
    st.markdown(f"#### 1. {plural.capitalize()} del bimestre")
    if modulo == "mis_ventas":
        filas = [{"Clave": k, "Nombre": i["nombre"], "Cobertura": "COBERTURA" in i["tipos"], "Volumen": "VOLUMEN" in i["tipos"]}
                 for k, i in cat.items()]
        cols = ["Clave", "Nombre", "Cobertura", "Volumen"]
        cfg_cols = {"Nombre": st.column_config.TextColumn(required=True),
                    "Cobertura": st.column_config.CheckboxColumn(help="Mide clientes distintos con compra de la campaña."),
                    "Volumen": st.column_config.CheckboxColumn(help="Mide unidades netas de la campaña (las notas de crédito restan).")}
    elif modulo == "titulares":
        filas = [{"Clave": k, "Nombre": i["nombre"], "Objetivo": i["objetivo"], "Propia": bool(i.get("propia"))} for k, i in cat.items()]
        cols = ["Clave", "Nombre", "Objetivo", "Propia"]
        cfg_cols = {"Nombre": st.column_config.TextColumn(required=True),
                    "Objetivo": st.column_config.NumberColumn(format="%d", min_value=0, step=1,
                                                              help="Clientes con compra que tiene que lograr el distribuidor entero en la línea."),
                    "Propia": st.column_config.CheckboxColumn(help="Parámetro propio de Pejinakis (no lo pide Peñaflor): no suma a los canales.")}
    else:
        filas = [{"Clave": k, "Nombre": i["nombre"], "Tipo de cliente": i["tipo_cliente"], "Modo": i["modo"]} for k, i in cat.items()]
        cols = ["Clave", "Nombre", "Tipo de cliente", "Modo"]
        cfg_cols = {"Nombre": st.column_config.TextColumn(required=True),
                    "Tipo de cliente": st.column_config.SelectboxColumn(options=list(CS.TIPOS_CLIENTE), required=True,
                                                                         help="AS = autoservicios; TRAD = kioscos, almacenes, etc."),
                    "Modo": st.column_config.SelectboxColumn(options=list(CS.MODOS_CF), required=True,
                                                             help="clientes = clientes distintos con compra; cliente_sku = cada par cliente × SKU suma 1.")}
    df_cat = pd.DataFrame(filas, columns=cols)
    if modulo == "mis_ventas":
        df_cat[["Cobertura", "Volumen"]] = df_cat[["Cobertura", "Volumen"]].astype(bool)
    ed_cat = st.data_editor(df_cat, hide_index=True, use_container_width=True, key=f"cp_cat_{ck}",
                            num_rows="dynamic" if editable else "fixed", disabled=True if not editable else False,
                            column_order=[c for c in cols if c != "Clave"], column_config=cfg_cols)
    if editable:
        st.caption(f"Agregá una fila por cada {palabra} nueva. Si borrás una fila, se quitan también sus artículos y objetivos.")
        motivo1 = st.text_input("Motivo del cambio (opcional, queda en el historial)", key=f"cp_mot1_{ck}", max_chars=200)
        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button(f"Guardar {plural}", type="primary", key=f"cp_g1_{ck}"):
            nuevo_cat, usadas = {}, {str(k) for k in ed_cat["Clave"].dropna() if str(k).strip()}
            for _, r in ed_cat.iterrows():
                nombre = str(r["Nombre"] or "").strip()
                if not nombre:
                    continue
                k = str(r["Clave"]).strip() if pd.notna(r["Clave"]) and str(r["Clave"]).strip() else _clave_nueva(nombre, usadas)
                usadas.add(k)
                if modulo == "mis_ventas":
                    tipos = [t for t, on in (("COBERTURA", r["Cobertura"]), ("VOLUMEN", r["Volumen"])) if bool(on)]
                    nuevo_cat[k] = {"nombre": nombre, "tipos": tipos}
                elif modulo == "titulares":
                    nuevo_cat[k] = {"nombre": nombre, "objetivo": r["Objetivo"] if pd.notna(r["Objetivo"]) else 0, "propia": bool(r["Propia"])}
                else:
                    nuevo_cat[k] = {"nombre": nombre, "tipo_cliente": r["Tipo de cliente"], "modo": r["Modo"]}
            nuevo = {**d, "catalogo": nuevo_cat,
                     "articulos": {k: v for k, v in d["articulos"].items() if k in nuevo_cat},
                     "objetivos": [o for o in d["objetivos"] if o["clave"] in nuevo_cat and
                                   (modulo != "mis_ventas" or o["tipo"] in nuevo_cat[o["clave"]]["tipos"])]}
            _guardar(store, modulo, clave, nuevo, semilla, motivo1, version, hoy, f"{plural.capitalize()} guardadas para {CB.bimestre_texto(clave)}.")
        if origen == "propia" and c2.button("Descartar lo editado", key=f"cp_desc_{ck}",
                                            help="Borra la definición propia de este bimestre (vuelve a lo del Excel, o a vacío)."):
            try:
                store.descartar(st.session_state.get("usuario", {}).get("usuario", "?"), modulo, clave, motivo1, hoy)
                st.session_state["_cp_ok"] = "Definición descartada."
                st.cache_data.clear()
                st.rerun()
            except CO.ConfigError as e:
                st.error(str(e))

    if not cat:
        _historial(store, modulo, clave)
        return

    # ------------------------------------------------------------------ 2) artículos
    st.markdown(f"#### 2. Artículos de cada {palabra}")
    elegida = st.selectbox(f"{palabra.capitalize()}", list(cat), format_func=lambda k: cat[k]["nombre"], key=f"cp_sel_{ck}")
    actuales = d["articulos"].get(elegida, [])
    dim = dim_art.drop_duplicates("articulo_id").assign(articulo_id=lambda x: x["articulo_id"].astype(str)) if dim_art is not None else pd.DataFrame()
    def _txt(v) -> str:
        return "" if v is None or pd.isna(v) else str(v).strip()
    desc = {r.articulo_id: f"{r.articulo_id} · {_txt(r.descripcion)}" + (f" ({_txt(r.presentacion)})" if _txt(getattr(r, "presentacion", None)) else "")
            for r in dim.itertuples()} if len(dim) else {}
    opciones = sorted({*desc, *actuales}, key=lambda a: (not a.isdigit(), int(a) if a.isdigit() else 0, a))
    sel = st.multiselect(f"Artículos de «{cat[elegida]['nombre']}» ({len(actuales)} hoy)", opciones, default=actuales, key=f"cp_art_{ck}_{elegida}",
                         format_func=lambda a: desc.get(a, f"{a} · (no está en la base de SIGMA)"), disabled=not editable)
    pegados = ""
    if editable:
        pegados = st.text_area("O pegá códigos de artículo (separados por coma, espacio o renglón) para sumarlos",
                               key=f"cp_peg_{ck}_{elegida}", height=70)
    quedan = [a for a in sel]
    desconocidos = []
    if pegados.strip():
        for a in re.split(r"[\s,;]+", pegados.strip()):
            if not a:
                continue
            if a not in quedan:
                quedan.append(a)
            if desc and a not in desc:
                desconocidos.append(a)
    if desconocidos:
        st.warning("Estos códigos no están en la base de artículos de SIGMA (revisalos): " + ", ".join(desconocidos))
    if editable:
        motivo2 = st.text_input("Motivo del cambio (opcional)", key=f"cp_mot2_{ck}_{elegida}", max_chars=200)
        if st.button("Guardar artículos", type="primary", key=f"cp_g2_{ck}_{elegida}"):
            nuevo = {**d, "catalogo": cat, "articulos": {**d["articulos"], elegida: quedan}}
            _guardar(store, modulo, clave, nuevo, semilla, motivo2, version, hoy, f"Artículos de «{cat[elegida]['nombre']}» guardados.")

    # ------------------------------------------------------------------ 3) objetivos
    if modulo == "titulares":
        _objetivos_canales(store, modulo, clave, d, semilla, editable, ck, version, hoy)
        _historial(store, modulo, clave)
        return
    st.markdown("#### 3. Objetivo por vendedor")
    if modulo == "mis_ventas":
        paneles = [(k, t, f"{i['nombre']} · {t.lower()}") for k, i in cat.items() for t in i["tipos"]]
    else:
        paneles = [(k, "", i["nombre"]) for k, i in cat.items()]
    vend = sorted({*CO.vendedores_con_escala(clave), *{o["vendedor_id"] for o in d["objetivos"]}})
    valores = {(o["clave"], o["tipo"], o["vendedor_id"]): o["valor"] for o in d["objetivos"]}
    mat = pd.DataFrame([{"Código": v, "Vendedor": nombres_vend.get(v, v),
                         **{etq: valores.get((k, t, v)) for k, t, etq in paneles}} for v in vend])
    cols_v = [etq for _, _, etq in paneles]
    ed = st.data_editor(mat, hide_index=True, use_container_width=True, num_rows="fixed", key=f"cp_obj_{ck}",
                        disabled=True if not editable else ("Código", "Vendedor"),
                        column_config={c: st.column_config.NumberColumn(format="%.0f", min_value=0, step=1) for c in cols_v})
    st.caption("Celda vacía = el vendedor no tiene objetivo en esa " + palabra + ". Cobertura y Club Faro se miden en clientes; "
               "volumen, en unidades.")
    if editable:
        motivo3 = st.text_input("Motivo del cambio (opcional)", key=f"cp_mot3_{ck}", max_chars=200)
        if st.button("Guardar objetivos", type="primary", key=f"cp_g3_{ck}"):
            nuevos = []
            for _, r in ed.iterrows():
                for k, t, etq in paneles:
                    if pd.notna(r[etq]):
                        nuevos.append({"clave": k, "tipo": t, "vendedor_id": str(r["Código"]), "valor": float(r[etq])})
            nuevo = {**d, "catalogo": cat, "articulos": d["articulos"], "objetivos": nuevos}
            _guardar(store, modulo, clave, nuevo, semilla, motivo3, version, hoy, "Objetivos guardados.")

    _historial(store, modulo, clave)


def _objetivos_canales(store, modulo, clave, d, semilla, editable, ck, version, hoy) -> None:
    """Paso 3 de 11 Titulares: el objetivo es del distribuidor, por canal y por subcanal de OP & VTK (no por vendedor)."""
    from sigma_conn import negocio as N
    st.markdown("#### 3. Objetivos por canal y subcanal")
    st.caption("Clientes con compra del distribuidor entero. Los canales salen del rubro del cliente en SIGMA; las líneas propias no suman acá.")
    can = pd.DataFrame([{c: d.get("canales", {}).get(c, 0) for c in N.TITULARES_CANALES}])
    sub = pd.DataFrame([{c: d.get("subcanales", {}).get(c, 0) for c in N.TITULARES_OBJ_SUBCANAL}])
    cfg = lambda df: {c: st.column_config.NumberColumn(format="%d", min_value=0, step=1) for c in df.columns}
    st.markdown("**Canales**")
    ed_c = st.data_editor(can, hide_index=True, use_container_width=True, disabled=not editable, key=f"cp_can_{ck}", column_config=cfg(can))
    st.markdown("**Subcanales de OP & VTK**")
    ed_s = st.data_editor(sub, hide_index=True, use_container_width=True, disabled=not editable, key=f"cp_sub_{ck}", column_config=cfg(sub))
    if editable:
        motivo = st.text_input("Motivo del cambio (opcional)", key=f"cp_mot3_{ck}", max_chars=200)
        if st.button("Guardar objetivos", type="primary", key=f"cp_g3_{ck}"):
            nuevo = {**d, "canales": {k: float(v) for k, v in ed_c.iloc[0].items() if pd.notna(v)},
                     "subcanales": {k: float(v) for k, v in ed_s.iloc[0].items() if pd.notna(v)}}
            _guardar(store, modulo, clave, nuevo, semilla, motivo, version, hoy, "Objetivos guardados.")


def _historial(store: CS.CampanasStore, modulo: str, clave: str) -> None:
    st.markdown("**Historial de cambios**")
    todos = st.checkbox("Mostrar todos los bimestres", value=False, key=f"cp_hist_{modulo}")
    hist = store.historial(modulo, None if todos else clave)
    if not hist:
        st.caption("Todavía no hay cambios registrados.")
        return
    filas = []
    for r in hist:
        for c in r["cambios"] or [{"campo": "(sin diferencias)", "antes": "", "despues": ""}]:
            filas.append({"Cuándo (UTC)": r["cuando"].replace("T", " ")[:16], "Quién": r["actor"],
                          "Bimestre": CB.bimestre_texto(r["bimestre"]), "Qué": c["campo"],
                          "Antes": _fmt(c["antes"]), "Después": _fmt(c["despues"]),
                          "Motivo": r.get("motivo", "") or {"copia": "copia del bimestre anterior", "descarte": "se descartó lo editado"}.get(r.get("tipo"), "")})
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)


def _fmt(v) -> str:
    return f"{v:,.0f}".replace(",", ".") if isinstance(v, (int, float)) else str(v)


def panel_cobertura_articulos(dim_art: pd.DataFrame, sesion: dict, hoy: date | None = None) -> None:
    """Qué artículos cuentan en BPC, FOOD y HC en cada bimestre. La regla automática (división de SIGMA y combos) sigue
    valiendo; acá se guardan solo las EXCEPCIONES: artículos que se pasan a otra categoría o se sacan de todas."""
    hoy = hoy or date.today()
    store = CS.store_por_defecto()
    st.markdown("#### Artículos de cada categoría")
    bimestres = sorted({*store.bimestres_con_config("cobertura"), CB.bimestre_clave(hoy), CB.siguiente_bimestre(CB.bimestre_clave(hoy))},
                       reverse=True)
    clave = st.selectbox("Bimestre", bimestres, index=bimestres.index(CB.bimestre_clave(hoy)), key="cb_art_bim", format_func=CB.bimestre_texto)
    editable = store.es_editable(clave, hoy)
    d, origen, version = store.vigente("cobertura", clave, None)
    exc = dict(d.get("excepciones") or {})
    if not editable:
        st.info(f"{CB.bimestre_texto(clave)} es un bimestre cerrado: solo se puede consultar.")
    elif clave == CB.bimestre_clave(hoy):
        st.warning("Estás editando el bimestre en curso: al guardar, **se recalcula la cobertura de todo el bimestre**.")
    if dim_art is None or dim_art.empty or "categoria_cobertura" not in dim_art.columns:
        st.info("Faltan los artículos o su categoría: correr el ETL completo.")
        return
    dim = dim_art.drop_duplicates("articulo_id").assign(articulo_id=lambda x: x["articulo_id"].astype(str)).set_index("articulo_id")
    base = dim["categoria_cobertura"].astype("object")
    efectiva = CS.categoria_efectiva(base, exc)

    def _txt(v) -> str:
        return "" if v is None or pd.isna(v) else str(v).strip()
    etiqueta = {a: f"{a} · {_txt(r.descripcion)}" for a, r in dim.iterrows()}
    ck = f"{clave}-{version}"
    cat = st.selectbox("Categoría", list(CS.CATEGORIAS_COB), key=f"cb_art_cat_{ck}")
    actuales = sorted([a for a, c in efectiva.items() if isinstance(c, str) and c == cat], key=lambda a: (not a.isdigit(), int(a) if a.isdigit() else 0, a))
    opciones = sorted(etiqueta, key=lambda a: (not a.isdigit(), int(a) if a.isdigit() else 0, a))
    sel = st.multiselect(f"Artículos de {cat} ({len(actuales)} hoy)", opciones, default=actuales, key=f"cb_art_sel_{ck}_{cat}",
                         format_func=lambda a: etiqueta.get(a, a), disabled=not editable,
                         help="Para pasar un artículo a esta categoría, agregalo; si venía de otra, deja de contar en la anterior. "
                              "Para sacarlo de la categoría, quitalo (queda sin categoría).")
    pegados = st.text_area("O pegá códigos de artículo para sumarlos a esta categoría", key=f"cb_art_peg_{ck}_{cat}", height=70) if editable else ""
    quedan = list(sel)
    for a in re.split(r"[\s,;]+", pegados.strip()) if pegados.strip() else []:
        if a and a not in quedan:
            quedan.append(a)
    desconocidos = [a for a in quedan if a not in etiqueta]
    if desconocidos:
        st.warning("Estos códigos no están en la base de artículos de SIGMA (revisalos): " + ", ".join(desconocidos))
    movidos = [a for a in quedan if a in efectiva.index and isinstance(efectiva.get(a), str) and efectiva.get(a) != cat]
    if movidos:
        st.caption("Pasan a " + cat + " desde otra categoría: " + ", ".join(f"{a} ({efectiva.get(a)})" for a in movidos[:15])
                   + ("…" if len(movidos) > 15 else ""))
    if editable:
        motivo = st.text_input("Motivo del cambio (opcional)", key=f"cb_art_mot_{ck}", max_chars=200)
        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button(f"Guardar artículos de {cat}", type="primary", key=f"cb_art_g_{ck}_{cat}"):
            nuevo_exc = dict(exc)
            deseada = {a: cat for a in quedan}
            for a in actuales:
                if a not in quedan:
                    deseada[a] = CS.SIN_CATEGORIA
            for a, c in deseada.items():
                natural = base.get(a) if a in base.index else None
                natural = None if natural is None or pd.isna(natural) else str(natural)
                if (c == CS.SIN_CATEGORIA and natural not in CS.CATEGORIAS_COB) or c == natural:
                    nuevo_exc.pop(a, None)        # coincide con la regla automática: no hace falta excepción
                else:
                    nuevo_exc[a] = c
            _guardar(store, "cobertura", clave, {"excepciones": nuevo_exc}, None, motivo, version, hoy,
                     f"Artículos de {cat} guardados.")
        if origen == "propia" and c2.button("Descartar excepciones", key=f"cb_art_desc_{ck}",
                                            help="Vuelve a la regla automática en este bimestre."):
            try:
                store.descartar(st.session_state.get("usuario", {}).get("usuario", "?"), "cobertura", clave, "", hoy)
                st.session_state["_cp_ok"] = "Excepciones descartadas."
                st.cache_data.clear()
                st.rerun()
            except CO.ConfigError as e:
                st.error(str(e))
        previo = CS.bimestre_anterior(clave)
        d_prev, _, _ = store.vigente("cobertura", previo, None)
        if origen != "propia" and d_prev.get("excepciones") and st.button(
                f"Copiar excepciones de {CB.bimestre_texto(previo)}", key=f"cb_art_copia_{ck}"):
            _guardar(store, "cobertura", clave, d_prev, None, f"copia de {CB.bimestre_texto(previo)}", version, hoy,
                     f"Copiado de {CB.bimestre_texto(previo)}.", copia=True)
    if st.session_state.get("_cp_ok"):
        st.success(st.session_state.pop("_cp_ok"))
    if exc:
        st.markdown("**Excepciones de este bimestre**")
        st.dataframe(pd.DataFrame([{"Artículo": a, "Descripción": etiqueta.get(a, "").split(" · ", 1)[-1], "Regla automática": _txt(base.get(a)) or "—",
                                    "Categoría en este bimestre": c} for a, c in sorted(exc.items())]), hide_index=True, use_container_width=True)
    _historial(store, "cobertura", clave)
