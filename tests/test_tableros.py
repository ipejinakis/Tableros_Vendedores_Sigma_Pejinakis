from datetime import date

import pandas as pd
import pytest

from sigma_conn import negocio as N
from sigma_conn import objetivos as O
from sigma_conn import tableros as TB
from sigma_conn import transform as T
from sigma_conn.store import Store


def av(fid, art, cant, precio, vend="100", fecha="2026-09-14", tipo="F", pedido_datos=None, desc=0):
    return {"id": fid, "fecha": fecha, "comprobanteCodigo": "FA13", "comprobanteNumero": "0001",
            "comprobanteTipo": tipo, "motivoNc": None, "ajustaComprobanteId": None, "empresa": "0001",
            "surcursal": "0001", "vendedor": vend, "clienteId": "100762", "reparto": None, "item": 1,
            "itemArticuloId": art, "itemDescripcion": "X", "itemRubroCodigo": "1", "itemRubroDescripcion": "R",
            "itemLineaCodigo": "1", "itemLinea": "L", "itemDivisionCodigo": "1", "itemDivision": "D",
            "itemCantidad": cant, "itemPrecioUnitario": precio, "itemDescuento": desc,
            "itemDescuentoGlobal": 0, "itemDescuentoFinanciero": 0, "costoUltimaCompra": 10.0,
            "costoPromedioPonderado": 10.0, "itemPedidoId": None, "itemPedidoDatosAdicionales": pedido_datos}


def fa(fid, estado="pagada", tipo="F", fecha="2026-09-14", vend="100"):
    return {"id": fid, "fecha": fecha, "comprobanteCodigo": "FA13", "comprobanteNumero": "0001",
            "comprobanteTipo": tipo, "empresa": "0001", "sucursal": "0001", "vendedor": vend,
            "clienteId": "100762", "estado": estado, "pendientePago": 0, "subtotal": 1, "totalComprobante": 1}


API = '{"canal":"api","API_ID":"1"}'
MAGENTO = '{"DISTCODE":"1","MAGENTOID":"9","TIPOENVIO":"delivery"}'
U = "UNILEVER DE ARGENTINA SA"

ART = pd.DataFrame({
    "articulo_id": ["A", "FIN", "MOR", "HEL"],
    "proveedor": [U, "DEPOSITO SALTA", "DEPOSITO MORILLO", U],
    "division": ["HC", None, None, "VARIOS"],
})
VEND = pd.DataFrame({"vendedor_id": ["100", "101", "124"], "nombre": ["GONZALBES MIGUEL", "ARIAS DANIEL", "GERENCIA SALTA"]})


def _ventas():
    rows = [
        av(1, "A", 10, 1_000_000, vend="100", pedido_datos=API),        # 10 M$ Axum
        av(2, "A", 5, 1_000_000, vend="100", pedido_datos=MAGENTO, fecha="2026-09-15"),   # 5 M$ Compre Ahora
        av(3, "FIN", 1, 200_000, vend="100", fecha="2026-09-16"),       # Depósito Salta cuenta (directa)
        av(4, "MOR", 1, 999_999_999, vend="100"),                       # Morillo: afuera
        av(5, "HEL", 1, 999_999_999, vend="100"),                       # heladera Unilever: afuera
        av(6, "A", -1, 1_000_000, vend="100", tipo="NC", fecha="2026-09-16"),   # NC resta 1 M$ (directa)
        av(7, "A", 60, 1_000_000, vend="101", pedido_datos=API),        # 60 M$ -> escalón 2 General
        av(8, "A", 3, 1_000_000, vend="124", pedido_datos=API),         # sin escala de preventa
        av(9, "A", 100, 1_000_000, vend="100", fecha="2026-09-28"),     # posterior al corte
        av(10, "A", 7, 1_000_000, vend="101", pedido_datos=API),        # anulada
    ]
    facs = [fa(1), fa(2, fecha="2026-09-15"), fa(3, fecha="2026-09-16"), fa(4), fa(5),
            fa(6, tipo="NC", fecha="2026-09-16"), fa(7, vend="101"), fa(8, vend="124"),
            fa(9, fecha="2026-09-28"), fa(10, estado="anulada", vend="101")]
    return T.build_fact_ventas(rows, facs)


