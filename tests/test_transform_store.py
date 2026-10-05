import json
from datetime import date

import pandas as pd
import pytest

from sigma_conn import transform as T
from sigma_conn.etl import date_chunks
from sigma_conn.store import Store


def av(fid, art, cant, precio, desc=0, glob=0, tipo="F", fecha="2026-09-14", vend="100", costo=10.0):
    return {"id": fid, "fecha": fecha, "comprobanteCodigo": "FA13", "comprobanteNumero": "0001",
            "comprobanteTipo": tipo, "motivoNc": None, "ajustaComprobanteId": None, "empresa": "0001",
            "surcursal": "0001", "vendedor": vend, "clienteId": "100762", "reparto": None, "item": 1,
            "itemArticuloId": art, "itemDescripcion": "X", "itemRubroCodigo": "1", "itemRubroDescripcion": "R",
            "itemLineaCodigo": "1", "itemLinea": "L", "itemDivisionCodigo": "1", "itemDivision": "D",
            "itemCantidad": cant, "itemPrecioUnitario": precio, "itemDescuento": desc,
            "itemDescuentoGlobal": glob, "itemDescuentoFinanciero": 0, "costoUltimaCompra": costo,
            "costoPromedioPonderado": costo, "itemPedidoId": None}


def fa(fid, estado="pagada", tipo="F", fecha="2026-09-14"):
    return {"id": fid, "fecha": fecha, "comprobanteCodigo": "FA13", "comprobanteNumero": "0001",
            "comprobanteTipo": tipo, "empresa": "0001", "sucursal": "0001", "vendedor": "100",
            "clienteId": "100762", "estado": estado, "pendientePago": 0, "subtotal": 1, "totalComprobante": 1}


def test_importe_neto_aplica_descuentos_secuenciales():
    v = T.build_fact_ventas([av(1, "A", 10, 100, desc=10, glob=12)], [fa(1)])
    assert v.loc[0, "importe_neto"] == pytest.approx(10 * 100 * 0.9 * 0.88)


def test_impuesto_interno_no_se_descuenta():
    r = av(1, "A", 6, 2000, desc=10)
    r["itemImpuestoInternoMonto"] = 100.0
    v = T.build_fact_ventas([r], [fa(1)])
    # (2000-100)*0.9 + 100 = 1810 por unidad
    assert v.loc[0, "importe_neto"] == pytest.approx(6 * 1810)
    assert v.loc[0, "impuesto_interno_unit"] == 100.0
    # sin impuesto interno, la fórmula vuelve a la de siempre
    v2 = T.build_fact_ventas([av(2, "A", 6, 2000, desc=10)], [fa(2)])
    assert v2.loc[0, "importe_neto"] == pytest.approx(6 * 2000 * 0.9)


def test_nc_resta_y_anuladas_se_excluyen():
    ventas = T.build_fact_ventas(
        [av(1, "A", 10, 100), av(2, "A", -10, 100, tipo="C"), av(3, "A", 5, 100), av(4, "A", -5, 100, tipo="C")],
        [fa(1), fa(2, tipo="C"), fa(3, estado="anulada"), fa(4, estado="anulada", tipo="C")],
    )
    validas = T.ventas_validas(ventas)
    assert set(validas["factura_id"]) == {1, 2}
    assert validas["unidades"].sum() == 0  # factura y NC activas se compensan
    assert validas["es_nc"].sum() == 1
    assert len(ventas) == 4  # la tabla conserva las anuladas, marcadas


def test_item_sin_cabecera_queda_desconocido_y_no_se_pierde():
    v = T.build_fact_ventas([av(9, "A", 1, 1)], [])
    assert v.loc[0, "estado"] == "desconocido"
    assert len(T.ventas_validas(v)) == 1


def test_ids_son_texto_y_typos_normalizados():
    v = T.build_fact_ventas([av(1, "0042", 1, 1)], [fa(1)])
    assert v.loc[0, "articulo_id"] == "0042"
    assert v.loc[0, "sucursal"] == "0001"  # venia como 'surcursal'
    art = T.build_dim_articulo([{"id": "1", "costoUltimaCrompa": 5.0, "unidadesPorBulto": 12}])
    assert art.loc[0, "costo_ultima_compra"] == 5.0


