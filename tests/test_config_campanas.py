"""Campañas de Mis Ventas y líneas de Club Faro editables por bimestre."""
from datetime import date

import pandas as pd
import pytest

from sigma_conn import config_campanas as CS
from sigma_conn import config_objetivos as CO

HOY = date(2026, 10, 9)          # bimestre en curso: sep-oct (clave 2026-09)


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setattr(CS, "vendedores_con_escala", lambda mes=None: ["101", "102", "103"])
    return CS.CampanasStore(tmp_path / "config")


def _mv_def():
    return {"catalogo": {"DOVE": {"nombre": "Dove 180 ml", "tipos": ["COBERTURA", "VOLUMEN"]}},
            "articulos": {"DOVE": ["10", "11"]},
            "objetivos": [{"clave": "DOVE", "tipo": "VOLUMEN", "vendedor_id": "101", "valor": 50},
                          {"clave": "DOVE", "tipo": "COBERTURA", "vendedor_id": "101", "valor": 20}]}


def _cf_def():
    return {"catalogo": {"SMIRNOFF": {"nombre": "K+T · Smirnoff", "tipo_cliente": "TRAD", "modo": "clientes"}},
            "articulos": {"SMIRNOFF": ["1"]}, "objetivos": [{"clave": "SMIRNOFF", "tipo": "", "vendedor_id": "102", "valor": 30}]}


def _semilla_mv():
    obj = pd.DataFrame([{"campana": "DOVE_180ML", "tipo": "VOLUMEN", "vendedor_id": "101", "target": 40.0, "periodo": "2026-09/2026-10"}])
    art = pd.DataFrame([{"articulo_id": "10", "campana": "DOVE_180ML", "incluir": True},
                        {"articulo_id": "99", "campana": "DOVE_180ML", "incluir": False}])
    return obj, art


def test_slug():
    assert CS.slug("Dove 180 ml") == "DOVE_180_ML" and CS.slug("  Línea Ñandú!! ") == "LINEA_NANDU"


def test_bimestre_nuevo_arranca_vacio_sin_heredar(st):
    st.guardar("mamaya", "mis_ventas", "2026-09", _mv_def(), hoy=HOY)
    d, origen, _ = st.vigente("mis_ventas", "2026-11", None)
    assert origen == "vacia" and d["catalogo"] == {}
    d, origen, _ = st.vigente("mis_ventas", "2026-09", None)
    assert origen == "propia" and d["articulos"]["DOVE"] == ["10", "11"]


def test_semilla_del_excel_solo_si_es_del_mismo_bimestre(st):
    sem = CS.semilla_mis_ventas(*_semilla_mv())
    d, origen, _ = st.vigente("mis_ventas", "2026-09", sem)
    assert origen == "excel" and d["articulos"] == {"DOVE_180ML": ["10"]}          # el artículo con N no está
    assert d["catalogo"]["DOVE_180ML"]["nombre"] == "Dove 180 ml" and d["catalogo"]["DOVE_180ML"]["tipos"] == ["VOLUMEN"]
    assert st.vigente("mis_ventas", "2026-11", sem)[1] == "vacia"


def test_editar_el_excel_crea_definicion_propia_con_historial(st):
    sem = CS.semilla_mis_ventas(*_semilla_mv())
    d, _, _ = st.vigente("mis_ventas", "2026-09", sem)
    d = {**d, "articulos": {"DOVE_180ML": ["10", "12"]}}
    st.guardar("nbuldurini", "mis_ventas", "2026-09", d, sem, "se suma el 12", hoy=HOY)
    assert st.vigente("mis_ventas", "2026-09", sem)[1] == "propia"
    r = st.historial("mis_ventas")[0]
    assert r["actor"] == "nbuldurini" and r["motivo"] == "se suma el 12"
    assert any("Artículos agregados" in c["campo"] and c["despues"] == "12" for c in r["cambios"])


