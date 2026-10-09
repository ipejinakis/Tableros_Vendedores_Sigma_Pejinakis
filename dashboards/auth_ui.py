"""Pantalla de ingreso, cambio obligatorio de clave y barra de usuario (Streamlit).

La lógica (claves, roles, bloqueos) está en `sigma_conn.auth` con tests; acá solo hay interfaz.
La sesión vive en `st.session_state["usuario"]` (sin el hash de la clave). Para no pedir la clave en cada recarga (F5),
el ingreso deja una cookie con un token al azar y el servidor guarda solo su hash (`sigma_conn.auth.SesionesStore`):
dura `SESION_DIAS` días y se revoca al salir, al cambiar o resetear la clave y al desactivar el usuario."""
import json
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:  # pragma: no cover
    HERE = Path.cwd() / "dashboards"
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from sigma_conn import auth as A  # noqa: E402
from estilo import mostrar_logo  # noqa: E402

ROL_TXT = {A.ROL_GERENTE: "Gerente", A.ROL_SUPERVISOR: "Supervisor", A.ROL_VENDEDOR: "Vendedor"}


@st.cache_resource
def _limitador() -> A.Limitador:
    return A.Limitador(max_intentos=5, bloqueo_s=300)


@st.cache_resource
def _limitador_ip() -> A.Limitador:
    return A.Limitador(max_intentos=20, bloqueo_s=600)       # 20 fallos seguidos desde una misma IP: 10 minutos de pausa


def _ip_cliente() -> str:
    """IP del visitante: detrás de Cloudflare viene en `Cf-Connecting-Ip`; si no, `X-Forwarded-For`; si no, '?'.
    Los encabezados los puede falsear quien llegue directo por la red interna: sirve para registro y freno, no como prueba."""
    try:
        h = st.context.headers
        ip = h.get("Cf-Connecting-Ip") or (h.get("X-Forwarded-For") or "").split(",")[0].strip() or h.get("X-Real-Ip")
        return ip or "?"
    except Exception:
        return "?"


def _auditoria(store: A.UsuariosStore) -> A.Auditoria:
    return A.Auditoria(A.ruta_auditoria(store.ruta))


def _sesiones(store: A.UsuariosStore) -> A.SesionesStore:
    return A.SesionesStore(A.ruta_sesiones(store.ruta), store)


def _cookie_del_navegador() -> str | None:
    try:
        return st.context.cookies.get(A.COOKIE_SESION)
    except Exception:  # Streamlit viejo (< 1.37) o sin contexto: no hay sesión persistente
        return None


def _aplicar_cookie() -> None:
    """Escribe o borra la cookie en el navegador si quedó una acción pendiente (se hace una sola vez)."""
    accion = st.session_state.pop("_cookie_accion", None)
    if not accion:
        return
    modo, token = accion
    valor, vida = (token, A.SESION_DIAS * 86400) if modo == "set" else ("", 0)
    js = (f"<script>try{{const p=window.parent;const sec=p.location.protocol==='https:'?'; Secure':'';"
          f"p.document.cookie={json.dumps(A.COOKIE_SESION)}+'='+{json.dumps(valor)}+'; path=/; max-age={vida}; SameSite=Strict'+sec;"
          f"}}catch(e){{}}</script>")
    components.html(js, height=0)


def _recordar(store: A.UsuariosStore, usuario: str) -> None:
    """Deja la sesión mantenida en este navegador (cookie con un token nuevo)."""
    token = _sesiones(store).crear(usuario)
    if token:
        st.session_state["_token"] = token
        st.session_state["_cookie_accion"] = ("set", token)


def _formulario_cambio(store: A.UsuariosStore, usuario: str, clave: str, obligatorio: bool) -> bool:
    """Dibuja el formulario de cambio de clave; devuelve True si se cambió."""
    with st.form(f"cambio_{clave}", clear_on_submit=True):
        actual = st.text_input("Clave actual", type="password")
        nueva = st.text_input("Clave nueva (mínimo 10, con letras y números, sin palabras obvias)", type="password")
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
        _auditoria(store).registrar("clave_cambiada", usuario, _ip_cliente())
        return True
    return False