def test_canal_de_origen():
    assert [TB.canal_de_origen(o) for o in ("api", "magento", "directa", "otro", None)] == \
        ["Axum", "Compre Ahora", "Directa", "Otro", "Otro"]


def test_facturacion_vendedores_aplica_las_reglas_de_objetivos():
    tabla, res = TB.facturacion_vendedores(_ventas(), ART, VEND, date(2026, 9, 20))
    t = tabla.set_index("vendedor_id")
    # vendedor 100 (AASS): 10 + 5 (Axum, Compre Ahora) + 0,2 (Depósito Salta) - 1 (NC) = 14,2 M$; Morillo, heladera y
    # lo posterior al corte no cuentan
    assert t.loc["100", "vendido"] == pytest.approx(14_200_000)
    assert t.loc["100", "Axum"] == pytest.approx(10_000_000) and t.loc["100", "Compre Ahora"] == pytest.approx(5_000_000)
    assert t.loc["100", "Directa"] == pytest.approx(200_000 - 1_000_000)
    assert t.loc["100", "perfil"] == "AASS" and t.loc["100", "escalon"] == 0 and t.loc["100", "premio"] == 0
    assert t.loc["100", "vendedor"] == "GONZALBES MIGUEL" and t.loc["100", "supervisor"] == "AMAYA MAURO"
    # vendedor 101 (GENERAL): 60 M$ (la factura anulada no cuenta) -> escalón 2, premio 400.000 $
    assert t.loc["101", "vendido"] == pytest.approx(60_000_000)
    assert t.loc["101", "escalon"] == 2 and t.loc["101", "premio"] == 400_000
    assert t.loc["101", "siguiente_escalon"] == 3 and t.loc["101", "faltante_siguiente"] == pytest.approx(12_000_000)


def test_tabla_trae_todos_los_vendedores_con_escala_aunque_no_hayan_vendido():
    tabla, res = TB.facturacion_vendedores(_ventas(), ART, VEND, date(2026, 9, 20))
    assert len(tabla) == 14 and res["vendedores"] == 14
    cero = tabla.set_index("vendedor_id").loc["119"]
    assert cero["vendido"] == 0 and cero["escalon"] == 0 and cero["avance_esc1"] == 0


def test_resumen_separa_los_vendedores_sin_escala_y_cierra_el_total():
    tabla, res = TB.facturacion_vendedores(_ventas(), ART, VEND, date(2026, 9, 20))
    assert res["total_con_escala"] == pytest.approx(14_200_000 + 60_000_000)
    assert res["total_sin_escala"] == pytest.approx(3_000_000)
    assert res["total_empresa"] == pytest.approx(res["total_con_escala"] + res["total_sin_escala"])
    assert list(res["sin_escala"]["vendedor_id"]) == ["124"] and res["sin_escala"].loc[0, "vendedor"] == "GERENCIA SALTA"
    assert sum(res["por_canal_empresa"].values()) == pytest.approx(res["total_empresa"])
    assert res["con_escalon"] == 1 and res["premio_alcanzado"] == 400_000


def test_el_corte_cambia_lo_vendido_y_los_dias():
    t1, r1 = TB.facturacion_vendedores(_ventas(), ART, VEND, date(2026, 9, 20))
    t2, r2 = TB.facturacion_vendedores(_ventas(), ART, VEND, date(2026, 9, 28))
    assert r2["total_con_escala"] == pytest.approx(r1["total_con_escala"] + 100_000_000)
    assert r1["dias_transcurridos"] == 17 and r1["dias_restantes"] == 9
    assert r2["dias_transcurridos"] == 24 and r2["dias_restantes"] == 2


def test_ventas_vacias_no_rompen():
    vacio = _ventas().iloc[0:0]
    tabla, res = TB.facturacion_vendedores(vacio, ART, VEND, date(2026, 9, 20))
    assert len(tabla) == 14 and tabla["vendido"].sum() == 0 and res["total_empresa"] == 0
    assert res["sin_escala"].empty