def test_cerrado_choque_y_sin_cambios(st):
    with pytest.raises(CO.ConfigError, match="cerrado"):
        st.guardar("x", "mis_ventas", "2026-07", _mv_def(), hoy=HOY)
    v = st.version()
    st.guardar("a", "mis_ventas", "2026-09", _mv_def(), version_base=v, hoy=HOY)
    otro = _mv_def()
    otro["articulos"]["DOVE"] = ["10"]
    with pytest.raises(CO.ConflictoError):
        st.guardar("b", "mis_ventas", "2026-09", otro, version_base=v, hoy=HOY)
    with pytest.raises(CO.ConfigError, match="No hay cambios"):
        st.guardar("a", "mis_ventas", "2026-09", _mv_def(), hoy=HOY)


def test_validaciones(st):
    d = _mv_def()
    d["objetivos"][0]["vendedor_id"] = "999"
    with pytest.raises(CO.ConfigError, match="999"):
        st.guardar("x", "mis_ventas", "2026-09", d, hoy=HOY)           # vendedor que no está en SIGMA / escala
    d = _mv_def()
    d["catalogo"]["DOVE"]["tipos"] = []
    with pytest.raises(CO.ConfigError, match="tipo"):
        st.guardar("x", "mis_ventas", "2026-09", d, hoy=HOY)
    d = _mv_def()
    d["catalogo"]["OTRA"] = {"nombre": "dove 180 ML", "tipos": ["VOLUMEN"]}
    with pytest.raises(CO.ConfigError, match="repetido"):
        st.guardar("x", "mis_ventas", "2026-09", d, hoy=HOY)
    d = _mv_def()
    d["objetivos"][0]["valor"] = -3
    with pytest.raises(CO.ConfigError, match="negativos"):
        st.guardar("x", "mis_ventas", "2026-09", d, hoy=HOY)
    d = _mv_def()
    d["articulos"]["NOEXISTE"] = ["1"]
    with pytest.raises(CO.ConfigError, match="no existe"):
        st.guardar("x", "mis_ventas", "2026-09", d, hoy=HOY)
    d = _cf_def()
    d["catalogo"]["SMIRNOFF"]["modo"] = "otro"
    with pytest.raises(CO.ConfigError, match="modo"):
        st.guardar("x", "club_faro", "2026-09", d, hoy=HOY)


def test_campana_nueva_en_el_bimestre_siguiente_y_descartar(st):
    st.guardar("x", "club_faro", "2026-11", {"catalogo": {"NUEVA": {"nombre": "AS · Nueva", "tipo_cliente": "AS", "modo": "cliente_sku"}},
                                             "articulos": {"NUEVA": ["5", "6"]},
                                             "objetivos": [{"clave": "NUEVA", "tipo": "", "vendedor_id": "103", "valor": 12}]}, hoy=HOY)
    d, origen, _ = st.vigente("club_faro", "2026-11", None)
    assert origen == "propia" and d["catalogo"]["NUEVA"]["modo"] == "cliente_sku"
    st.descartar("x", "club_faro", "2026-11", hoy=HOY)
    assert st.vigente("club_faro", "2026-11", None)[1] == "vacia"
    assert st.historial("club_faro")[0]["tipo"] == "descarte"


def test_copiar_del_bimestre_anterior(st):
    st.guardar("x", "club_faro", "2026-09", _cf_def(), hoy=HOY)
    previo, _, _ = st.vigente("club_faro", CS.bimestre_anterior("2026-11"), None)
    st.guardar("x", "club_faro", "2026-11", previo, hoy=HOY, copia=True)
    assert st.vigente("club_faro", "2026-11", None)[0]["articulos"] == {"SMIRNOFF": ["1"]}
    assert st.historial("club_faro")[0]["tipo"] == "copia"
    assert CS.bimestre_anterior("2027-01") == "2026-11"