def test_cliente_vendedor_explota_ruta():
    rows = [{"id": "1", "nombre": "A", "vendedores": [
        {"vendedor": "114", "diaDeVisita": "4", "ordenDeVisita": None, "repartoId": "174", "repartoDescripcion": "R"},
        {"vendedor": "115", "diaDeVisita": "1,3"}]}]
    cv = T.build_cliente_vendedor(rows)
    assert len(cv) == 2 and cv.loc[1, "dia_visita"] == "1,3"


def test_origen_pedido_clasifica_los_json_conocidos():
    from sigma_conn.transform import origen_pedido as o
    assert o(None) == "directa" and o("") == "directa" and o("{}") == "directa"
    assert o('{"canal": "api", "API_ID": "1"}') == "api"
    assert o('{"canal": "api", "API_ID": "1", "OBSAFIP": "S"}') == "api"
    assert o('{"DISTCODE": "1", "NOSEPARA": "S", "MAGENTOID": "2", "TIPOENVIO": "delivery"}') == "magento"
    assert o('{"OBSAFIP": "S"}') == "directa"
    assert o({"canal": "API"}) == "api"            # ya parseado y en mayúsculas
    assert o("no es json") == "otro" and o('{"x": 1}') == "otro" and o("[1]") == "otro"


def test_importe_bruto_y_origen_en_fact_ventas():
    r = av(1, "A", 10, 100, desc=10, glob=12)
    r["itemPorcentajeIva"] = 21
    r["itemPedidoDatosAdicionales"] = '{"canal": "api", "API_ID": "9"}'
    v = T.build_fact_ventas([r], [fa(1)])
    neto = 10 * 100 * 0.9 * 0.88
    assert v.loc[0, "importe_bruto"] == pytest.approx(neto * 1.21)
    assert v.loc[0, "origen"] == "api"
    assert v.loc[0, "pedido_datos_adicionales"] == '{"canal": "api", "API_ID": "9"}'
    # sin IVA ni datos adicionales: bruto = neto y origen directa
    v2 = T.build_fact_ventas([av(2, "A", 1, 100)], [fa(2)])
    assert v2.loc[0, "importe_bruto"] == v2.loc[0, "importe_neto"] and v2.loc[0, "origen"] == "directa"


def test_categoria_unilever_por_division():
    c = T.categoria_unilever
    U = "UNILEVER DE ARGENTINA SA"
    assert [c(U, d) for d in ("NUTRITION", "PASTA", "HC", "PC", "BEAUTY")] == ["FOOD", "FOOD", "HC", "BPC", "BPC"]
    assert c(U, None) == "COMBO" and c(U, "") == "COMBO"
    assert c(U, "VARIOS") == "EXCLUIDO" and c(U, "FINANCIEROS") == "EXCLUIDO" and c(U, "XYZ") == "EXCLUIDO"
    assert c("GRUPO PEÑAFLOR", "VINOS") is None and c(None, "HC") is None


def test_dim_articulo_trae_categoria_unilever():
    art = T.build_dim_articulo([{"id": "1", "proveedorNombre": "UNILEVER DE ARGENTINA SA", "division": "BEAUTY"},
                                {"id": "2", "proveedorNombre": "UNILEVER DE ARGENTINA SA"},
                                {"id": "3", "proveedorNombre": "ENERGIZER", "division": "PC"}])
    assert list(art["categoria_unilever"]) == ["BPC", "COMBO", pd.NA]


def test_muestra_real_categoria_unilever(sample_dir):
    ar = T.build_dim_articulo(json.load(open(sample_dir / "articulos.json")))
    assert ar["categoria_unilever"].value_counts().to_dict() == {"BPC": 481, "HC": 177, "FOOD": 166, "COMBO": 19, "EXCLUIDO": 10}


def test_categoria_cobertura_combos():
    U = "UNILEVER DE ARGENTINA SA"
    art = T.build_dim_articulo([{"id": "1", "proveedorNombre": U, "division": "BEAUTY"},
                                {"id": "2027", "proveedorNombre": U},       # combo HC
                                {"id": "2031", "proveedorNombre": U},       # combo BPC
                                {"id": "541100021", "proveedorNombre": U},  # combo FOOD
                                {"id": "777", "proveedorNombre": U},        # combo nuevo sin clasificar
                                {"id": "8", "proveedorNombre": U, "division": "VARIOS"},
                                {"id": "9", "proveedorNombre": "ENERGIZER", "division": "PC"}])
    assert list(art["categoria_cobertura"]) == ["BPC", "HC", "BPC", "FOOD", "COMBO_SIN_ASIGNAR", "EXCLUIDO", pd.NA]
    assert list(art["categoria_unilever"])[1] == "COMBO"  # la categoría original no cambia


