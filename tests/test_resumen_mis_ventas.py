"""Resumen de Mis Ventas por vendedor (objetivo, avance, proyectado y porcentajes), una tabla por tipo."""
import pandas as pd
import pytest

from sigma_conn import tableros as TB


def _mv(esperado=0.5):
    filas = [
        # vendedor 101: dos campañas de cobertura y una de volumen
        ("101", "ANA", "DOVE", "COBERTURA", 10, 20),
        ("101", "ANA", "VIM", "COBERTURA", 5, 10),
        ("101", "ANA", "DOVE", "VOLUMEN", 100, 400),
        # vendedor 102: solo cobertura, sin avance
        ("102", "BETO", "DOVE", "COBERTURA", 0, 8),
    ]
    return pd.DataFrame([{"vendedor_id": v, "vendedor": n, "campana": c, "tipo": t, "logrado": lg, "target": ob,
                          "esperado_pct": esperado} for v, n, c, t, lg, ob in filas])


def test_cobertura_suma_campanas_y_proyecta():
    r = TB.resumen_mis_ventas(_mv(), "COBERTURA").set_index("vendedor_id")
    a = r.loc["101"]
    assert a["objetivo"] == 30 and a["avance"] == 15
    assert a["pct_avance"] == pytest.approx(0.5)
    assert a["proyectado"] == pytest.approx(30)                # 10/0,5 + 5/0,5
    assert a["pct_proyeccion"] == pytest.approx(1.0)
    assert a["media_necesaria"] == pytest.approx(a["pct_avance"])   # definición de Juan: avance ÷ objetivo
    b = r.loc["102"]
    assert b["avance"] == 0 and b["proyectado"] == 0 and b["pct_avance"] == 0


def test_volumen_va_en_su_propia_tabla():
    r = TB.resumen_mis_ventas(_mv(), "VOLUMEN")
    assert list(r["vendedor_id"]) == ["101"]
    assert r.iloc[0]["objetivo"] == 400 and r.iloc[0]["avance"] == 100 and r.iloc[0]["proyectado"] == pytest.approx(200)


def test_sin_avance_esperado_no_proyecta_de_mas():
    r = TB.resumen_mis_ventas(_mv(esperado=0.0), "COBERTURA").set_index("vendedor_id")
    assert r.loc["101"]["proyectado"] == 15            # primer día: se queda con lo logrado


def test_acepta_la_tabla_del_vendedor_con_columna_objetivo_y_tipo_vacio():
    mv = _mv().rename(columns={"target": "objetivo"})
    assert TB.resumen_mis_ventas(mv, "COBERTURA").set_index("vendedor_id").loc["101"]["objetivo"] == 30
    assert TB.resumen_mis_ventas(mv[mv["tipo"] == "COBERTURA"], "VOLUMEN").empty


def test_objetivo_cero_da_nan_en_los_porcentajes():
    mv = _mv(); mv.loc[3, "target"] = 0
    r = TB.resumen_mis_ventas(mv, "COBERTURA").set_index("vendedor_id")
    assert pd.isna(r.loc["102"]["pct_avance"]) and pd.isna(r.loc["102"]["pct_proyeccion"])
