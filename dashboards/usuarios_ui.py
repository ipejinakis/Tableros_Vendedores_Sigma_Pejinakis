"""Pestaña "Usuarios": gerentes y supervisores gestionan las cuentas de los vendedores (Streamlit).

Qué se puede hacer: cambiar la clave de un vendedor (clave temporal nueva que debe cambiar al entrar), dar de baja su
acceso (baja lógica: la cuenta queda guardada pero no entra más) y dar de alta o reactivar (el código lo toma otra
persona: nombre nuevo y clave temporal). El gerente gestiona a todos; el supervisor, solo a su equipo.
Las reglas de permiso están en `sigma_conn.auth` (con tests); acá solo hay interfaz. La clave temporal se muestra una
sola vez en pantalla y nunca se guarda en claro. Cada acción queda en el registro de auditoría."""
import pandas as pd
import streamlit as st

import auth_ui
from sigma_conn import auth as A

_ESTADO = {"activa": "Activa", "baja": "De baja", "sin": "Sin cuenta"}


def _estado(f: dict) -> str:
    if not f["existe"]:
        return _ESTADO["sin"]
    return _ESTADO["activa"] if f["activo"] else _ESTADO["baja"]


def _accion(sesion: dict, store: A.UsuariosStore, evento: str, vid: str) -> None:
    auth_ui._auditoria(store).registrar(evento, sesion["usuario"], auth_ui._ip_cliente(), extra=f"vendedor {vid}")


def panel_usuarios(sesion: dict, nombres_sigma: dict[str, str]) -> None:
    store = A.UsuariosStore(A.ruta_usuarios())
    filas = store.estado_vendedores(sesion)
    st.subheader("Cuentas de vendedores")
    if not filas:
        st.info("Tu usuario no tiene vendedores asignados para gestionar. Si tendría que tenerlos, avisale al administrador.")
        return
    alcance = "todos los vendedores" if sesion["rol"] == A.ROL_GERENTE else "los vendedores de tu equipo"
    st.caption(f"Podés gestionar {alcance} ({len(filas)}). Las claves nuevas se muestran una sola vez: pasáselas al vendedor "
               "por un canal privado; las tiene que cambiar en su primer ingreso.")

    # Clave recién generada (una sola vez, hasta que se oculte)
    nueva = st.session_state.get("_clave_nueva")
    if nueva:
        st.success(f"{nueva['titulo']} — vendedor {nueva['vid']} ({nueva['nombre']}). Clave temporal (no se vuelve a mostrar):")
        st.code(nueva["clave"], language=None)
        if st.button("Ya la copié, ocultar", key="ocultar_clave"):
            st.session_state.pop("_clave_nueva", None)
            st.rerun()

    tabla = pd.DataFrame([{"Código": f["vendedor_id"], "Nombre": f["nombre"] or nombres_sigma.get(f["vendedor_id"], ""),
                           "Estado": _estado(f), "Clave pendiente de cambio": "Sí" if f["debe_cambiar"] else "—"}
                          for f in filas])
    st.dataframe(tabla, hide_index=True, use_container_width=True)

    por_codigo = {f["vendedor_id"]: f for f in filas}
    elegido = st.selectbox("Vendedor", list(por_codigo), key="usuarios_sel",
                           format_func=lambda v: f"{v} — {por_codigo[v]['nombre'] or nombres_sigma.get(v, '(sin nombre)')} · {_estado(por_codigo[v])}")
    f = por_codigo[elegido]
    estado = _estado(f)

    try:
        if estado == _ESTADO["activa"]:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Cambiar la clave**")
                st.caption("Genera una clave temporal nueva y cierra sus sesiones abiertas.")
                if st.button("Resetear clave", key=f"reset_{elegido}"):
                    clave = store.resetear_vendedor(sesion, elegido)
                    auth_ui._sesiones(store).revocar_usuario(elegido)
                    _accion(sesion, store, "cuenta_clave_reseteada", elegido)
                    st.session_state["_clave_nueva"] = {"titulo": "Clave reseteada", "vid": elegido, "nombre": f["nombre"], "clave": clave}
                    st.rerun()
            with c2:
                st.markdown("**Dar de baja**")
                st.caption("Deja de poder entrar al tablero. Se puede reactivar después con el alta.")
                confirma = st.checkbox("Confirmo la baja de esta cuenta", key=f"conf_baja_{elegido}")
                if st.button("Dar de baja", key=f"baja_{elegido}", disabled=not confirma):
                    store.baja_vendedor(sesion, elegido)
                    auth_ui._sesiones(store).revocar_usuario(elegido)
                    _accion(sesion, store, "cuenta_baja", elegido)
                    st.session_state.pop("_clave_nueva", None)
                    st.toast(f"Cuenta {elegido} dada de baja.")
                    st.rerun()
        else:
            accion = "Reactivar la cuenta" if estado == _ESTADO["baja"] else "Dar de alta"
            st.markdown(f"**{accion}**")
            st.caption("Para un vendedor nuevo que toma este código: escribí su nombre; se genera una clave temporal que debe cambiar al entrar."
                       if estado == _ESTADO["baja"] else
                       "Crea la cuenta de este código con una clave temporal que el vendedor debe cambiar al entrar.")
            nombre = st.text_input("Nombre del vendedor", value=nombres_sigma.get(elegido, ""), key=f"nombre_{elegido}")
            if st.button(accion, key=f"alta_{elegido}"):
                clave = store.alta_vendedor(sesion, elegido, nombre)
                _accion(sesion, store, "cuenta_reactivada" if estado == _ESTADO["baja"] else "cuenta_alta", elegido)
                st.session_state["_clave_nueva"] = {"titulo": "Cuenta activada", "vid": elegido, "nombre": " ".join(nombre.split()), "clave": clave}
                st.rerun()
    except A.AuthError as exc:
        st.error(str(exc))
    st.caption("Los vendedores que no figuran en la lista no tienen escala de preventa cargada: para sumarlos hay que avisarle al administrador.")
