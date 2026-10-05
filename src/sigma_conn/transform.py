"""Transformaciones JSON de la API -> tablas (DataFrames) con nombres estables.

Normaliza los typos de la API (surcursal, costoUltimaCrompa, totaPedido, ...) para que el
resto del proyecto no tenga que conocerlos.

Hallazgos verificados con datos reales (semana 14-18/09/2026):
- ``itemCantidad`` viene en UNIDADES sueltas (no bultos). bultos = unidades / unidadesPorBulto.
- Las notas de crédito vienen con cantidad NEGATIVA y precio positivo.
- ExportArticulosVendidos incluye comprobantes ANULADOS; el estado sale de ExportFacturas.
- Venta neta = unidades * precio * (1 - desc%) * (1 - descGlobal%). Concilia con el subtotal
  de la factura en ~86% de los casos; el resto tiene otros conceptos (a investigar).
"""

from __future__ import annotations

import json
import logging
from datetime import date

import pandas as pd

log = logging.getLogger(__name__)

ESTADO_ANULADA = "anulada"

# Origen de la venta, derivado de los datos adicionales del pedido (JSON en texto).
ORIGEN_API = "api"          # {"canal": "api", "API_ID": ...}  (probable Axum / app de preventa)
ORIGEN_MAGENTO = "magento"  # {"MAGENTOID": ..., "TIPOENVIO": ...}  (probable Compre Ahora / e-commerce)
ORIGEN_DIRECTA = "directa"  # sin datos adicionales: carga directa en SIGMA
ORIGEN_OTRO = "otro"        # JSON ilegible o con claves desconocidas


def origen_pedido(raw) -> str:
    """Clasifica el origen de una venta a partir de ``itemPedidoDatosAdicionales``.

    Reglas (verificadas con la semana 14-18/09/2026; el mapeo a Axum/Compre Ahora está por confirmar):
    - vacío / null            -> directa
    - tiene MAGENTOID         -> magento
    - canal == "api"          -> api
    - solo OBSAFIP u otras marcas sin canal -> directa (no identifican un canal)
    - no se puede leer el JSON -> otro
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or raw is pd.NA:
        return ORIGEN_DIRECTA
    if isinstance(raw, dict):
        obj = raw
    else:
        text = str(raw).strip()
        if not text:
            return ORIGEN_DIRECTA
        try:
            obj = json.loads(text)
        except ValueError:
            return ORIGEN_OTRO
    if not isinstance(obj, dict):
        return ORIGEN_OTRO
    if not obj:
        return ORIGEN_DIRECTA
    if "MAGENTOID" in obj:
        return ORIGEN_MAGENTO
    if str(obj.get("canal", "")).lower() == "api":
        return ORIGEN_API
    return ORIGEN_DIRECTA if set(obj) <= {"OBSAFIP"} else ORIGEN_OTRO


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _str(s: pd.Series) -> pd.Series:
    """Texto sin espacios; None/NaN quedan como <NA>."""
    return s.astype("string").str.strip()


def _pick(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Selecciona y renombra columnas; las ausentes se crean vacías (tolera cambios de la API)."""
    out = pd.DataFrame(index=df.index)
    for src, dst in mapping.items():
        out[dst] = df[src] if src in df.columns else pd.NA
    return out


# --------------------------------------------------------------------------- facturas
FACTURA_COLS = {
    "id": "factura_id",
    "fecha": "fecha",
    "comprobanteCodigo": "comprobante_codigo",
    "comprobanteNumero": "comprobante_numero",
    "comprobanteTipo": "comprobante_tipo",
    "motivoNc": "motivo_nc",
    "ajustaComprobanteId": "ajusta_comprobante_id",
    "empresa": "empresa",
    "sucursal": "sucursal",
    "puntoVenta": "punto_venta",
    "vendedor": "vendedor_id",
    "clienteId": "cliente_id",
    "estado": "estado",
    "pendientePago": "pendiente_pago",
    "subtotal": "subtotal",
    "totalComprobante": "total_comprobante",
}


