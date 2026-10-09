"""Pestaña "Objetivos" (gerentes y supervisores): escalas, premios y perfil de cada vendedor de Facturación.

Reglas: cada cambio vale para un mes completo; el mes en curso se puede editar (recalcula todo el mes) y los meses
cerrados son de solo lectura; un mes sin configuración propia hereda la del último mes anterior; el equipo de cada
vendedor NO se edita acá. Todo cambio queda en el historial (quién, cuándo, qué, antes y después).
La lógica y las validaciones están en `sigma_conn.config_objetivos` (con tests); acá solo hay pantalla.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from sigma_conn import auth as A
from sigma_conn import config_objetivos as CO
from sigma_conn import negocio as N
from sigma_conn import tableros as TB


def _meses_ofrecidos(store: CO.ConfigStore, hoy: date) -> list[str]:
    actual = CO.mes_de(hoy)
    anio, m = hoy.year, hoy.month
    siguiente = f"{anio + (m == 12):04d}-{(m % 12) + 1:02d}"
    return sorted({*store.meses_con_config(), actual, siguiente}, reverse=True)


def _fmt_valor(v) -> str:
    return f"{v:,.0f}".replace(",", ".") if isinstance(v, (int, float)) else str(v)


def panel_objetivos(sesion: dict, nombres_sigma: dict, hoy: date | None = None) -> None:
    hoy = hoy or date.today()
    store = CO.store_por_defecto()
    actor = sesion.get("usuario", "?")

    st.subheader("Objetivos de Facturación")
    st.caption("Escalas de venta neta mensual (sin IVA), premios por escalón y perfil de cada vendedor. Cada cambio vale para un mes "
               "completo. Un mes sin configuración propia usa la del último mes anterior que la tenga.")

    meses = _meses_ofrecidos(store, hoy)
    mes = st.selectbox("Mes", meses, key="obj_mes", index=meses.index(CO.mes_de(hoy)))
    cfg = store.cargar(mes)
    editable = store.es_editable(mes, hoy)

    if not editable:
        st.info(f"{mes} es un mes cerrado: solo se puede consultar.")
    else:
        if mes == CO.mes_de(hoy):
            st.warning("Estás editando el mes en curso: al guardar, **se recalcula todo el mes** (semáforos, escalones y premios de todos "
                       "los vendedores) con los valores nuevos.")
        if cfg.propia:
            st.caption(f"Este mes tiene configuración propia (versión {cfg.version} del archivo).")
        elif cfg.origen == "codigo":
            st.caption("Este mes todavía no tiene configuración propia: rigen los valores iniciales del sistema.")
        else:
            st.caption(f"Este mes todavía no tiene configuración propia: hereda la de {cfg.origen}. Al guardar se crea una propia.")

    # --- escalas y premios
    escalas = pd.DataFrame([{"Perfil": p, "Escalón 1 (M$)": cfg.escalas[p][0] / 1e6, "Escalón 2 (M$)": cfg.escalas[p][1] / 1e6,
                             "Escalón 3 (M$)": cfg.escalas[p][2] / 1e6} for p in CO.PERFILES])
    premios = pd.DataFrame([{"Escalón 1 ($)": cfg.premios[0], "Escalón 2 ($)": cfg.premios[1], "Escalón 3 ($)": cfg.premios[2]}])
    perfiles = pd.DataFrame([{"Código": v, "Vendedor": nombres_sigma.get(v, v), "Perfil": p,
                              "Supervisor": N.SUPERVISORES.get(N.SUPERVISOR_VENDEDOR.get(v, ""), "— sin equipo —")}
                             for v, p in sorted(cfg.vendedor_perfil.items())])
    clave = f"{mes}-{cfg.version}"      # al guardar cambia la versión y los editores se reinician con lo nuevo

    st.markdown("**Escalas por perfil** (millones de pesos, neto sin IVA, por mes)")
    cols_m = {c: st.column_config.NumberColumn(format="%.1f", min_value=0.0, step=0.5) for c in escalas.columns if c != "Perfil"}
    esc_ed = st.data_editor(escalas, hide_index=True, disabled=("Perfil",) if editable else True, column_config=cols_m,
                            key=f"obj_esc_{clave}", use_container_width=True)
    st.markdown("**Premio por escalón alcanzado** (pesos)")
    pre_ed = st.data_editor(premios, hide_index=True, disabled=not editable,
                            column_config={c: st.column_config.NumberColumn(format="%d", min_value=0, step=10000) for c in premios.columns},
                            key=f"obj_pre_{clave}", use_container_width=True)
    st.markdown("**Perfil de cada vendedor** (solo lectura)")
    per_ed = st.data_editor(
        perfiles, hide_index=True, num_rows="fixed", use_container_width=True, key=f"obj_per_{clave}",
        disabled=True,
        column_config={"Perfil": st.column_config.SelectboxColumn(options=list(CO.PERFILES), required=True),
                       })
    st.caption("Los vendedores, su perfil y su equipo (supervisor) no se editan desde el tablero: se administran en SIGMA y los "
               "incorpora el administrador.")
    sin_equipo = [v for v in cfg.vendedor_perfil if v not in N.SUPERVISOR_VENDEDOR]
    if sin_equipo:
        st.warning("Vendedores con escala pero sin equipo asignado (no aparecen en los filtros por supervisor hasta que el administrador "
                   f"los asigne): {', '.join(sin_equipo)}.")

    if editable:
        motivo = st.text_input("Motivo del cambio (opcional, queda en el historial)", key=f"obj_motivo_{clave}", max_chars=200)
        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button("Guardar cambios", type="primary", key=f"obj_guardar_{clave}"):
            try:
                nuevo = {
                    "escalas": {r["Perfil"]: [round(r[f"Escalón {i} (M$)"] * 1e6) for i in (1, 2, 3)] for _, r in esc_ed.iterrows()},
                    "premios": [int(pre_ed.iloc[0][f"Escalón {i} ($)"]) for i in (1, 2, 3)],
                    "vendedor_perfil": dict(cfg.vendedor_perfil),
                }
                guardada = store.guardar(actor, mes, nuevo, motivo, version_base=cfg.version, hoy=hoy)
                auth_ui._auditoria(A.UsuariosStore(A.ruta_usuarios())).registrar("objetivos_cambiados", actor, auth_ui._ip_cliente(), extra=f"facturacion {mes}")
                st.session_state["_obj_ok"] = f"Guardado para {mes}."
                st.cache_data.clear()
                st.rerun()
            except CO.ConflictoError as e:
                st.error(str(e))
            except CO.ConfigError as e:
                st.error(str(e))
        if cfg.propia and c2.button("Volver a heredar", key=f"obj_heredar_{clave}",
                                    help="Borra la configuración propia de este mes y vuelve a usar la del mes anterior."):
            try:
                store.volver_a_heredar(actor, mes, motivo, hoy=hoy)
                st.session_state["_obj_ok"] = f"{mes} vuelve a heredar la configuración anterior."
                st.cache_data.clear()
                st.rerun()
            except CO.ConfigError as e:
                st.error(str(e))
    if st.session_state.get("_obj_ok"):
        st.success(st.session_state.pop("_obj_ok"))

    # --- historial
    st.markdown("**Historial de cambios**")
    todos = st.checkbox("Mostrar todos los meses", value=False, key="obj_hist_todos")
    hist = store.historial(None if todos else mes)
    if not hist:
        st.caption("Todavía no hay cambios registrados.")
    else:
        filas = []
        for r in hist:
            for c in r["cambios"] or [{"campo": "(sin diferencias)", "antes": "", "despues": ""}]:
                filas.append({"Cuándo (UTC)": r["cuando"].replace("T", " ")[:16], "Quién": r["actor"], "Mes": r["mes"],
                              "Qué": c["campo"], "Antes": _fmt_valor(c["antes"]), "Después": _fmt_valor(c["despues"]),
                              "Motivo": r.get("motivo", "") or ("vuelve a heredar" if r.get("tipo") == "herencia" else "")})
        st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