def test_store_meses_y_ultimo_dia(tmp_path):
    import os
    st = Store(tmp_path / "data", "csv")
    v = _ventas()
    st.upsert_window("fact_ventas_item", v, date(2026, 9, 1), date(2026, 9, 30))
    previo = {k: os.environ.get(k) for k in ("SIGMA_DATA_DIR", "SIGMA_STORE_FORMAT")}
    os.environ["SIGMA_DATA_DIR"], os.environ["SIGMA_STORE_FORMAT"] = str(tmp_path / "data"), "csv"
    try:
        abierto = TB.abrir_store()
        assert TB.meses_disponibles(abierto) == ["2026-09"]
        mes = TB.cargar_ventas_mes(abierto, "2026-09")
        assert len(mes) == len(v) and TB.ultimo_dia_con_ventas(mes) == date(2026, 9, 28)
    finally:
        for k, val in previo.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val


def test_formatos_es_ar():
    assert TB.fmt_pesos(1234567.4) == "$ 1.234.567" and TB.fmt_pesos(None) == "—"
    assert TB.fmt_millones(48_260_000) == "48,3 M$" and TB.fmt_millones(1_234_000_000) == "1.234,0 M$"


def test_estado_facturacion_semaforo():
    corte = date(2026, 9, 28)
    ev = lambda vendido: O.evaluar_facturacion(vendido, N.PERFIL_GENERAL, corte)
    assert TB.estado_facturacion(ev(55_000_000)) == "verde"      # ya pasó el escalón 1 (50 M$)
    assert TB.estado_facturacion(ev(48_000_000)) == "amarillo"   # al ritmo llega a 52 M$
    assert TB.estado_facturacion(ev(20_000_000)) == "rojo"
    assert set(TB.ESTADO_TXT) == set(TB.ESTADO_COLOR) - {"sin_objetivo"} == {"verde", "amarillo", "rojo"}


def test_tabla_y_resumen_traen_el_estado():
    tabla, res = TB.facturacion_vendedores(_ventas(), ART, VEND, date(2026, 9, 20))
    t = tabla.set_index("vendedor_id")
    assert t.loc["101", "estado"] == "verde" and t.loc["101", "estado_txt"] == TB.ESTADO_TXT["verde"]
    assert t.loc["100", "estado"] == "rojo"
    assert sum(res["por_estado"].values()) == 14 and res["por_estado"]["verde"] == 1


def test_ritmo_mes_acumulado_y_rutas():
    corte = date(2026, 9, 20)
    r = TB.ritmo_mes(_ventas(), ART, corte, ["101"])
    assert len(r) == 30 and r["fecha"].iloc[0] == pd.Timestamp("2026-09-01")
    assert r.set_index("fecha").loc["2026-09-20", "acumulado"] == pytest.approx(60_000_000)
    assert r.set_index("fecha")["acumulado"].iloc[20:].isna().all()          # después del corte no hay dato
    assert r["esc1"].iloc[-1] == pytest.approx(50_000_000) and r["esc3"].iloc[-1] == pytest.approx(72_000_000)
    assert r["esc1"].iloc[0] == pytest.approx(50_000_000 / 26)               # 1 de 26 días de venta
    todos = TB.ritmo_mes(_ventas(), ART, corte)
    assert todos.set_index("fecha").loc["2026-09-20", "acumulado"] == pytest.approx(14_200_000 + 60_000_000)
    sin_escala = TB.ritmo_mes(_ventas(), ART, corte, ["124"])        # sin escala de preventa: no hay ruta ni acumulado
    assert sin_escala["esc1"].iloc[-1] == 0 and sin_escala["acumulado"].dropna().eq(0).all()


# ----------------------------------------------------------------------------- cobertura
ART_COB = pd.DataFrame({
    "articulo_id": ["B1", "F1", "H1", "CMB", "SIN", "MOR"],
    "proveedor": [U, U, U, U, U, "DEPOSITO MORILLO"],
    "division": ["PC", "NUTRITION", "HC", None, None, None],
    "categoria_cobertura": ["BPC", "FOOD", "HC", "FOOD", "COMBO_SIN_ASIGNAR", None],
})