def test_conversion_a_tablas_que_leen_los_tableros():
    obj, art, nombres = CS.a_tablas_mis_ventas(_mv_def(), "2026-09")
    assert set(obj["tipo"]) == {"VOLUMEN", "COBERTURA"} and nombres == {"DOVE": "Dove 180 ml"}
    assert obj["periodo"].iloc[0] == "2026-09/2026-10" and set(art["articulo_id"]) == {"10", "11"} and art["incluir"].all()
    obj, art, lineas = CS.a_tablas_club_faro(_cf_def(), "2026-09")
    assert lineas["SMIRNOFF"] == {"nombre": "K+T · Smirnoff", "tipo_cliente": "TRAD", "modo": "clientes"}
    assert obj.loc[0, "linea"] == "SMIRNOFF" and obj.loc[0, "objetivo"] == 30 and obj.loc[0, "tipo_cliente"] == "TRAD"


def test_tablas_vigentes_excel_propia_y_vacia(tmp_path, monkeypatch):
    monkeypatch.setattr(CS, "vendedores_con_escala", lambda mes=None: ["101"])
    s = CS.CampanasStore(tmp_path / "config")
    bo, ba = _semilla_mv()
    obj, art, nombres = CS.tablas_vigentes("mis_ventas", date(2026, 9, 1), bo, ba, s)
    assert obj is bo and nombres == {"DOVE_180ML": "Dove 180 ml"}                       # rige el Excel
    s.guardar("x", "mis_ventas", "2026-09", _mv_def(), CS.semilla_mis_ventas(bo, ba), hoy=HOY)
    obj, art, nombres = CS.tablas_vigentes("mis_ventas", date(2026, 9, 1), bo, ba, s)
    assert nombres == {"DOVE": "Dove 180 ml"} and len(obj) == 2
    obj, art, nombres = CS.tablas_vigentes("mis_ventas", date(2026, 11, 1), bo, ba, s)
    assert obj.empty and nombres == {}                                                  # bimestre nuevo: vacío


def test_copiar_conserva_vendedores_sin_escala_pero_editar_no_los_suma(st):
    d = _cf_def()
    d["objetivos"].append({"clave": "SMIRNOFF", "tipo": "", "vendedor_id": "126", "valor": 5})
    sem = ("2026-09/2026-10", d)                                  # el Excel trae un vendedor (126) que no está en la escala
    previo, _, _ = st.vigente("club_faro", "2026-09", sem)
    st.guardar("x", "club_faro", "2026-11", previo, hoy=HOY, copia=True)
    assert any(o["vendedor_id"] == "126" for o in st.vigente("club_faro", "2026-11", None)[0]["objetivos"])
    otro = _cf_def()
    otro["objetivos"].append({"clave": "SMIRNOFF", "tipo": "", "vendedor_id": "126", "valor": 5})
    with pytest.raises(CO.ConfigError, match="126"):
        st.guardar("x", "club_faro", "2027-01", otro, hoy=HOY)        # sin copia, sumar un vendedor fuera de la escala se rechaza


# ----------------------------------------------------------------------------- 11 Titulares
def _t_def():
    return {"catalogo": {"ALMA_MORA": {"nombre": "Alma Mora", "objetivo": 351, "propia": False},
                         "ELEMENTOS": {"nombre": "Elementos", "objetivo": 0, "propia": True}},
            "articulos": {"ALMA_MORA": ["7", "8"]}, "objetivos": [],
            "canales": {"Autoservicios": 66, "Tradicionales": 362, "OP & VTK": 90},
            "subcanales": {"On Premise": 0, "On Premise Noche": 0, "Vinotecas": 56, "Tienda de Bebidas": 34, "Catering": 0}}


