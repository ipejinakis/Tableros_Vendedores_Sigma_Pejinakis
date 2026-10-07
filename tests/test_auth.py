import json
import os
import stat

import pytest

from sigma_conn import auth as A


def _store(tmp_path):
    return A.UsuariosStore(tmp_path / "auth" / "usuarios.json")


def test_hash_y_verificacion():
    h = A.hash_clave("abc12345")
    assert h.startswith("scrypt$") and "abc12345" not in h
    assert A.verificar_clave("abc12345", h) and not A.verificar_clave("abc12346", h)
    assert A.hash_clave("abc12345") != h                       # sal distinta cada vez
    assert not A.verificar_clave("x", "basura") and not A.verificar_clave("x", "md5$1$2$3$4$5")


def test_clave_generada_legible_y_distinta():
    k = A.generar_clave()
    assert len(k) == 10 and set(k) <= set(A._ALFABETO) and A.generar_clave() != k
    assert not set(k) & set("0o1l")


def test_validar_clave_nueva():
    with pytest.raises(A.AuthError):
        A.validar_clave_nueva("corta1")
    with pytest.raises(A.AuthError):
        A.validar_clave_nueva("sololetrasaqui")
    with pytest.raises(A.AuthError):
        A.validar_clave_nueva("123456789")
    A.validar_clave_nueva("letras12345")
    with pytest.raises(A.AuthError):
        A.validar_clave_nueva("letras123")                      # 9 caracteres: el mínimo es 10


def test_validar_clave_rechaza_comunes_repetitivas_y_con_el_usuario():
    for mala in ("password123", "Pejinakis2026", "tableros2026", "contrasena99", "Qwerty12345", "aaaabbbb1111", "1234567890a"):
        with pytest.raises(A.AuthError):
            A.validar_clave_nueva(mala)
    with pytest.raises(A.AuthError):
        A.validar_clave_nueva("miusuario8472x", "MiUsuario")      # contiene el usuario
    A.validar_clave_nueva("Verde-Mesa-4821")


def test_auditoria_registra_sin_claves_y_con_permiso_privado(tmp_path):
    aud = A.Auditoria(tmp_path / "auth" / "auditoria.log", max_bytes=10_000)
    aud.registrar("ingreso_ok", "101", "1.2.3.4")
    aud.registrar("ingreso_fallido", "MiClaveSecreta con espacios!!", "1.2.3.4")        # una clave tipeada en el campo usuario
    texto = (tmp_path / "auth" / "auditoria.log").read_text(encoding="utf-8")
    lineas = [json.loads(x) for x in texto.splitlines()]
    assert [l["evento"] for l in lineas] == ["ingreso_ok", "ingreso_fallido"]
    assert lineas[0]["usuario"] == "101" and lineas[0]["ip"] == "1.2.3.4" and lineas[0]["ts"].endswith("-03:00")
    assert lineas[1]["usuario"] == "<no válido>" and "Secreta" not in texto
    assert stat.S_IMODE(os.stat(tmp_path / "auth" / "auditoria.log").st_mode) == 0o600


def test_crear_y_autenticar_con_clave_temporal(tmp_path):
    st = _store(tmp_path)
    clave = st.crear("101", A.ROL_VENDEDOR, "Arias Daniel", vendedor_id="101")
    s = st.autenticar("101", clave)
    assert s == {"usuario": "101", "rol": "vendedor", "nombre": "Arias Daniel", "vendedor_id": "101", "debe_cambiar": True}
    assert st.autenticar("101", "otra") is None and st.autenticar("999", clave) is None
    assert st.autenticar(" 101 ", clave) is not None             # el usuario se normaliza


def test_el_archivo_no_guarda_claves_en_claro_y_es_privado(tmp_path):
    st = _store(tmp_path)
    clave = st.crear("mamaya", A.ROL_SUPERVISOR, "Mauro Amaya")
    texto = st.ruta.read_text(encoding="utf-8")
    assert clave not in texto and "hash" in texto
    assert stat.S_IMODE(os.stat(st.ruta).st_mode) == 0o600
    assert all("hash" not in u for u in st.listar())              # listar nunca devuelve hashes
    assert json.loads(texto)["mamaya"]["vendedor_id"] is None


def test_validaciones_al_crear(tmp_path):
    st = _store(tmp_path)
    st.crear("101", A.ROL_VENDEDOR, "X", vendedor_id="101")
    with pytest.raises(A.AuthError):
        st.crear("101", A.ROL_VENDEDOR, "X", vendedor_id="101")           # duplicado
    with pytest.raises(A.AuthError):
        st.crear("555", A.ROL_VENDEDOR, "X", vendedor_id="555")           # sin escala de preventa
    with pytest.raises(A.AuthError):
        st.crear("102", A.ROL_VENDEDOR, "X", vendedor_id="101")           # el usuario debe ser su código
    with pytest.raises(A.AuthError):
        st.crear("jefe", "dueño", "X")                                     # rol inválido
    with pytest.raises(A.AuthError):
        st.crear("con espacio", A.ROL_GERENTE, "X")


def test_cambio_obligatorio_de_clave(tmp_path):
    st = _store(tmp_path)
    temp = st.crear("103", A.ROL_VENDEDOR, "Balderrama", vendedor_id="103")
    with pytest.raises(A.AuthError):
        st.cambiar_clave("103", "incorrecta", "nueva12345")               # clave actual mal
    with pytest.raises(A.AuthError):
        st.cambiar_clave("103", temp, temp)                                # igual a la actual
    with pytest.raises(A.AuthError):
        st.cambiar_clave("103", temp, "corta")
    st.cambiar_clave("103", temp, "nueva12345")
    assert st.autenticar("103", temp) is None
    s = st.autenticar("103", "nueva12345")
    assert s is not None and s["debe_cambiar"] is False


