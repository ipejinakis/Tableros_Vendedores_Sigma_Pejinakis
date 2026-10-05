"""Smoke test del tablero de gerentes con AppTest de Streamlit (se saltea si streamlit no está instalado)."""
import os
import sys
from datetime import date
from pathlib import Path

import pytest

from sigma_conn.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tableros import ART, VEND, _ventas

ROOT = Path(__file__).resolve().parents[1]


def _requiere_streamlit():
    try:
        import streamlit  # noqa: F401
    except ImportError:
        pytest.skip("streamlit no está instalado")


def _preparar(tmp_path, con_objetivos=False):
    from sigma_conn import tableros as TB  # noqa: F401
    data = tmp_path / "data"
    st_ = Store(data, "csv")
    st_.upsert_window("fact_ventas_item", _ventas(), date(2026, 9, 1), date(2026, 9, 30))
    st_.write_table("dim_articulo", ART.assign(categoria_cobertura=None) if con_objetivos else ART)
    st_.write_table("dim_vendedor", VEND)
    if con_objetivos:
        import pandas as pd
        st_.write_table("obj_cobertura", pd.DataFrame([
            {"vendedor_id": "101", "categoria": c, "grupo": "PREVENTA", "objetivo": 10.0, "total_distribuidora": 100.0,
             "periodo": "2026-09/2026-10"} for c in ("BPC", "FOOD", "HC")]))
        st_.write_table("obj_mis_ventas", pd.DataFrame([
            {"campana": "DOVE_180ML", "campana_excel": "DOVE", "tipo": "COBERTURA", "supervisor_id": "5", "vendedor_id": "101",
             "target": 5.0, "remanente": None, "periodo": "2026-09/2026-10"}]))
        st_.write_table("cfg_campana_articulo", pd.DataFrame([
            {"articulo_id": "A", "campana": "DOVE_180ML", "descripcion": "X", "sugerencia": "S", "incluir": True,
             "fuente": "por defecto (S)", "periodo": "2026-09/2026-10"}]))
    return data


def _correr(pagina, sesion, data):
    from streamlit.testing.v1 import AppTest
    previo = {k: os.environ.get(k) for k in ("SIGMA_DATA_DIR", "SIGMA_STORE_FORMAT")}
    os.environ["SIGMA_DATA_DIR"], os.environ["SIGMA_STORE_FORMAT"] = str(data), "csv"
    try:
        at = AppTest.from_file(str(ROOT / "dashboards" / pagina), default_timeout=60)
        if sesion is not None:
            at.session_state["usuario"] = sesion
        return at.run()
    finally:
        for k, val in previo.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val


GERENTE = {"usuario": "jperez", "rol": "gerente", "nombre": "Juan Pérez", "vendedor_id": None, "debe_cambiar": False}
VENDEDOR = {"usuario": "101", "rol": "vendedor", "nombre": "Arias Daniel", "vendedor_id": "101", "debe_cambiar": False}


def test_la_app_de_gerentes_levanta_sin_errores(tmp_path):
    _requiere_streamlit()
    at = _correr("gerentes.py", GERENTE, _preparar(tmp_path))
    assert not at.exception
    assert len(at.metric) >= 4


def test_gerentes_sin_sesion_no_muestra_datos(tmp_path):
    _requiere_streamlit()
    at = _correr("gerentes.py", None, _preparar(tmp_path))
    assert not at.exception and len(at.metric) == 0 and len(at.error) == 1


def test_un_vendedor_no_entra_al_tablero_de_gerentes(tmp_path):
    _requiere_streamlit()
    at = _correr("gerentes.py", VENDEDOR, _preparar(tmp_path))
    assert not at.exception and len(at.metric) == 0 and len(at.error) == 1


def test_la_vista_del_vendedor_levanta_y_muestra_solo_lo_suyo(tmp_path):
    _requiere_streamlit()
    at = _correr("vendedor.py", VENDEDOR, _preparar(tmp_path, con_objetivos=True))
    assert not at.exception
    assert len(at.metric) == 3                                    # venta, premio ganado, premio a fin de mes
    texto = " ".join(m.value for m in at.metric)
    assert "60,0 M$" in texto                                     # sus 60 M$ (no el total de la empresa ni los de otros)


def test_la_vista_del_vendedor_exige_rol_vendedor(tmp_path):
    _requiere_streamlit()
    for sesion in (None, GERENTE):
        at = _correr("vendedor.py", sesion, _preparar(tmp_path))
        assert not at.exception and len(at.metric) == 0 and len(at.error) == 1


def test_marcas_de_texto_y_lineas_llevan_color_explicito():
    """Altair dibuja texto y líneas en negro por defecto: invisibles en el tema oscuro de Streamlit."""
    import re
    paginas = sorted((ROOT / "dashboards").glob("*.py"))
    assert {p.name for p in paginas} >= {"gerentes.py", "vendedor.py"}
    total = 0
    for pagina in paginas:
        src = pagina.read_text(encoding="utf-8")
        for tipo, args in re.findall(r"mark_(text|tick|rule)\(([^)]*)\)", src):
            total += 1
            assert "color=" in args, f"{pagina.name}: mark_{tipo}({args}) sin color explícito"
            if tipo == "text":
                assert "color=TXT" in args, f"{pagina.name}: mark_text({args}) debe usar color=TXT"
    assert total, "no se encontraron marcas: ¿cambió el patrón?"


def test_las_paginas_exigen_sesion_y_el_vendedor_sale_de_la_sesion():
    """Chequeo estático de seguridad: acceso por sesión y el vendedor nunca viene de un control de pantalla."""
    ger = (ROOT / "dashboards" / "gerentes.py").read_text(encoding="utf-8")
    ven = (ROOT / "dashboards" / "vendedor.py").read_text(encoding="utf-8")
    app = (ROOT / "dashboards" / "app.py").read_text(encoding="utf-8")
    assert 'st.session_state.get("usuario")' in ger and 'in ("gerente", "supervisor")' in ger
    assert 'st.session_state.get("usuario")' in ven and '"vendedor"' in ven
    assert 'VID = str(_sesion["vendedor_id"])' in ven
    for control in ("selectbox", "multiselect", "text_input", "number_input"):
        for linea in ven.splitlines():
            if control in linea:
                assert "vendedor" not in linea.lower().split("=")[0], f"el vendedor no puede elegirse en pantalla: {linea.strip()}"
    assert "requerir_login()" in app and "ve_todo(usuario)" in app