def test_muestra_real_combos_todos_asignados(sample_dir):
    ar = T.build_dim_articulo(json.load(open(sample_dir / "articulos.json")))
    combos = ar[ar["categoria_unilever"] == "COMBO"]
    assert len(combos) == 19 and set(combos["articulo_id"]) == set(T.COMBO_CATEGORIA)
    assert combos["categoria_cobertura"].value_counts().to_dict() == {"HC": 11, "FOOD": 7, "BPC": 1}


def test_ventas_para_objetivos_excluye_morillo_y_anuladas_pero_no_deposito_salta():
    ventas = T.build_fact_ventas(
        [av(1, "A", 10, 100), av(2, "FIN", 1, 500), av(3, "M", 1, 70), av(4, "A", 1, 100)],
        [fa(1), fa(2), fa(3), fa(4, estado="anulada")])
    art = pd.DataFrame({"articulo_id": ["A", "FIN", "M"],
                        "proveedor": ["UNILEVER DE ARGENTINA SA", "DEPOSITO SALTA", "DEPOSITO MORILLO"]})
    v = T.ventas_para_objetivos(ventas, art)
    assert sorted(v["articulo_id"]) == ["A", "FIN"]          # sin anulada ni Morillo; DEPOSITO SALTA se queda
    assert v["importe_neto"].sum() == pytest.approx(10 * 100 + 500)


def test_ventas_para_objetivos_incluye_nc_y_todos_los_origenes():
    nc = av(2, "A", -2, 100, tipo="NC")
    ventas = T.build_fact_ventas([av(1, "A", 10, 100), nc], [fa(1), fa(2, tipo="NC")])
    art = pd.DataFrame({"articulo_id": ["A"], "proveedor": ["UNILEVER DE ARGENTINA SA"]})
    assert T.ventas_para_objetivos(ventas, art)["importe_neto"].sum() == pytest.approx(800)


def test_ventas_para_objetivos_excluye_varios_de_unilever_pero_no_financieros():
    ventas = T.build_fact_ventas(
        [av(1, "HEL", 1, 1000), av(2, "PROMO", 1, 200), av(3, "HC1", 1, 100), av(4, "VARX", 1, 50)],
        [fa(1), fa(2), fa(3), fa(4)])
    U = "UNILEVER DE ARGENTINA SA"
    art = pd.DataFrame({"articulo_id": ["HEL", "PROMO", "HC1", "VARX"],
                        "proveedor": [U, U, U, "OTRO PROVEEDOR"],
                        "division": ["VARIOS", "FINANCIEROS", "HC", "VARIOS"]})
    v = T.ventas_para_objetivos(ventas, art)
    # heladera (Unilever/VARIOS) afuera; promo (FINANCIEROS) adentro; VARIOS de otro proveedor no se toca
    assert sorted(v["articulo_id"]) == ["HC1", "PROMO", "VARX"]


def test_dim_vendedor_activo():
    d = T.build_dim_vendedor([{"id": "1", "nombre": "A", "desactivado": "N"},
                              {"id": "2", "nombre": "B", "desactivado": "S"},
                              {"id": "3", "nombre": "C", "desactivado": None}])
    assert list(d["activo"]) == [True, False, True]


def test_date_chunks_cubre_sin_solaparse():
    ch = list(date_chunks(date(2026, 9, 1), date(2026, 9, 20), 7))
    assert ch == [(date(2026, 9, 1), date(2026, 9, 7)), (date(2026, 9, 8), date(2026, 9, 14)),
                  (date(2026, 9, 15), date(2026, 9, 20))]
    assert list(date_chunks(date(2026, 9, 1), date(2026, 9, 1), 7)) == [(date(2026, 9, 1), date(2026, 9, 1))]