def test_resetear_y_desactivar(tmp_path):
    st = _store(tmp_path)
    st.crear("105", A.ROL_VENDEDOR, "Valeriano", vendedor_id="105", clave="primera123")
    st.cambiar_clave("105", "primera123", "segunda456")
    nueva = st.resetear("105")
    assert st.autenticar("105", "segunda456") is None
    assert st.autenticar("105", nueva)["debe_cambiar"] is True
    st.desactivar("105")
    assert st.autenticar("105", nueva) is None
    st.desactivar("105", activo=True)
    assert st.autenticar("105", nueva) is not None
    with pytest.raises(A.AuthError):
        st.resetear("no-existe")


def test_ve_todo_segun_rol():
    assert A.ve_todo({"rol": "gerente"}) and A.ve_todo({"rol": "supervisor"})
    assert not A.ve_todo({"rol": "vendedor"}) and not A.ve_todo(None) and not A.ve_todo({})


def test_limitador_bloquea_y_se_libera():
    lim = A.Limitador(max_intentos=3, bloqueo_s=60)
    for t in (0, 1, 2):
        assert lim.segundos_bloqueado("101", ahora=t) == 0
        lim.fallo("101", ahora=t)
    assert lim.segundos_bloqueado("101", ahora=3) > 0
    assert lim.segundos_bloqueado("102", ahora=3) == 0           # otro usuario no se ve afectado
    assert lim.segundos_bloqueado("101", ahora=100) == 0          # pasó la ventana
    lim.fallo("101", ahora=100)
    lim.ok("101")
    assert lim.segundos_bloqueado("101", ahora=101) == 0


def test_ruta_usuarios_por_variable_de_entorno(tmp_path):
    previo = os.environ.get("SIGMA_AUTH_FILE")
    os.environ["SIGMA_AUTH_FILE"] = str(tmp_path / "x" / "u.json")
    try:
        assert A.ruta_usuarios() == tmp_path / "x" / "u.json"
    finally:
        if previo is None:
            os.environ.pop("SIGMA_AUTH_FILE", None)
        else:
            os.environ["SIGMA_AUTH_FILE"] = previo


def test_ruta_usuarios_por_defecto_es_un_archivo_dentro_de_data(tmp_path):
    previo = {k: os.environ.get(k) for k in ("SIGMA_AUTH_FILE", "SIGMA_DATA_DIR")}
    os.environ.pop("SIGMA_AUTH_FILE", None)
    os.environ["SIGMA_DATA_DIR"] = str(tmp_path / "datos")
    try:
        ruta = A.ruta_usuarios()
        assert ruta == tmp_path / "datos" / "auth" / "usuarios.json" or ruta.name == "usuarios.json"
        assert ruta.name == "usuarios.json" and not ruta.is_dir()
    finally:
        for k, val in previo.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val


# ----------------------------------------------------------------------------- sesiones persistentes
def _con_sesiones(tmp_path):
    us = A.UsuariosStore(tmp_path / "usuarios.json")
    clave = us.crear("gerencia", A.ROL_GERENTE, "Gerencia")
    us.cambiar_clave("gerencia", clave, "claveNueva123")
    return us, A.SesionesStore(A.ruta_sesiones(tmp_path / "usuarios.json"), us)


def test_sesion_persistente_se_valida_y_se_revoca(tmp_path):
    us, ses = _con_sesiones(tmp_path)
    token = ses.crear("gerencia")
    assert token and len(token) >= 40
    assert ses.validar(token)["usuario"] == "gerencia" and ses.validar(token)["rol"] == "gerente"
    assert ses.validar("token-falso") is None and ses.validar(None) is None and ses.validar("") is None
    ses.revocar(token)
    assert ses.validar(token) is None


def test_sesion_persistente_vence(tmp_path):
    _, ses = _con_sesiones(tmp_path)
    token = ses.crear("gerencia", ahora=1_000_000)
    assert ses.validar(token, ahora=1_000_000 + 6 * 86400)
    assert ses.validar(token, ahora=1_000_000 + 7 * 86400 + 1) is None


def test_sesion_persistente_no_sobrevive_a_cambio_de_clave_ni_desactivacion(tmp_path):
    us, ses = _con_sesiones(tmp_path)
    t1 = ses.crear("gerencia")
    us.cambiar_clave("gerencia", "claveNueva123", "otraClave456")
    assert ses.validar(t1) is None                          # cambió la clave: la sesión vieja ya no vale
    t2 = ses.crear("gerencia")
    us.resetear("gerencia")
    assert ses.validar(t2) is None                          # reset por el administrador
    us.cambiar_clave("gerencia", us.resetear("gerencia"), "claveFinal789")
    t3 = ses.crear("gerencia")
    us.desactivar("gerencia")
    assert ses.validar(t3) is None and ses.crear("gerencia") is None


def test_sesiones_solo_guardan_hash_del_token_y_el_archivo_es_privado(tmp_path):
    import os
    import stat
    _, ses = _con_sesiones(tmp_path)
    token = ses.crear("gerencia")
    texto = ses.ruta.read_text(encoding="utf-8")
    assert token not in texto and "claveNueva123" not in texto
    if os.name == "posix":
        assert stat.S_IMODE(ses.ruta.stat().st_mode) == 0o600
    ses.revocar_usuario("gerencia")
    assert ses.validar(token) is None
