"""Configuración editable de objetivos de Facturación: herencia entre meses, períodos, choques e historial."""
from datetime import date

import pytest

from sigma_conn import config_objetivos as CO
from sigma_conn import negocio as N
from sigma_conn import objetivos as O

HOY = date(2026, 10, 9)


@pytest.fixture
def st(tmp_path):
    return CO.ConfigStore(tmp_path / "config")


def _base(cfg=None):
    return (cfg or CO.semilla()).a_dict()


def test_sin_configuracion_rigen_los_valores_del_codigo(st):
    c = st.cargar("2026-10")
    assert c.origen == "codigo" and not c.propia
    assert c.escalas["GENERAL"] == (50_000_000, 60_000_000, 72_000_000)
    assert c.premios == (200_000, 400_000, 600_000) and c.vendedor_perfil == N.VENDEDOR_PERFIL


def test_guardar_y_heredar_en_meses_posteriores(st):
    d = _base()
    d["escalas"]["GENERAL"] = [55_000_000, 65_000_000, 75_000_000]
    st.guardar("mamaya", "2026-10", d, "ajuste", hoy=HOY)
    assert st.cargar("2026-10").propia and st.cargar("2026-10").escalas["GENERAL"][0] == 55_000_000
    nov = st.cargar("2026-11")
    assert not nov.propia and nov.origen == "2026-10" and nov.escalas["GENERAL"][0] == 55_000_000
    assert st.cargar("2026-09").origen == "codigo"       # un mes anterior no hereda del futuro


def test_mes_cerrado_es_solo_lectura_y_el_corriente_es_editable(st):
    d = _base()
    d["premios"] = [250_000, 450_000, 650_000]
    with pytest.raises(CO.ConfigError, match="cerrado"):
        st.guardar("x", "2026-09", d, hoy=HOY)
    assert st.guardar("x", "2026-10", d, hoy=HOY).premios == (250_000, 450_000, 650_000)
    assert st.guardar("x", "2026-11", {**d, "premios": [1, 2, 3]}, hoy=HOY).premios == (1, 2, 3)


def test_choque_de_versiones(st):
    leida = st.cargar("2026-10").version
    d1, d2 = _base(), _base()
    d1["premios"] = [210_000, 400_000, 600_000]
    d2["premios"] = [220_000, 400_000, 600_000]
    st.guardar("a", "2026-10", d1, version_base=leida, hoy=HOY)
    with pytest.raises(CO.ConflictoError):
        st.guardar("b", "2026-10", d2, version_base=leida, hoy=HOY)
    assert st.cargar("2026-10").premios[0] == 210_000


def test_historial_registra_quien_cuando_antes_y_despues(st):
    d = _base()
    d["escalas"]["AASS"] = [110_000_000, 120_000_000, 144_000_000]
    d["premios"] = [210_000, 400_000, 600_000]
    st.guardar("nbuldurini", "2026-10", d, "vacaciones", hoy=HOY)
    r = st.historial("2026-10")[0]
    assert r["actor"] == "nbuldurini" and r["motivo"] == "vacaciones"
    campos = {c["campo"]: (c["antes"], c["despues"]) for c in r["cambios"]}
    assert campos["Escala AASS · escalón 1"] == (100_000_000, 110_000_000)
    assert campos["Premio escalón 1"] == (200_000, 210_000)
    assert st.historial("2026-11") == []


def test_sin_cambios_no_guarda_y_valida_datos(st):
    with pytest.raises(CO.ConfigError, match="No hay cambios"):
        st.guardar("x", "2026-10", _base(), hoy=HOY)
    malo = _base()
    malo["escalas"]["GENERAL"] = [60_000_000, 50_000_000, 72_000_000]
    with pytest.raises(CO.ConfigError, match="creciente"):
        st.guardar("x", "2026-10", malo, hoy=HOY)
    malo = _base()
    malo["vendedor_perfil"]["abc"] = "GENERAL"
    with pytest.raises(CO.ConfigError):  # sumar un vendedor no está permitido
        st.guardar("x", "2026-10", malo, hoy=HOY)
    malo = _base()
    malo["vendedor_perfil"]["101"] = "OTRO"
    with pytest.raises(CO.ConfigError):
        st.guardar("x", "2026-10", malo, hoy=HOY)


def test_volver_a_heredar(st):
    d = _base()
    d["premios"] = [250_000, 450_000, 650_000]
    st.guardar("x", "2026-10", d, hoy=HOY)
    c = st.volver_a_heredar("x", "2026-10", hoy=HOY)
    assert not c.propia and c.premios == (200_000, 400_000, 600_000)
    assert st.historial()[0]["tipo"] == "herencia"


def test_la_configuracion_cambia_el_calculo_de_los_escalones(st):
    d = _base()
    d["escalas"]["GENERAL"] = [40_000_000, 60_000_000, 72_000_000]
    d["premios"] = [300_000, 400_000, 600_000]
    st.guardar("x", "2026-10", d, hoy=HOY)
    cfg = st.cargar("2026-10")
    ev = O.evaluar_facturacion(45_000_000, "GENERAL", date(2026, 10, 9), cfg)
    assert ev["escalon"] == 1 and ev["premio"] == 300_000
    base = O.evaluar_facturacion(45_000_000, "GENERAL", date(2026, 10, 9))
    assert base["escalon"] == 0


def test_vendedores_y_perfiles_no_se_editan(st):
    cfg = st.cargar("2026-10")
    cambia = _base(cfg)
    cambia["vendedor_perfil"]["101"] = "INTERIOR"
    with pytest.raises(CO.ConfigError, match="SIGMA"):
        st.guardar("x", "2026-10", cambia, hoy=HOY)
    nuevo = _base(cfg)
    nuevo["vendedor_perfil"]["130"] = "GENERAL"
    with pytest.raises(CO.ConfigError, match="SIGMA"):
        st.guardar("x", "2026-10", nuevo, hoy=HOY)
    menos = _base(cfg)
    del menos["vendedor_perfil"]["101"]
    with pytest.raises(CO.ConfigError, match="SIGMA"):
        st.guardar("x", "2026-10", menos, hoy=HOY)


def test_vendedores_con_escala_lee_el_almacen(tmp_path, monkeypatch):
    monkeypatch.setattr(CO, "ruta_config", lambda: tmp_path / "config")
    assert CO.vendedores_con_escala() == sorted(N.VENDEDOR_PERFIL)
