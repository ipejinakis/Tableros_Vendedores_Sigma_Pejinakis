"""Objetivos bimestrales editables (cobertura, Mis Ventas, Club Faro)."""
from datetime import date

import pandas as pd
import pytest

from sigma_conn import config_bimestre as CB
from sigma_conn import config_objetivos as CO

HOY = date(2026, 10, 9)          # bimestre en curso: sep-oct (clave 2026-09)


@pytest.fixture
def st(tmp_path):
    return CB.ObjetivosBimestreStore(tmp_path / "config")


def _cob():
    filas = [{"vendedor_id": v, "categoria": c, "grupo": "PREVENTA", "objetivo": 100.0, "total_distribuidora": 1000.0,
              "periodo": "2026-09/2026-10"} for v in ("101", "102") for c in ("BPC", "FOOD", "HC")]
    return pd.DataFrame(filas)


def test_claves_de_bimestre():
    assert CB.bimestre_clave(date(2026, 10, 9)) == "2026-09" and CB.bimestre_clave(date(2026, 9, 1)) == "2026-09"
    assert CB.bimestre_clave(date(2026, 11, 3)) == "2026-11" and CB.bimestre_clave(date(2026, 12, 31)) == "2026-11"
    assert CB.bimestre_texto("2026-09") == "2026-09/2026-10"
    assert CB.siguiente_bimestre("2026-11") == "2027-01"


def test_sin_edicion_rige_el_excel(st):
    df, origen, _ = st.vigente("cobertura", "2026-09", _cob())
    assert origen == "excel" and df["objetivo"].eq(100).all()


def test_edicion_y_herencia_al_bimestre_siguiente(st):
    cob = _cob()
    nuevos = cob.copy()
    nuevos.loc[(nuevos.vendedor_id == "101") & (nuevos.categoria == "BPC"), "objetivo"] = 120.0
    st.guardar("mamaya", "cobertura", "2026-09", nuevos, cob, "ajuste", hoy=HOY)
    df, origen, _ = st.vigente("cobertura", "2026-09", cob)
    assert origen == "2026-09" and df.loc[(df.vendedor_id == "101") & (df.categoria == "BPC"), "objetivo"].iloc[0] == 120
    nov, origen2, _ = st.vigente("cobertura", "2026-11", cob)
    assert origen2 == "2026-09" and nov["periodo"].iloc[0] == "2026-11/2026-12"
    assert nov.loc[(nov.vendedor_id == "101") & (nov.categoria == "BPC"), "objetivo"].iloc[0] == 120
    r = st.historial("cobertura")[0]
    assert r["actor"] == "mamaya" and r["cambios"][0]["antes"] == 100.0 and r["cambios"][0]["despues"] == 120.0


def test_bimestre_cerrado_y_choque_de_versiones(st):
    cob = _cob()
    n = cob.copy()
    n["objetivo"] = 5.0
    with pytest.raises(CO.ConfigError, match="cerrado"):
        st.guardar("x", "cobertura", "2026-07", n, cob, hoy=HOY)
    v = st.version()
    st.guardar("a", "cobertura", "2026-09", n, cob, version_base=v, hoy=HOY)
    otro = cob.copy()
    otro["objetivo"] = 7.0
    with pytest.raises(CO.ConflictoError):
        st.guardar("b", "cobertura", "2026-09", otro, cob, version_base=v, hoy=HOY)


def test_no_se_pueden_sumar_filas_ni_valores_invalidos(st):
    cob = _cob()
    nuevo = cob.iloc[[0]].copy()
    nuevo["vendedor_id"] = "130"
    with pytest.raises(CO.ConfigError, match="SIGMA"):
        st.guardar("x", "cobertura", "2026-09", nuevo, cob, hoy=HOY)
    neg = cob.iloc[[0]].copy()
    neg["objetivo"] = -1.0
    with pytest.raises(CO.ConfigError, match="negativos"):
        st.guardar("x", "cobertura", "2026-09", neg, cob, hoy=HOY)
    with pytest.raises(CO.ConfigError, match="No hay cambios"):
        st.guardar("x", "cobertura", "2026-09", cob, cob, hoy=HOY)


def test_total_de_la_distribuidora_uniforme_por_categoria(st):
    cob = _cob()
    n = cob.copy()
    n.loc[n.index[0], "total_distribuidora"] = 2000.0       # solo una fila de BPC: queda inconsistente
    with pytest.raises(CO.ConfigError, match="mismo"):
        st.guardar("x", "cobertura", "2026-09", n, cob, hoy=HOY)
    n.loc[(n.categoria == "BPC"), "total_distribuidora"] = 2000.0
    st.guardar("x", "cobertura", "2026-09", n, cob, hoy=HOY)
    assert st.vigente("cobertura", "2026-09", cob)[0].query("categoria == 'BPC'")["total_distribuidora"].eq(2000).all()


def test_objetivos_vigentes_nunca_rompe(tmp_path, monkeypatch):
    monkeypatch.setattr(CB, "ruta_config", lambda: tmp_path / "config")
    base = _cob()
    assert CB.objetivos_vigentes("cobertura", date(2026, 9, 1), base).equals(base)
    assert CB.objetivos_vigentes("cobertura", date(2026, 9, 1), None) is None