def build_dim_factura(rows: list[dict]) -> pd.DataFrame:
    df = _df(rows)
    if df.empty:
        return pd.DataFrame(columns=list(FACTURA_COLS.values()))
    out = _pick(df, FACTURA_COLS)
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.normalize()
    for c in ("comprobante_codigo", "comprobante_numero", "comprobante_tipo", "motivo_nc",
              "empresa", "sucursal", "vendedor_id", "cliente_id", "estado"):
        out[c] = _str(out[c])
    for c in ("pendiente_pago", "subtotal", "total_comprobante"):
        out[c] = _num(out[c])
    out["es_nc"] = out["comprobante_tipo"].eq("C")
    return out.drop_duplicates("factura_id", keep="last").reset_index(drop=True)


# --------------------------------------------------------------------------- ventas
VENTA_COLS = {
    "id": "factura_id",
    "fecha": "fecha",
    "comprobanteCodigo": "comprobante_codigo",
    "comprobanteNumero": "comprobante_numero",
    "comprobanteTipo": "comprobante_tipo",
    "motivoNc": "motivo_nc",
    "ajustaComprobanteId": "ajusta_comprobante_id",
    "empresa": "empresa",
    "surcursal": "sucursal",  # typo de la API
    "vendedor": "vendedor_id",
    "clienteId": "cliente_id",
    "reparto": "reparto",
    "item": "item",
    "itemArticuloId": "articulo_id",
    "itemDescripcion": "articulo_desc",
    "itemRubroCodigo": "rubro_cod",
    "itemRubroDescripcion": "rubro",
    "itemLineaCodigo": "linea_cod",
    "itemLinea": "linea",
    "itemDivisionCodigo": "division_cod",
    "itemDivision": "division",
    "itemCantidad": "unidades",
    "itemPrecioUnitario": "precio_unitario",
    "itemDescuento": "descuento_pct",
    "itemDescuentoGlobal": "descuento_global_pct",
    "itemDescuentoFinanciero": "descuento_financiero_pct",
    "costoUltimaCompra": "costo_unit_ultima_compra",
    "costoPromedioPonderado": "costo_unit_ppp",
    "itemPedidoId": "pedido_id",
    "itemPorcentajeIva": "porcentaje_iva",
    "itemImpuestoInternoMonto": "impuesto_interno_unit",
    "itemImpuestoInternoPorcen": "impuesto_interno_pct",
    "itemPedidoDatosAdicionales": "pedido_datos_adicionales",
}