def test_titulares_guarda_lineas_canales_y_los_valida(st):
    st.guardar("x", "titulares", "2026-11", _t_def(), hoy=HOY)
    d, origen, _ = st.vigente("titulares", "2026-11", None)
    assert origen == "propia" and d["canales"]["Tradicionales"] == 362 and d["catalogo"]["ELEMENTOS"]["propia"] is True
    nuevo = _t_def()
    nuevo["canales"]["Tradicionales"] = 400
    nuevo["catalogo"]["ALMA_MORA"]["objetivo"] = 300
    st.guardar("x", "titulares", "2026-11", nuevo, hoy=HOY)
    campos = [c["campo"] for c in st.historial("titulares")[0]["cambios"]]
    assert "Objetivo canal «Tradicionales»" in campos and "Datos de «Alma Mora»" in campos
    malo = _t_def()
    malo["canales"]["Inventado"] = 5
    with pytest.raises(CO.ConfigError, match="desconocido"):
        st.guardar("x", "titulares", "2026-11", malo, hoy=HOY)
    malo = _t_def()
    malo["catalogo"]["ALMA_MORA"]["objetivo"] = -1
    with pytest.raises(CO.ConfigError, match="negativos"):
        st.guardar("x", "titulares", "2026-11", malo, hoy=HOY)


def test_titulares_semilla_y_tablas_vigentes(tmp_path, monkeypatch):
    monkeypatch.setattr(CS, "vendedores_con_escala", lambda mes=None: ["101"])
    s = CS.CampanasStore(tmp_path / "config")
    art = pd.DataFrame([{"linea": "ALMA_MORA", "articulo_id": "7", "incluir": True, "fuente": "INCLUIR", "periodo": "2026-09/2026-10"},
                        {"linea": "ALMA_MORA", "articulo_id": "9", "incluir": False, "fuente": "INCLUIR", "periodo": "2026-09/2026-10"}])
    a, lineas, oc, os_ = CS.titulares_vigentes(date(2026, 9, 1), art, s)
    assert a is art and lineas["ALMA_MORA"]["objetivo"] == 351 and oc["Tradicionales"] == 362      # rige el Excel + negocio.py
    a, lineas, oc, os_ = CS.titulares_vigentes(date(2026, 11, 1), art, s)
    assert a is art or a.empty
    assert lineas == {} and a.empty                                                               # bimestre nuevo: vacío
    s.guardar("x", "titulares", "2026-11", _t_def(), hoy=HOY)
    a, lineas, oc, os_ = CS.titulares_vigentes(date(2026, 11, 1), art, s)
    assert set(a["articulo_id"]) == {"7", "8"} and lineas["ELEMENTOS"]["propia"] and oc["OP & VTK"] == 90 and os_["Vinotecas"] == 56


# ----------------------------------------------------------------------------- Cobertura: artículos por categoría
def test_cobertura_excepciones_se_guardan_y_validan(st):
    st.guardar("x", "cobertura", "2026-09", {"excepciones": {"123": "FOOD", "456": "NINGUNA"}}, hoy=HOY)
    assert CS.excepciones_cobertura(date(2026, 9, 1), st) == {"123": "FOOD", "456": "NINGUNA"}
    assert CS.excepciones_cobertura(date(2026, 11, 1), st) == {}                      # no hereda: bimestre nuevo = regla automática
    with pytest.raises(CO.ConfigError, match="Categoría inválida"):
        st.guardar("x", "cobertura", "2026-09", {"excepciones": {"9": "XYZ"}}, hoy=HOY)
    r = st.historial("cobertura")[0]
    assert {c["campo"] for c in r["cambios"]} == {"Categoría de cobertura del artículo 123", "Categoría de cobertura del artículo 456"}


def test_categoria_efectiva_aplica_las_excepciones():
    base = pd.Series({"1": "BPC", "2": "HC", "3": None}, dtype="object")
    ef = CS.categoria_efectiva(base, {"1": "FOOD", "2": "NINGUNA", "3": "HC"})
    assert ef["1"] == "FOOD" and ef["2"] is None and ef["3"] == "HC"
    assert base["1"] == "BPC"                                                          # no modifica la original


def test_categoria_efectiva_con_dtype_string_y_na():
    base = pd.Series(["BPC", None, "HC"], index=["1", "2", "3"], dtype="string")      # como viene de dim_articulo
    ef = CS.categoria_efectiva(base, {"1": "NINGUNA"})
    assert ef["2"] is None and ef["1"] is None and ef["3"] == "HC"
    assert [a for a, c in ef.items() if isinstance(c, str) and c == "HC"] == ["3"]