def _ventas_cob():
    def it(fid, art, cli, vend="101", fecha="2026-09-10", cant=1, tipo="F"):
        r = av(fid, art, cant, 1000, vend=vend, fecha=fecha, tipo=tipo)
        r["clienteId"] = cli
        return r
    rows = [it(1, "B1", "c1"), it(2, "B1", "c1"), it(3, "B1", "c2"), it(4, "F1", "c1"), it(5, "CMB", "c3"),
            it(6, "SIN", "c4"), it(7, "MOR", "c5"), it(8, "B1", "c6", cant=-1, tipo="C"), it(9, "B1", "c7"),
            it(10, "B1", "c8", vend="100"), it(11, "B1", "c9", fecha="2026-09-25")]
    facs = [fa(r["id"], tipo=r["comprobanteTipo"], fecha=r["fecha"], vend=r["vendedor"]) for r in rows]
    facs[8]["estado"] = "anulada"
    return T.build_fact_ventas(rows, facs)


def _obj_cob():
    filas = []
    for vid, grupo in (("101", "PREVENTA"), ("100", "AASS")):
        for cat, obj in (("BPC", 10.0), ("FOOD", 5.0), ("HC", 4.0)):
            filas.append({"vendedor_id": vid, "categoria": cat, "grupo": grupo, "objetivo": obj,
                          "total_distribuidora": {"BPC": 100.0, "FOOD": 50.0, "HC": 40.0}[cat], "periodo": "2026-09/2026-10"})
    return pd.DataFrame(filas)


def test_bimestre_de():
    assert TB.bimestre_de("2026-10") == TB.bimestre_de("2026-09") == (date(2026, 9, 1), date(2026, 10, 31))
    assert TB.bimestre_de("2026-04") == (date(2026, 3, 1), date(2026, 4, 30))


def test_estado_avance_semaforo():
    assert TB.estado_avance(0.5, 0.5) == "verde" and TB.estado_avance(1.0, 0.9) == "verde"
    assert TB.estado_avance(0.45, 0.5) == "amarillo" and TB.estado_avance(0.39, 0.5) == "rojo"
    assert TB.estado_avance(0.0, 0.0) == "verde"           # primer día: nadie va atrasado


def test_fraccion_esperada_por_dias_de_venta():
    ini, fin = date(2026, 9, 1), date(2026, 10, 31)
    assert TB.fraccion_esperada(ini, fin, date(2026, 9, 20)) == pytest.approx(17 / 53)   # 17 de 53 días de venta
    assert TB.fraccion_esperada(ini, fin, date(2026, 11, 15)) == 1.0


def test_clientes_con_compra_reglas():
    cc = TB.clientes_con_compra(_ventas_cob(), ART_COB, date(2026, 9, 1), date(2026, 9, 20))
    c101 = cc[cc["vendedor_id"] == "101"]
    # BPC: c1 y c2 (c1 repetido cuenta una vez; la NC c6, la anulada c7 y lo posterior al corte c9 no cuentan)
    assert sorted(c101.loc[c101.categoria == "BPC", "cliente_id"]) == ["c1", "c2"]
    # FOOD: c1 (F1) y c3 (combo asignado a FOOD); el combo sin asignar (c4) y Morillo (c5) no cuentan
    assert sorted(c101.loc[c101.categoria == "FOOD", "cliente_id"]) == ["c1", "c3"]
    assert c101[c101.categoria == "HC"].empty