def build_fact_ventas(av_rows: list[dict], factura_rows: list[dict]) -> pd.DataFrame:
    """Una fila por ítem de comprobante, con el estado de la factura y métricas derivadas."""
    df = _df(av_rows)
    if df.empty:
        cols = list(VENTA_COLS.values()) + ["origen", "estado", "es_nc", "importe_neto", "importe_bruto",
                                            "costo_total_ultima_compra"]
        return pd.DataFrame(columns=cols)

    out = _pick(df, VENTA_COLS)
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.normalize()
    for c in ("comprobante_codigo", "comprobante_numero", "comprobante_tipo", "motivo_nc", "empresa",
              "sucursal", "vendedor_id", "cliente_id", "reparto", "articulo_id", "articulo_desc",
              "rubro_cod", "rubro", "linea_cod", "linea", "division_cod", "division"):
        out[c] = _str(out[c])
    for c in ("unidades", "precio_unitario", "descuento_pct", "descuento_global_pct",
              "descuento_financiero_pct", "costo_unit_ultima_compra", "costo_unit_ppp"):
        out[c] = _num(out[c])
    for c in ("descuento_pct", "descuento_global_pct", "descuento_financiero_pct"):
        out[c] = out[c].fillna(0.0)

    # IVA por ítem (para la venta bruta). Si la API no lo trae se asume 0 y se avisa.
    out["porcentaje_iva"] = _num(out["porcentaje_iva"])
    sin_iva = int(out["porcentaje_iva"].isna().sum())
    if sin_iva:
        log.warning("%d ítems sin porcentaje de IVA; importe_bruto = importe_neto en esos ítems", sin_iva)
        out["porcentaje_iva"] = out["porcentaje_iva"].fillna(0.0)

    # Origen de la venta (guardamos el JSON crudo como texto + el origen derivado).
    raw = out["pedido_datos_adicionales"]
    out["origen"] = raw.map(origen_pedido).astype("string")
    out["pedido_datos_adicionales"] = raw.map(
        lambda x: None if x is None or x is pd.NA or (isinstance(x, float) and pd.isna(x))
        else (x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))
    ).astype("string")

    # Estado (impaga/pagada/anulada) viene de la cabecera de la factura.
    fac = build_dim_factura(factura_rows)
    estado = fac.set_index("factura_id")["estado"] if not fac.empty else pd.Series(dtype="string")
    out["estado"] = out["factura_id"].map(estado).astype("string")
    faltan = out["estado"].isna().sum()
    if faltan:
        log.warning("%d ítems sin cabecera de factura en el rango; estado='desconocido'", faltan)
        out["estado"] = out["estado"].fillna("desconocido")

    out["es_nc"] = out["comprobante_tipo"].eq("C")
    # Neto s/IVA como lo calcula SIGMA: el precio unitario INCLUYE el impuesto interno fijo (whisky, vodka,
    # Frizze...) y los descuentos se aplican solo sobre la parte sin impuesto interno:
    #   neto = unidades * ((precio - imp_interno) * (1 - desc%) * (1 - desc_global%) + imp_interno)
    # Verificado: concilia con el subtotal de la factura en el 100 % de los comprobantes de la muestra.
    out["impuesto_interno_unit"] = _num(out["impuesto_interno_unit"]).fillna(0.0)
    out["impuesto_interno_pct"] = _num(out["impuesto_interno_pct"]).fillna(0.0)
    if (out["impuesto_interno_pct"] != 0).any():
        log.warning("%d ítems con impuesto interno porcentual (no se trata distinto del fijo; revisar)",
                    int((out["impuesto_interno_pct"] != 0).sum()))
    base = out["precio_unitario"] - out["impuesto_interno_unit"]
    out["importe_neto"] = out["unidades"] * (
        base * (1 - out["descuento_pct"] / 100.0) * (1 - out["descuento_global_pct"] / 100.0)
        + out["impuesto_interno_unit"]
    )
    out["importe_bruto"] = out["importe_neto"] * (1 + out["porcentaje_iva"] / 100.0)  # c/IVA
    out["costo_total_ultima_compra"] = out["unidades"] * out["costo_unit_ultima_compra"]
    return out.reset_index(drop=True)


def ventas_validas(ventas: pd.DataFrame) -> pd.DataFrame:
    """Excluye comprobantes anulados (facturas y sus NC anuladas se cancelan en pares)."""
    return ventas[ventas["estado"] != ESTADO_ANULADA]


# Proveedores que NO sirven para los tableros (decidido por Juan, 2026-10-02): DEPOSITO MORILLO se descarta.
# DEPOSITO SALTA SÍ cuenta (sus números se leen: NC por ajuste, artículos financieros y fletes).
PROVEEDORES_EXCLUIDOS_OBJETIVOS = frozenset({"DEPOSITO MORILLO"})


# Divisiones de UNILEVER que no cuentan como venta para objetivos: VARIOS = heladeras y muebles (Juan, 2026-10-02).
# FINANCIEROS (promos) SÍ cuenta para la facturación (aunque no suma a ninguna categoría de cobertura).
DIVISIONES_UNILEVER_EXCLUIDAS_OBJETIVOS = frozenset({"VARIOS"})


