"""Pestaña "Objetivos → Feriados": días del mes que no son de venta.

Un feriado resta un día de venta: baja los días del mes y del bimestre y los transcurridos, y con eso cambian el avance
esperado a hoy, la proyección y la media diaria necesaria. Los objetivos, escalones y premios no cambian.
Un solo calendario para toda la empresa. La lógica, las validaciones y el historial están en `sigma_conn.config_feriados`.
"""
from __future__ import annotations

import calendar
from datetime import date

import pandas as pd
import streamlit as st

import auth_ui
from sigma_conn import auth as A
from sigma_conn import config_feriados as CF
from sigma_conn import config_objetivos as CO
from sigma_conn import objetivos as O

_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _meses(store: CF.FeriadosStore, hoy: date) -> list[str]:
    extra = []
    anio, m = hoy.year, hoy.month
    for _ in range(7):                                  # el mes en curso y los 6 siguientes
        extra.append(f"{anio:04d}-{m:02d}")
        anio, m = anio + (m == 12), (m % 12) + 1
    pasados = {x.strftime("%Y-%m") for x in store.todos()}
    return sorted({*extra, *pasados}, reverse=True)


def _etiqueta(d: date) -> str:
    return f"{_DIAS[d.weekday()]} {d:%d/%m}"


def panel_feriados(sesion: dict, hoy: date | None = None) -> None:
    hoy = hoy or date.today()
    store = CF.store_por_defecto()
    actor = sesion.get("usuario", "?")

    st.subheader("Feriados")
    st.caption("Marcá los días del mes que son feriado. Un feriado **resta un día de venta**: cambia el avance esperado a hoy, la proyección "
               "y la media diaria necesaria. Los objetivos, escalones y premios **no** cambian. Los domingos no se marcan (ya no cuentan). "
               "El calendario es uno solo para toda la empresa.")

    meses = _meses(store, hoy)
    mes = st.selectbox("Mes", meses, index=meses.index(CO.mes_de(hoy)), key="fer_mes")
    anio, m = (int(x) for x in mes.split("-"))
    editable = store.es_editable(mes, hoy)
    version = store.version()
    actuales = store.del_mes(mes)

    dias = [date(anio, m, d) for d in range(1, calendar.monthrange(anio, m)[1] + 1) if date(anio, m, d).weekday() != 6]
    if not editable:
        st.info(f"{mes} es un mes cerrado: solo se puede consultar.")
    elif mes == CO.mes_de(hoy):
        st.warning("Estás editando el mes en curso: al guardar, **se recalcula todo el mes y el bimestre** (semáforos, proyecciones y avance esperado).")

    elegidos = st.multiselect("Días feriados (lunes a sábado)", dias, default=actuales, format_func=_etiqueta, disabled=not editable,
                              key=f"fer_sel_{mes}_{version}")
    base = O.dias_de_venta_mes(anio, m)
    con = O.dias_de_venta_mes(anio, m, frozenset(elegidos))
    c1, c2 = st.columns(2)
    c1.metric("Días de venta del mes (sin domingos)", base)
    c2.metric("Días de venta con estos feriados", con, delta=con - base if con != base else None, delta_color="off")

    if editable:
        motivo = st.text_input("Motivo (opcional, queda en el historial: p. ej. el nombre del feriado)", key=f"fer_motivo_{mes}_{version}", max_chars=200)
        if st.button("Guardar feriados", type="primary", key=f"fer_guardar_{mes}_{version}"):
            try:
                store.guardar(actor, mes, elegidos, motivo, version_base=version, hoy=hoy)
                auth_ui._auditoria(A.UsuariosStore(A.ruta_usuarios())).registrar(
                    "objetivos_cambiados", actor, auth_ui._ip_cliente(), extra=f"feriados {mes}")
                st.session_state["_fer_ok"] = f"Feriados guardados para {mes}."
                st.cache_data.clear()
                st.rerun()
            except CO.ConfigError as e:          # incluye ConflictoError
                st.error(str(e))
    if st.session_state.get("_fer_ok"):
        st.success(st.session_state.pop("_fer_ok"))

    st.markdown("**Historial de cambios**")
    todos = st.checkbox("Mostrar todos los meses", value=False, key="fer_hist_todos")
    hist = store.historial(None if todos else mes)
    if not hist:
        st.caption("Todavía no hay cambios registrados.")
        return
    filas = [{"Cuándo (UTC)": r["cuando"].replace("T", " ")[:16], "Quién": r["actor"], "Mes": r["mes"], "Qué": c["campo"],
              "Antes": c["antes"], "Después": c["despues"], "Motivo": r.get("motivo", "")}
             for r in hist for c in r["cambios"]]
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