def test_cobertura_vendedores_tabla_y_resumen():
    tabla, res = TB.cobertura_vendedores(_ventas_cob(), ART_COB, VEND, _obj_cob(),
                                         date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    t = tabla.set_index(["vendedor_id", "categoria"])
    assert len(tabla) == 6                                    # aparecen aunque no tengan clientes (101/HC)
    assert t.loc[("101", "BPC"), "clientes"] == 2 and t.loc[("101", "BPC"), "avance"] == pytest.approx(0.2)
    assert t.loc[("101", "BPC"), "estado"] == "rojo"          # 20 % contra 32 % esperado
    assert t.loc[("101", "FOOD"), "estado"] == "verde"        # 40 % >= 32 %
    assert t.loc[("101", "HC"), "clientes"] == 0 and t.loc[("101", "HC"), "faltan"] == 4
    assert t.loc[("100", "BPC"), "clientes"] == 1 and t.loc[("101", "BPC"), "vendedor"] == "ARIAS DANIEL"
    # toda la distribuidora: BPC = c1, c2, c8 distintos = 3 de 100; FOOD = c1, c3 = 2 de 50
    assert res["por_categoria"]["BPC"]["clientes"] == 3 and res["por_categoria"]["BPC"]["objetivo"] == 100
    assert res["por_categoria"]["FOOD"]["clientes"] == 2
    assert res["esperado_pct"] == pytest.approx(17 / 53) and res["periodo"] == "2026-09/2026-10"


# ----------------------------------------------------------------------------- Mis Ventas
def test_mis_ventas_cobertura_y_volumen_por_campana():
    art = pd.DataFrame({"articulo_id": ["D1", "D2", "H1", "H2", "X"], "proveedor": [U] * 5,
                        "division": ["PC", "PC", "NUTRITION", "NUTRITION", "HC"],
                        "categoria_cobertura": ["BPC", "BPC", "FOOD", "FOOD", "HC"]})

    def it(fid, art_, cli, cant, vend="101", fecha="2026-09-10", tipo="F"):
        r = av(fid, art_, cant, 1000, vend=vend, fecha=fecha, tipo=tipo)
        r["clienteId"] = cli
        return r
    rows = [it(1, "D1", "c1", 2), it(2, "D2", "c1", 1), it(3, "D1", "c2", 1),          # Dove: c1 y c2 -> 2 clientes
            it(4, "H1", "c1", 10), it(5, "H2", "c3", 6), it(6, "H1", "c1", -4, tipo="C"),   # Hellmann's: 10 + 6 - 4 = 12 u.
            it(7, "X", "c9", 50),                                                      # fuera de campañas
            it(8, "D1", "c7", 1, fecha="2026-09-25")]                                  # posterior al corte
    facs = [fa(r["id"], tipo=r["comprobanteTipo"], fecha=r["fecha"], vend=r["vendedor"]) for r in rows]
    ventas = T.build_fact_ventas(rows, facs)
    cfg = pd.DataFrame({"articulo_id": ["D1", "D2", "H1", "H2", "X"], "campana": ["DOVE_180ML", "DOVE_180ML",
                        "HELLMANNS_SAB_LIV", "HELLMANNS_SAB_LIV", "REXONA_AERO"], "incluir": [True, True, True, True, False]})
    obj = pd.DataFrame({"vendedor_id": ["101", "101", "100"], "campana": ["DOVE_180ML", "HELLMANNS_SAB_LIV", "REXONA_AERO"],
                        "tipo": ["COBERTURA", "VOLUMEN", "VOLUMEN"], "target": [4.0, 24.0, 10.0]})
    t = TB.mis_ventas_vendedores(ventas, art, VEND, obj, cfg, date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    t = t.set_index(["vendedor_id", "campana"])
    assert t.loc[("101", "DOVE_180ML"), "logrado"] == 2 and t.loc[("101", "DOVE_180ML"), "avance"] == pytest.approx(0.5)
    assert t.loc[("101", "DOVE_180ML"), "estado"] == "verde"                      # 50 % >= 32 % esperado
    assert t.loc[("101", "HELLMANNS_SAB_LIV"), "logrado"] == 12 and t.loc[("101", "HELLMANNS_SAB_LIV"), "unidad"] == "unidades"
    assert t.loc[("101", "HELLMANNS_SAB_LIV"), "faltan"] == 12
    assert t.loc[("100", "REXONA_AERO"), "logrado"] == 0 and t.loc[("100", "REXONA_AERO"), "estado"] == "rojo"
    assert t.loc[("101", "DOVE_180ML"), "panel"] == "Dove 180 ml · cobertura (clientes)"
    assert t.loc[("101", "DOVE_180ML"), "vendedor"] == "ARIAS DANIEL"


# ----------------------------------------------------------------------------- Club Faro
PEN = "GRUPO PEÑAFLOR S.A"


def _club_faro_datos():
    art = pd.DataFrame({"articulo_id": ["S1", "S2", "SR", "BD1", "BD2", "F1", "OTRO"],
                        "proveedor": [PEN] * 6 + [U], "division": [None] * 7})
    cfg = pd.DataFrame({
        "linea": ["SMIRNOFF", "SMIRNOFF", "SMIRNOFF", "BLANCOS_DULCES", "BLANCOS_DULCES", "FRIZZE"],
        "articulo_id": ["S1", "S2", "SR", "BD1", "BD2", "F1"], "incluir": [True, True, False, True, True, True]})
    clientes = pd.DataFrame({"cliente_id": ["k1", "k2", "a1", "a2", "a3", "g1"], "rubro_cod": ["02", "03", "01", "98", "70", "12"]})

    def it(fid, art_, cli, cant=1, vend="101", fecha="2026-09-10", tipo="F"):
        r = av(fid, art_, cant, 1000, vend=vend, fecha=fecha, tipo=tipo)
        r["clienteId"] = cli
        return r
    rows = [
        it(1, "S1", "k1"), it(2, "S2", "k1"),            # Smirnoff: k1 cuenta UNA vez aunque compre 2 artículos
        it(3, "S1", "k2", cant=1),                       # k2 (almacén) con 1 unidad alcanza
        it(4, "S1", "a1"),                               # Smirnoff a un AS: no cuenta (la línea es K+T)
        it(5, "SR", "g1"),                               # artículo con INCLUIR = N: no cuenta
        it(6, "S1", "g1", fecha="2026-09-25"),           # posterior al corte
        it(7, "S1", "g1", cant=-1, tipo="C"),            # NC: no cuenta (ni resta)
        it(8, "BD1", "a1"), it(9, "BD2", "a1"),          # blancos dulces: a1 suma 2 (cada SKU suma 1)
        it(10, "BD1", "a2"),                             # a2 (AAS Gold = AS) suma 1
        it(11, "BD1", "k1"),                             # blanco dulce a un K+T: no cuenta
        it(12, "F1", "a3"), it(13, "F1", "a3"),          # Frizze: a3 (Cadena SAR = AS) cuenta una vez
        it(14, "OTRO", "a3"),                            # fuera de las líneas
        it(15, "S1", "k1", vend="100"),                  # k1 con otro vendedor: cuenta para ese vendedor
    ]
    facs = [fa(r["id"], tipo=r["comprobanteTipo"], fecha=r["fecha"], vend=r["vendedor"]) for r in rows]
    return T.build_fact_ventas(rows, facs), art, clientes, cfg


def _obj_club_faro():
    filas = []
    for vid, objs in (("101", {"SMIRNOFF": 29.0, "BLANCOS_DULCES": 3.0, "FRIZZE": 1.0}), ("100", {"SMIRNOFF": 1.0})):
        for linea, o in objs.items():
            filas.append({"vendedor_id": vid, "nombre_excel": "X", "supervisor_excel": "S", "linea": linea, "objetivo": o,
                          "tipo_cliente": N.CLUB_FARO_LINEAS[linea]["tipo_cliente"], "supuesto": False, "periodo": "2026-09/2026-10"})
    return pd.DataFrame(filas)


def test_tipo_cliente_por_rubro():
    assert [TB.tipo_cliente(r) for r in ("01", "98", "70", "02", "03", "12", "81", None)] == \
        ["AS", "AS", "AS", "TRAD", "TRAD", "TRAD", "TRAD", "TRAD"]


def test_club_faro_compras_reglas():
    ventas, art, clientes, cfg = _club_faro_datos()
    c = TB.club_faro_compras(ventas, art, clientes, cfg, date(2026, 9, 1), date(2026, 9, 20))
    c101 = c[c["vendedor_id"] == "101"]
    assert sorted(c101.loc[c101.linea == "SMIRNOFF", "cliente_id"].unique()) == ["k1", "k2"]
    assert len(c101[c101.linea == "BLANCOS_DULCES"]) == 3                      # (a1,BD1) (a1,BD2) (a2,BD1)
    assert sorted(c101.loc[c101.linea == "FRIZZE", "cliente_id"].unique()) == ["a3"]


def test_club_faro_articulos_equivalentes_cuentan_una_vez(monkeypatch):
    ventas, art, clientes, cfg = _club_faro_datos()
    monkeypatch.setattr(N, "CLUB_FARO_ARTICULO_EQUIVALENTE", {"BD2": "BD1"})   # BD2 = mismo producto que BD1
    c = TB.club_faro_compras(ventas, art, clientes, cfg, date(2026, 9, 1), date(2026, 9, 20))
    bd = c[(c["vendedor_id"] == "101") & (c.linea == "BLANCOS_DULCES")]
    assert len(bd) == 2 and sorted(bd["cliente_id"]) == ["a1", "a2"]            # a1 compró BD1 y BD2: suma 1, no 2


def test_club_faro_vendedores_avance_y_faltante():
    ventas, art, clientes, cfg = _club_faro_datos()
    tabla, res = TB.club_faro_vendedores(ventas, art, clientes, VEND, cfg, _obj_club_faro(),
                                         date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    t = tabla.set_index(["vendedor_id", "linea"])
    assert len(tabla) == 4
    assert t.loc[("101", "SMIRNOFF"), "logrado"] == 2 and t.loc[("101", "SMIRNOFF"), "faltan"] == 27
    assert t.loc[("101", "BLANCOS_DULCES"), "logrado"] == 3 and t.loc[("101", "BLANCOS_DULCES"), "estado"] == "verde"
    assert t.loc[("101", "FRIZZE"), "logrado"] == 1 and t.loc[("101", "FRIZZE"), "faltan"] == 0
    assert t.loc[("100", "SMIRNOFF"), "logrado"] == 1 and t.loc[("100", "SMIRNOFF"), "estado"] == "verde"
    assert t.loc[("101", "SMIRNOFF"), "vendedor"] == "ARIAS DANIEL"
    assert t.loc[("101", "SMIRNOFF"), "estado"] == "rojo"                      # 2/29 = 7 % contra 32 % esperado
    assert res["por_linea"]["SMIRNOFF"]["objetivo"] == 30 and res["por_linea"]["SMIRNOFF"]["logrado"] == 3
    assert res["esperado_pct"] == pytest.approx(17 / 53)


def test_club_faro_sin_compras_ni_objetivos_no_rompe():
    ventas, art, clientes, cfg = _club_faro_datos()
    vacio = _obj_club_faro().iloc[0:0]
    tabla, res = TB.club_faro_vendedores(ventas, art, clientes, VEND, cfg, vacio, date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    # sin objetivos en el Excel, los vendedores de la base que vendieron igual aparecen como "sin objetivo"
    assert (tabla["estado"] == "sin_objetivo").all() and (tabla["objetivo"] == 0).all() and (tabla["logrado"] > 0).all()
    assert res["por_linea"]["FRIZZE"]["objetivo"] == 0 and res["por_linea"]["FRIZZE"]["logrado"] == 0


# ----------------------------------------------------------------------------- 11 Titulares
def _titulares_datos():
    art = pd.DataFrame({"articulo_id": ["T1", "T2", "NO"], "proveedor": [PEN] * 3, "division": [None] * 3,
                        "unidades_por_bulto": [6, 6, 6]})
    cfg = pd.DataFrame({"linea": ["ALMA_MORA", "ALMA_MORA", "DADA"], "articulo_id": ["T1", "T2", "NO"],
                        "incluir": [True, True, False]})
    clientes = pd.DataFrame({"cliente_id": ["as1", "as2", "tr1", "tr2", "vi1", "vi2"], "rubro_cod": ["01", "98", "02", "03", "65", "75"]})

    def it(fid, art_, cli, cant, tipo="F", fecha="2026-09-10"):
        r = av(fid, art_, cant, 1000, vend="101", fecha=fecha, tipo=tipo)
        r["clienteId"] = cli
        return r
    rows = [
        it(1, "T1", "as1", 6),                  # AS con 1 bulto (6 u): cuenta
        it(2, "T1", "as2", 5),                  # AS con 5 u (< 1 bulto): no cuenta
        it(3, "T1", "tr1", 3),                  # tradicional con 3 u iguales: cuenta
        it(4, "T1", "tr2", 2),                  # tradicional con 2 u: no
        it(5, "T1", "tr2", 1), it(6, "T2", "tr2", 2),   # 2+1 de T1 = 3 en el mismo artículo -> cuenta; T2 con 2 no
        it(7, "T1", "vi1", 6),                  # vinoteca = OP & VTK, 1 caja cerrada (6 u): cuenta (subcanal Vinotecas)
        it(11, "T1", "vi2", 3),                 # OP & VTK con 3 u (media caja): no cuenta, la regla es la caja cerrada
        it(8, "NO", "tr1", 10),                 # artículo con INCLUIR = N: no cuenta
        it(9, "T1", "as2", 6, tipo="C"),        # NC: no cuenta
        it(10, "T1", "as2", 6, fecha="2026-09-25"),   # posterior al corte
    ]
    facs = [fa(r["id"], tipo=r["comprobanteTipo"], fecha=r["fecha"], vend=r["vendedor"]) for r in rows]
    return T.build_fact_ventas(rows, facs), art, clientes, cfg


def test_titulares_compras_reglas_por_canal():
    ventas, art, clientes, cfg = _titulares_datos()
    c = TB.titulares_compras(ventas, art, clientes, cfg, date(2026, 9, 1), date(2026, 9, 20))
    assert sorted(c["cliente_id"]) == ["as1", "tr1", "tr2", "vi1"]
    assert set(c["linea"]) == {"ALMA_MORA"}
    assert c.set_index("cliente_id").loc["vi1", "subcanal"] == "Vinotecas"
    assert c.set_index("cliente_id").loc["as1", "canal"] == "Autoservicios"


def test_titulares_resumen_lineas_canales_y_subcanales():
    ventas, art, clientes, cfg = _titulares_datos()
    r = TB.titulares_resumen(ventas, art, clientes, cfg, date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    assert len(r["lineas"]) == 12 and r["lineas"].set_index("linea").loc["ELEMENTOS", "estado"] == "sin_objetivo"
    assert r["lineas"].set_index("linea").loc["ALMA_MORA", "logrado"] == 4
    assert r["lineas"].set_index("linea").loc["ALMA_MORA", "objetivo"] == 351
    can = r["canales"].set_index("nombre")
    assert can.loc["Autoservicios", "logrado"] == 1 and can.loc["Tradicionales", "logrado"] == 2 and can.loc["OP & VTK", "logrado"] == 1
    sub = r["subcanales"].set_index("nombre")
    assert sub.loc["Vinotecas", "logrado"] == 1 and sub.loc["Vinotecas", "objetivo"] == 56
    assert sub.loc["Catering", "estado"] == "sin_objetivo" and sub.loc["On Premise", "avance"] == 0.0


def test_titulares_elementos_es_linea_propia_y_no_suma_a_los_canales():
    ventas, art, clientes, cfg = _titulares_datos()
    art = pd.concat([art, pd.DataFrame({"articulo_id": ["EL1"], "proveedor": [PEN], "division": [None], "unidades_por_bulto": [6]})])
    cfg = pd.concat([cfg, pd.DataFrame({"linea": ["ELEMENTOS"], "articulo_id": ["EL1"], "incluir": [True]})], ignore_index=True)
    r_ = av(99, "EL1", 6, 1000, vend="101", fecha="2026-09-10", tipo="F")
    r_["clienteId"] = "as2"                                        # as2 (autoservicio) compra 1 caja (6 u) de EL1; en las otras líneas no califica
    ventas = pd.concat([ventas, T.build_fact_ventas([r_], [fa(r_["id"], tipo="F", fecha=r_["fecha"], vend=r_["vendedor"])])], ignore_index=True)
    r = TB.titulares_resumen(ventas, art, clientes, cfg, date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    assert r["lineas"].set_index("linea").loc["ELEMENTOS", "logrado"] == 1
    base = TB.titulares_resumen(*_titulares_datos()[:3], _titulares_datos()[3], date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    assert list(r["canales"]["logrado"]) == list(base["canales"]["logrado"])   # los canales no cambian por Elementos


def test_titulares_sin_ventas_no_rompe():
    ventas, art, clientes, cfg = _titulares_datos()
    r = TB.titulares_resumen(ventas.iloc[0:0], art, clientes, cfg, date(2026, 9, 1), date(2026, 10, 31), date(2026, 9, 20))
    assert (r["lineas"]["logrado"] == 0).all()


def test_ventas_sin_escala_por_vendedor_y_canal():
    ventas, art, clientes, cfg = _club_faro_datos()      # vendedores 101 (con ventas) y 100
    t = TB.ventas_sin_escala(ventas, art, VEND, date(2026, 9, 20), ["100", "999"])
    assert list(t["vendedor_id"]) == ["100", "999"]                  # una fila por vendedor pedido, aunque no haya vendido
    assert t.loc[0, "vendido"] > 0 and t.loc[1, "vendido"] == 0
    assert t.loc[0, "vendido"] == pytest.approx(t.loc[0, list(TB.CANALES)].sum())