def ventas_para_objetivos(ventas: pd.DataFrame, dim_articulo: pd.DataFrame) -> pd.DataFrame:
    """Ventas válidas (sin anuladas) que cuentan para objetivos de facturación: todos los canales (Axum,
    Compre Ahora y Directa, incluidas las NC) menos (a) los proveedores de PROVEEDORES_EXCLUIDOS_OBJETIVOS y
    (b) los artículos de Unilever con división en DIVISIONES_UNILEVER_EXCLUIDAS_OBJETIVOS. Agrega `proveedor`."""
    v = ventas_validas(ventas)
    cols = ["articulo_id", "proveedor"] + (["division"] if "division" in dim_articulo.columns else [])
    art = dim_articulo.drop_duplicates("articulo_id")[cols].rename(columns={"division": "_division_art"})
    v = v.merge(art, on="articulo_id", how="left")
    prov = v["proveedor"].astype("string").str.strip().str.upper()
    excl = prov.isin(PROVEEDORES_EXCLUIDOS_OBJETIVOS)
    if "_division_art" in v.columns:
        div = v["_division_art"].astype("string").str.strip().str.upper()
        excl = excl | (prov.str.contains("UNILEVER", na=False) & div.isin(DIVISIONES_UNILEVER_EXCLUIDAS_OBJETIVOS))
    return v[~excl.fillna(False).astype(bool)].drop(columns=["_division_art"], errors="ignore").reset_index(drop=True)


# --------------------------------------------------------------------------- dimensiones
# Categoría Unilever para cobertura (decidido por Juan, 2026-10-01). Se deriva de `division` de SIGMA.
CAT_FOOD, CAT_HC, CAT_BPC, CAT_COMBO, CAT_EXCLUIDO = "FOOD", "HC", "BPC", "COMBO", "EXCLUIDO"
_DIVISION_A_CATEGORIA = {"NUTRITION": CAT_FOOD, "PASTA": CAT_FOOD, "HC": CAT_HC, "PC": CAT_BPC, "BEAUTY": CAT_BPC}


def categoria_unilever(proveedor, division) -> str | None:
    """FOOD/HC/BPC según la división; COMBO si no tiene división; EXCLUIDO para VARIOS (heladeras y
    muebles), FINANCIEROS (promos) y cualquier división desconocida. None si el proveedor no es Unilever."""
    if proveedor is None or pd.isna(proveedor) or "UNILEVER" not in str(proveedor).upper():
        return None
    if division is None or pd.isna(division) or str(division).strip() == "":
        return CAT_COMBO
    return _DIVISION_A_CATEGORIA.get(str(division).strip().upper(), CAT_EXCLUIDO)


# Categoría de cobertura de cada combo Unilever (por articulo_id; decidido por Juan 2026-10-02).
# SIGMA no trae la composición de los combos, por eso se asigna a mano. Un combo suma a la cobertura de su categoría.
CAT_COMBO_SIN_ASIGNAR = "COMBO_SIN_ASIGNAR"
COMBO_CATEGORIA: dict[str, str] = {
    # FOOD
    "541100021": CAT_FOOD, "541100018": CAT_FOOD, "541100019": CAT_FOOD, "541100022": CAT_FOOD,
    "541100020": CAT_FOOD, "2006": CAT_FOOD, "541100012": CAT_FOOD,
    # HC
    "2027": CAT_HC, "2008": CAT_HC, "2029": CAT_HC, "999901": CAT_HC, "999900": CAT_HC,
    "2017": CAT_HC, "2018": CAT_HC, "999915": CAT_HC, "2007": CAT_HC, "2028": CAT_HC, "2030": CAT_HC,
    # BPC
    "2031": CAT_BPC,
}


