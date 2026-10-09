"""Feriados cargados desde el tablero: almacenamiento, reglas y efecto en los días de venta y los avances esperados."""
from datetime import date

import pytest

from sigma_conn import config_feriados as CF
from sigma_conn import negocio as N
from sigma_conn import objetivos as O
from sigma_conn import tableros as TB
from sigma_conn.config_objetivos import ConfigError, ConflictoError

HOY = date(2026, 10, 9)


@pytest.fixture
def store(tmp_path):
    return CF.FeriadosStore(tmp_path)


def test_guardar_y_leer(store):
    store.guardar("juan", "2026-10", [date(2026, 10, 12), date(2026, 10, 10)], "Diversidad cultural", hoy=HOY)
    assert store.del_mes("2026-10") == [date(2026, 10, 10), date(2026, 10, 12)]
    assert store.todos() == frozenset({date(2026, 10, 10), date(2026, 10, 12)})
    h = store.historial("2026-10")
    assert len(h) == 1 and h[0]["actor"] == "juan" and h[0]["motivo"] == "Diversidad cultural"
    assert {c["despues"] for c in h[0]["cambios"]} == {"feriado"}


def test_quitar_feriado_queda_en_historial(store):
    store.guardar("juan", "2026-10", [date(2026, 10, 12)], hoy=HOY)
    store.guardar("ana", "2026-10", [], hoy=HOY)
    assert store.del_mes("2026-10") == []
    assert store.historial("2026-10")[0]["cambios"][0]["despues"] == "día de venta"


def test_no_acepta_domingo_otro_mes_ni_mes_cerrado_ni_sin_cambios(store):
    with pytest.raises(ConfigError, match="domingo"):
        store.guardar("juan", "2026-10", [date(2026, 10, 11)], hoy=HOY)
    with pytest.raises(ConfigError, match="no pertenece"):
        store.guardar("juan", "2026-10", [date(2026, 11, 2)], hoy=HOY)
    with pytest.raises(ConfigError, match="cerrado"):
        store.guardar("juan", "2026-09", [date(2026, 9, 7)], hoy=HOY)
    with pytest.raises(ConfigError, match="sin cambios|No hay cambios"):
        store.guardar("juan", "2026-10", [], hoy=HOY)


def test_conflicto_de_version(store):
    store.guardar("juan", "2026-10", [date(2026, 10, 12)], hoy=HOY)
    with pytest.raises(ConflictoError):
        store.guardar("ana", "2026-10", [date(2026, 10, 13)], version_base=0, hoy=HOY)
    store.guardar("ana", "2026-10", [date(2026, 10, 13)], version_base=store.version(), hoy=HOY)


def test_feriados_vigentes_nunca_rompe(tmp_path):
    (tmp_path / "feriados.json").write_text("{esto no es json", encoding="utf-8")
    assert CF.feriados_vigentes(CF.FeriadosStore(tmp_path)) == frozenset()


def test_sin_feriados_todo_igual_que_antes():
    assert O.dias_de_venta_mes(2026, 10) == 27 == O.dias_de_venta_mes(2026, 10, None) == O.dias_de_venta_mes(2026, 10, frozenset())
    assert O.dias_objetivo_mes(2026, 10) == N.DIAS_OBJETIVO_MES


def test_feriado_resta_dias_de_venta():
    fer = frozenset({date(2026, 10, 12)})                       # lunes
    assert O.dias_de_venta_mes(2026, 10, fer) == 26
    assert O.dias_transcurridos(date(2026, 10, 9), fer) == O.dias_transcurridos(date(2026, 10, 9))      # el feriado es posterior
    assert O.dias_transcurridos(date(2026, 10, 13), fer) == O.dias_transcurridos(date(2026, 10, 13)) - 1
    assert O.dias_restantes(date(2026, 10, 9), fer) == O.dias_restantes(date(2026, 10, 9)) - 1
    assert O.dias_objetivo_mes(2026, 10, fer) == 25
    assert O.dias_objetivo_mes(2026, 11, fer) == 26              # otro mes: no cambia
    assert O.dias_objetivo_mes(2026, 10, frozenset({date(2026, 10, 11)})) == 26   # domingo: no resta


def test_evaluar_facturacion_con_feriados():
    corte = date(2026, 10, 9)
    base = O.evaluar_facturacion(20_000_000, N.PERFIL_GENERAL, corte)
    fer = O.evaluar_facturacion(20_000_000, N.PERFIL_GENERAL, corte, None, frozenset({date(2026, 10, 12), date(2026, 10, 13)}))
    assert fer["dias_restantes"] == base["dias_restantes"] - 2
    assert fer["dias_transcurridos"] == base["dias_transcurridos"]
    assert fer["proyeccion"] < base["proyeccion"]                 # quedan menos días para vender al mismo ritmo
    e1 = fer["escalones"][0]
    assert e1["objetivo"] == base["escalones"][0]["objetivo"]     # el escalón no cambia
    assert e1["objetivo_diario"] == pytest.approx(e1["objetivo"] / 24)
    assert e1["media_necesaria"] > base["escalones"][0]["media_necesaria"]


def test_fraccion_esperada_con_feriados():
    ini, fin = date(2026, 9, 1), date(2026, 10, 31)
    assert TB.fraccion_esperada(ini, fin, date(2026, 9, 20)) == pytest.approx(17 / 53)
    fer = frozenset({date(2026, 9, 7), date(2026, 10, 12)})      # lunes de septiembre y de octubre
    assert TB.fraccion_esperada(ini, fin, date(2026, 9, 20), fer) == pytest.approx(16 / 51)
    assert TB.fraccion_esperada(ini, fin, date(2026, 10, 31), fer) == 1.0
