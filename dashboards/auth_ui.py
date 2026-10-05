"""Pantalla de ingreso, cambio obligatorio de clave y barra de usuario (Streamlit).

La lógica (claves, roles, bloqueos) está en `sigma_conn.auth` con tests; acá solo hay interfaz.
La sesión vive en `st.session_state["usuario"]` (sin el hash de la clave). Al recargar la página (F5) se vuelve
a pedir el ingreso."""
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:  # pragma: no cover
    HERE = Path.cwd() / "dashboards"
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import streamlit as st  # noqa: E402

from sigma_conn import auth as A  # noqa: E402
from estilo import mostrar_logo  # noqa: E402

ROL_TXT = {A.ROL_GERENTE: "Gerente", A.ROL_SUPERVISOR: "Supervisor", A.ROL_VENDEDOR: "Vendedor"}


@st.cache_resource
def _limitador() -> A.Limitador:
    return A.Limitador(max_intentos=5, bloqueo_s=300)


def _formulario_cambio(store: A.UsuariosStore, usuario: str, clave: str, obligatorio: bool) -> bool:
    """Dibuja el formulario de cambio de clave; devuelve True si se cambió."""
    with st.form(f"cambio_{clave}", clear_on_submit=True):
        actual = st.text_input("Clave actual", type="password")
        nueva = st.text_input("Clave nueva (mínimo 8, con letras y números)", type="password")
        repetida = st.text_input("Repetir clave nueva", type="password")
        enviar = st.form_submit_button("Cambiar clave")
    if enviar:
        if nueva != repetida:
            st.error("Las claves nuevas no coinciden.")
            return False
        try:
            store.cambiar_clave(usuario, actual, nueva)
        except A.AuthError as exc:
            st.error(str(exc))
            return False
        st.success("Clave cambiada.")
        return True
    return False


def requerir_login() -> dict:
    """Devuelve la sesión del usuario ingresado; si no hay, muestra el ingreso y detiene la página."""
    store = A.UsuariosStore(A.ruta_usuarios())
    sesion = st.session_state.get("usuario")
    if sesion:
        if sesion.get("debe_cambiar"):
            mostrar_logo(240)
            st.title("Elegí tu clave")
            st.info("Es tu primer ingreso (o te reseteamos la clave): tenés que elegir una clave nueva para seguir.")
            if _formulario_cambio(store, sesion["usuario"], "obligatorio", obligatorio=True):
                st.session_state["usuario"] = {**sesion, "debe_cambiar": False}
                st.rerun()
            st.stop()
        return sesion

    mostrar_logo(240)
    st.title("Tableros de ventas")
    if not store.existe():
        st.error("Todavía no hay usuarios creados. Correr: python scripts/admin/usuarios.py iniciales")
        st.stop()
    st.caption("Ingresá con tu usuario (los vendedores, su código) y tu clave.")
    with st.form("ingreso"):
        usuario = st.text_input("Usuario")
        clave = st.text_input("Clave", type="password")
        entrar = st.form_submit_button("Entrar")
    if entrar:
        lim = _limitador()
        espera = lim.segundos_bloqueado(usuario)
        if espera:
            st.error(f"Demasiados intentos. Probá de nuevo en {espera // 60 + 1} minuto(s).")
        else:
            sesion = store.autenticar(usuario, clave)
            if sesion:
                lim.ok(usuario)
                st.session_state["usuario"] = sesion
                st.rerun()
            lim.fallo(usuario)
            st.error("Usuario o clave incorrectos.")
    st.stop()


def barra_usuario(sesion: dict) -> None:
    """Datos del usuario, cambio de clave y salida, arriba de la barra lateral."""
    sb = st.sidebar
    sb.markdown(f"**{sesion['nombre']}**")
    sb.caption(ROL_TXT.get(sesion["rol"], sesion["rol"]))
    with sb.expander("Cambiar mi clave"):
        _formulario_cambio(A.UsuariosStore(A.ruta_usuarios()), sesion["usuario"], "voluntario", obligatorio=False)
    if sb.button("Salir"):
        st.session_state.clear()
        st.rerun()
    sb.divider()