def categoria_cobertura(articulo_id, categoria) -> str | None:
    """Categoría para cobertura: igual a `categoria_unilever`, salvo los COMBO, que toman la categoría de
    COMBO_CATEGORIA (o COMBO_SIN_ASIGNAR si es un combo nuevo sin clasificar, para avisar en el tablero)."""
    if categoria is None or pd.isna(categoria):
        return None
    if categoria != CAT_COMBO:
        return categoria
    return COMBO_CATEGORIA.get(str(articulo_id), CAT_COMBO_SIN_ASIGNAR)


def build_dim_articulo(rows: list[dict]) -> pd.DataFrame:
    df = _df(rows)
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    # typo de la API: costoUltimaCrompa
    if "costoUltimaCrompa" in df.columns and "costoUltimaCompra" not in df.columns:
        df["costoUltimaCompra"] = df["costoUltimaCrompa"]
    out = _pick(df, {
        "id": "articulo_id", "descripcion": "descripcion", "presentacion": "presentacion",
        "rubroCodigo": "rubro_cod", "rubroDescripcion": "rubro",
        "lineaCodigo": "linea_cod", "linea": "linea",
        "divisionCodigo": "division_cod", "division": "division",
        "grupoCodigo": "grupo_cod", "grupoDescripcion": "grupo", "marca": "marca",
        "proveedorCodigo": "proveedor_cod", "proveedorNombre": "proveedor",
        "unidadesPorBulto": "unidades_por_bulto", "unidadesPorDisplay": "unidades_por_display",
        "litrosUnitarios": "litros_unitarios", "kilosUnitarios": "kilos_unitarios",
        "costoUltimaCompra": "costo_ultima_compra", "costoPromedioPonderado": "costo_ppp",
        "suspendido": "suspendido", "desactivado": "desactivado",
        "ultimaModificacion": "ultima_modificacion",
    })
    for c in ("articulo_id", "descripcion", "presentacion", "rubro_cod", "rubro", "linea_cod", "linea",
              "division_cod", "division", "grupo_cod", "grupo", "marca", "proveedor_cod", "proveedor"):
        out[c] = _str(out[c])
    for c in ("unidades_por_bulto", "unidades_por_display", "litros_unitarios", "kilos_unitarios",
              "costo_ultima_compra", "costo_ppp"):
        out[c] = _num(out[c])
    out["categoria_unilever"] = [categoria_unilever(p, d) for p, d in zip(out["proveedor"], out["division"])]
    out["categoria_unilever"] = out["categoria_unilever"].astype("string")
    out["categoria_cobertura"] = [categoria_cobertura(a, c) for a, c in zip(out["articulo_id"], out["categoria_unilever"])]
    out["categoria_cobertura"] = out["categoria_cobertura"].astype("string")
    return out.drop_duplicates("articulo_id", keep="last").reset_index(drop=True)


def build_dim_vendedor(rows: list[dict]) -> pd.DataFrame:
    df = _df(rows)
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    # la doc dice divisionesArticulo; la API real devuelve divisionesarticulo
    if "divisionesarticulo" in df.columns and "divisionesArticulo" not in df.columns:
        df["divisionesArticulo"] = df["divisionesarticulo"]
    out = _pick(df, {
        "id": "vendedor_id", "nombre": "nombre", "desactivado": "desactivado",
        "sucursal": "sucursal", "email": "email",
        "supervisorId": "supervisor_id", "supervisor": "supervisor",
        "divisionesArticulo": "divisiones_articulo",
    })
    for c in ("vendedor_id", "nombre", "sucursal", "email", "supervisor_id", "supervisor", "divisiones_articulo"):
        out[c] = _str(out[c])
    out["activo"] = _str(out.pop("desactivado")).str.upper().ne("S").fillna(True).astype(bool)
    # DNI: la API no lo documenta; se toma el primer campo con nombre de documento si existe (si no, queda vacío)
    cols_l = {str(c).lower(): c for c in df.columns}
    doc = next((cols_l[k] for k in ("dni", "numerodocumento", "documento", "nrodocumento", "cuil", "cuit") if k in cols_l), None)
    out["dni"] = _str(df[doc]) if doc else pd.NA
    return out.drop_duplicates("vendedor_id", keep="last").reset_index(drop=True)