def requerir_login() -> dict:
    """Devuelve la sesión del usuario ingresado; si no hay, muestra el ingreso y detiene la página."""
    store = A.UsuariosStore(A.ruta_usuarios())
    _aplicar_cookie()
    sesion = st.session_state.get("usuario")
    if not sesion:      # recarga de la página: ¿quedó una sesión mantenida en este navegador?
        token = _cookie_del_navegador()
        sesion = _sesiones(store).validar(token)
        if sesion:
            st.session_state["usuario"], st.session_state["_token"] = sesion, token
    if sesion and store.sesion_de(sesion["usuario"]) is None:      # la cuenta se dio de baja con la sesión abierta: se cierra
        st.session_state.clear()
        st.session_state["_cookie_accion"] = ("borrar", "")
        sesion = None
        st.rerun()
    if sesion:
        if sesion.get("debe_cambiar"):
            mostrar_logo(240)
            st.title("Elegí tu clave")
            st.info("Es tu primer ingreso (o te reseteamos la clave): tenés que elegir una clave nueva para seguir.")
            if _formulario_cambio(store, sesion["usuario"], "obligatorio", obligatorio=True):
                st.session_state["usuario"] = {**sesion, "debe_cambiar": False}
                if st.session_state.get("_mantener", True):
                    _recordar(store, sesion["usuario"])
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
        mantener = st.checkbox(f"Mantener la sesión iniciada en este equipo ({A.SESION_DIAS} días)", value=True,
                               help="Si es una computadora compartida, destildalo: así tendrás que ingresar de nuevo al recargar.")
        entrar = st.form_submit_button("Entrar")
    if entrar:
        lim, lim_ip, ip, aud = _limitador(), _limitador_ip(), _ip_cliente(), _auditoria(store)
        espera = max(lim.segundos_bloqueado(usuario), lim_ip.segundos_bloqueado(f"ip:{ip}") if ip != "?" else 0)
        if espera:
            aud.registrar("ingreso_bloqueado", usuario, ip)
            st.error(f"Demasiados intentos. Probá de nuevo en {espera // 60 + 1} minuto(s).")
        else:
            sesion = store.autenticar(usuario, clave)
            if sesion:
                lim.ok(usuario)
                aud.registrar("ingreso_ok", sesion["usuario"], ip)
                st.session_state["usuario"] = sesion
                st.session_state["_mantener"] = mantener
                if mantener and not sesion.get("debe_cambiar"):
                    _recordar(store, sesion["usuario"])
                st.rerun()
            lim.fallo(usuario)
            if ip != "?":
                lim_ip.fallo(f"ip:{ip}")
            aud.registrar("ingreso_fallido", usuario, ip)
            st.error("Usuario o clave incorrectos.")
    st.stop()


def barra_usuario(sesion: dict) -> None:
    """Datos del usuario, cambio de clave y salida, arriba de la barra lateral."""
    sb = st.sidebar
    sb.markdown(f"**{sesion['nombre']}**")
    sb.caption(ROL_TXT.get(sesion["rol"], sesion["rol"]))
    with sb.expander("Cambiar mi clave"):
        us = A.UsuariosStore(A.ruta_usuarios())
        if _formulario_cambio(us, sesion["usuario"], "voluntario", obligatorio=False) and st.session_state.get("_token"):
            _recordar(us, sesion["usuario"])    # cambiar la clave invalida la cookie vieja: se entrega una nueva
            _aplicar_cookie()
    if sb.button("Salir"):
        token = st.session_state.get("_token") or _cookie_del_navegador()
        _almacen = A.UsuariosStore(A.ruta_usuarios())
        _sesiones(_almacen).revocar(token)
        _auditoria(_almacen).registrar("salida", sesion["usuario"], _ip_cliente())
        st.session_state.clear()
        st.session_state["_cookie_accion"] = ("borrar", "")
        st.rerun()
    sb.divider()
