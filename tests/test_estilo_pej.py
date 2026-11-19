"""Estética compartida con Rentabilidad y Torre de control (`dashboards/estilo_pej.py`) y menú por rol."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboards"))

import menu_tableros as MT  # noqa: E402
import pytest  # noqa: E402

try:
    import streamlit  # noqa: F401
    import estilo_pej as E  # noqa: E402
except ImportError:  # pragma: no cover
    E = None

pytestmark = pytest.mark.skipif(E is None, reason="streamlit no está instalado")


def test_tono_por_variacion_igual_que_rentabilidad():
    assert E.tono_por_variacion(None) == "azul" and E.tono_por_variacion(0.01) == "azul"
    assert E.tono_por_variacion(3.0) == "verde"
    assert E.tono_por_variacion(-3.0) == "naranja" and E.tono_por_variacion(-5.0) == "rojo"
    assert E.tono_por_variacion(-3.0, mejor="baja") == "verde" and E.tono_por_variacion(8.0, mejor="baja") == "rojo"


def test_tono_estado_usa_el_semaforo_existente():
    assert [E.tono_estado(x) for x in ("verde", "amarillo", "rojo")] == ["verde", "naranja", "rojo"]
    assert E.tono_estado("sin_objetivo") == "azul" and E.tono_estado(None) == "azul"


def test_textos_de_periodo_y_variacion():
    assert E.etiqueta_periodo("2026-08") == "ago 2026"
    assert E.texto_variacion(2.2, "%", "ago 2026") == "▲ +2,2 % vs. ago 2026"
    assert E.texto_variacion(-1.0, "pp") == "▼ -1,0 pp" and E.texto_variacion(None) is None
    assert E.formato_pct(19.84) == "19,8 %"


def test_el_menu_solo_muestra_ventas_a_supervisores_y_vendedores():
    """La regla de oro, en el menú: gerente ve los tres tableros; supervisor y vendedor, solo Ventas.
    (Lo que realmente impide entrar a Rentabilidad o a Torre es el login de esos tableros.)"""
    assert [t["titulo"] for t in MT.visibles("gerente")] == ["Rentabilidad", "Control tower", "Ventas"]
    for rol in ("supervisor", "vendedor", None, "otro"):
        assert [t["titulo"] for t in MT.visibles(rol)] == ["Ventas"]


def test_el_menu_dibuja_el_actual_sin_link_y_los_otros_con_link(monkeypatch):
    capturado = []
    monkeypatch.setattr(E.st, "markdown", lambda html, **kw: capturado.append(html))
    monkeypatch.setattr(E.st, "sidebar", type("SB", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: False})())
    E.barra_lateral_nav("Ventas", "gerente")
    html = capturado[0]
    assert '<span class="on">Ventas</span>' in html
    assert 'href="https://tablerosrentabilidad.pejinakisit.com"' in html and 'href="https://tablerostorre.pejinakisit.com"' in html
    assert 'href="https://tablerosventas.pejinakisit.com"' not in html
    capturado.clear()
    E.barra_lateral_nav("Ventas", "supervisor")
    assert "Rentabilidad" not in capturado[0] and "Control tower" not in capturado[0]


def test_la_tarjeta_escapa_el_signo_pesos_y_el_html(monkeypatch):
    capturado = []
    monkeypatch.setattr(E.st, "markdown", lambda html, **kw: capturado.append(html))
    E.tarjeta_kpi("Venta <b>", "$ 1.000", "vs. $ 2", tono="verde", ayuda="tip $")
    html = capturado[0]
    assert "$" not in html and "&#36; 1.000" in html and "&lt;b&gt;" in html and "pj-kpi verde" in html
    E.tarjeta_kpi("x", "1", tono="inventado")
    assert "pj-kpi azul" in capturado[1]


def test_cartel_de_datos_verde_ambar_y_sin_dato():
    from datetime import datetime, timedelta, timezone
    ahora = datetime.now(timezone.utc)
    fresco = E.cartel_datos_html({"written_at": ahora.isoformat(timespec="seconds")})
    viejo = E.cartel_datos_html({"written_at": (ahora - timedelta(hours=30)).isoformat(timespec="seconds")})
    assert "Datos al:" in fresco and "viejo" not in fresco
    assert "pj-datos viejo" in viejo and "más de un día" in viejo
    assert "sin dato" in E.cartel_datos_html(None) and "sin dato" in E.cartel_datos_html({"written_at": "x"})