def test_upsert_window_reemplaza_sin_duplicar_y_limpia_dias(tmp_path):
    st = Store(tmp_path, "csv")
    first = T.build_fact_ventas([av(1, "A", 1, 1, fecha="2026-08-31"), av(2, "A", 2, 1, fecha="2026-09-02"),
                                 av(3, "A", 3, 1, fecha="2026-09-03")],
                                [fa(1, fecha="2026-08-31"), fa(2, fecha="2026-09-02"), fa(3, fecha="2026-09-03")])
    st.upsert_window("fact_ventas_item", first, date(2026, 8, 31), date(2026, 9, 3))
    # recarga de la ventana: la factura 2 desapareció y apareció la 4
    second = T.build_fact_ventas([av(3, "A", 3, 1, fecha="2026-09-03"), av(4, "A", 4, 1, fecha="2026-09-03")],
                                 [fa(3, fecha="2026-09-03"), fa(4, fecha="2026-09-03")])
    st.upsert_window("fact_ventas_item", second, date(2026, 9, 2), date(2026, 9, 3))
    got = st.read_facts("fact_ventas_item")
    assert sorted(got["factura_id"]) == [1, 3, 4]
    assert got["articulo_id"].dtype == "string" or got["articulo_id"].dtype == object
    only_sep = st.read_facts("fact_ventas_item", date(2026, 9, 1), date(2026, 9, 30))
    assert sorted(only_sep["factura_id"]) == [3, 4]


def test_upsert_rechaza_filas_fuera_de_ventana(tmp_path):
    st = Store(tmp_path, "csv")
    df = T.build_fact_ventas([av(1, "A", 1, 1, fecha="2026-09-20")], [fa(1, fecha="2026-09-20")])
    with pytest.raises(ValueError):
        st.upsert_window("fact_ventas_item", df, date(2026, 9, 1), date(2026, 9, 7))


def test_csv_conserva_ceros_a_la_izquierda(tmp_path):
    st = Store(tmp_path, "csv")
    st.write_table("dim_articulo", T.build_dim_articulo([{"id": "0042", "descripcion": "x"}]))
    assert st.read_table("dim_articulo").loc[0, "articulo_id"] == "0042"


# ------------------------------------------------------------------ contra datos reales
def test_muestra_real_invariantes(sample_dir):
    a = json.load(open(sample_dir / "articulos_vendidos.json"))
    f = json.load(open(sample_dir / "facturas.json"))
    v = T.build_fact_ventas(a, f)
    assert len(v) == len(a)
    assert (v["estado"] == "desconocido").sum() == 0
    assert set(v["estado"]) <= {"pagada", "impaga", "anulada"}
    # NC = cantidades negativas, y solo ellas
    assert ((v["unidades"] < 0) == v["es_nc"]).all()
    # 16 comprobantes anulados en la semana muestreada
    assert v.loc[v["estado"] == "anulada", "factura_id"].nunique() == 16
    valid = T.ventas_validas(v)
    assert valid["factura_id"].nunique() == len(f) - 16
    # no hay NC activas apuntando a facturas anuladas
    anuladas = set(v.loc[v["estado"] == "anulada", "factura_id"])
    nc_activas = valid[valid["es_nc"]]
    assert not nc_activas["ajusta_comprobante_id"].isin(anuladas).any()


def test_muestra_real_neto_concilia_con_subtotal_de_factura(sample_dir):
    a = json.load(open(sample_dir / "articulos_vendidos.json"))
    f = json.load(open(sample_dir / "facturas.json"))
    v = T.ventas_validas(T.build_fact_ventas(a, f))
    sub = T.build_dim_factura(f).set_index("factura_id")["subtotal"]
    s = v.groupby("factura_id")["importe_neto"].sum().to_frame("neto").join(sub)
    assert ((s["neto"] - s["subtotal"]).abs() < 0.05).all()   # 100 % de los comprobantes
    assert (v["impuesto_interno_unit"] > 0).sum() > 300


def test_muestra_real_origen_e_iva(sample_dir):
    a = json.load(open(sample_dir / "articulos_vendidos.json"))
    f = json.load(open(sample_dir / "facturas.json"))
    v = T.build_fact_ventas(a, f)
    # distribución verificada a mano en la semana 14-18/09/2026
    assert v["origen"].value_counts().to_dict() == {"api": 2890, "magento": 959, "directa": 394}
    assert (v["porcentaje_iva"] == 21).all()
    assert (v["importe_bruto"] / v["importe_neto"]).dropna().round(6).eq(1.21).all()


def test_muestra_real_dimensiones(sample_dir):
    cl = json.load(open(sample_dir / "clientes.json"))
    assert len(T.build_dim_cliente(cl)) == len(cl)
    cv = T.build_cliente_vendedor(cl)
    assert cv["cliente_id"].nunique() > 4000
    ar = T.build_dim_articulo(json.load(open(sample_dir / "articulos.json")))
    assert ar["articulo_id"].is_unique and ar["costo_ultima_compra"].notna().any()
    ve = T.build_dim_vendedor(json.load(open(sample_dir / "vendedores.json")))
    assert ve["vendedor_id"].is_unique and ve["activo"].sum() == 26