def build_dim_cliente(rows: list[dict]) -> pd.DataFrame:
    df = _df(rows)
    if df.empty:
        return pd.DataFrame()
    out = _pick(df, {
        "id": "cliente_id", "nombre": "nombre", "rubroCodigo": "rubro_cod", "rubroDescripcion": "rubro",
        "grupoCodigo": "grupo_cod", "grupoDescripcion": "grupo", "zona": "zona",
        "tipoDocumento": "tipo_documento", "numeroDocumento": "numero_documento",
        "idClienteMadre": "cliente_madre_id", "localidad": "localidad", "provincia": "provincia",
        "latitud": "latitud", "longitud": "longitud",
        "suspendido": "suspendido", "desactivado": "desactivado",
        "fechaAlta": "fecha_alta", "vendedorPredeterminado": "vendedor_predeterminado_id",
        "limiteCredito": "limite_credito", "ultimaModificacion": "ultima_modificacion",
    })
    for c in ("cliente_id", "nombre", "rubro_cod", "rubro", "grupo_cod", "grupo", "zona", "tipo_documento",
              "numero_documento", "cliente_madre_id", "localidad", "provincia", "vendedor_predeterminado_id"):
        out[c] = _str(out[c])
    for c in ("latitud", "longitud", "limite_credito"):
        out[c] = _num(out[c])
    out["fecha_alta"] = pd.to_datetime(out["fecha_alta"], errors="coerce")
    return out.drop_duplicates("cliente_id", keep="last").reset_index(drop=True)


def build_cliente_vendedor(rows: list[dict]) -> pd.DataFrame:
    """Un cliente puede tener varios vendedores; acá va la hoja de ruta (día/orden de visita)."""
    recs: list[dict] = []
    for r in rows:
        cid = str(r.get("id", "")).strip()
        for v in r.get("vendedores") or []:
            recs.append({
                "cliente_id": cid,
                "vendedor_id": str(v.get("vendedor", "")).strip(),
                "dia_visita": v.get("diaDeVisita"),
                "orden_visita": v.get("ordenDeVisita"),
                "frecuencia_visita": v.get("frecuenciaVisita"),
                "reparto_id": v.get("repartoId", v.get("repardoId")),  # typo en ClientesNovedades
                "reparto": v.get("repartoDescripcion"),
                "condicion_venta": v.get("condicionVentaDescripcion", v.get("condicionVenta")),
                "lista_precio": v.get("listaDePrecio"),
                "descuento_pct": v.get("descuento"),
            })
    cols = ["cliente_id", "vendedor_id", "dia_visita", "orden_visita", "frecuencia_visita",
            "reparto_id", "reparto", "condicion_venta", "lista_precio", "descuento_pct"]
    out = pd.DataFrame(recs, columns=cols)
    for c in ("dia_visita", "frecuencia_visita", "reparto_id", "reparto", "condicion_venta", "lista_precio"):
        out[c] = _str(out[c])
    out["orden_visita"] = _num(out["orden_visita"])
    out["descuento_pct"] = _num(out["descuento_pct"])
    return out


def build_saldos(rows: list[dict], snapshot: date) -> pd.DataFrame:
    df = _df(rows)
    if df.empty:
        return pd.DataFrame(columns=["cliente_id", "empresa", "moneda", "saldo", "fecha_snapshot"])
    out = _pick(df, {"id": "cliente_id", "empresa": "empresa", "moneda": "moneda", "saldo": "saldo"})
    for c in ("cliente_id", "empresa", "moneda"):
        out[c] = _str(out[c])
    out["saldo"] = _num(out["saldo"])
    out["fecha_snapshot"] = pd.Timestamp(snapshot)
    return out
