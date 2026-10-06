"""Capa de datos de los tableros (pandas puro, sin Streamlit, con tests).

Tablero de gerentes: facturación por vendedor frente a su escala del mes, premio en $ y corte por canal.
Toda cifra de objetivos sale de `ventas_para_objetivos` (sin anuladas, sin Depósito Morillo, sin heladeras y
muebles de Unilever; todos los canales, las NC restan).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values

from . import negocio as N
from . import objetivos as O
from . import transform as T
from .store import Store

ROOT = Path(__file__).resolve().parents[2]

# api = pedidos que entran por la app de preventa (deviceId API), magento = Compre Ahora (UNILEVER-CA),
# directa = cargas directas en SIGMA y notas de crédito.
CANAL_POR_ORIGEN = {"api": "Axum", "magento": "Compre Ahora", "directa": "Directa"}
CANALES = ("Axum", "Compre Ahora", "Directa", "Otro")


# Semáforo de facturación (decidido por Juan, 2026-10-02: "semáforo en todo"). Siempre ícono + texto, nunca solo color.
#   verde    = ya alcanzó al menos el escalón 1
#   amarillo = todavía no, pero al ritmo actual llega al escalón 1
#   rojo     = al ritmo actual no llega al escalón 1
ESTADO_TXT = {"verde": "✔ Escalón alcanzado", "amarillo": "▲ En camino al escalón 1", "rojo": "✖ En riesgo"}
ESTADO_COLOR = {"verde": "#0ca30c", "amarillo": "#fab219", "rojo": "#d03b3b", "sin_objetivo": "#9a9a9a"}  # paleta de estados (fija)


def estado_facturacion(ev: dict) -> str:
    if ev["escalon"] > 0:
        return "verde"
    return "amarillo" if ev["escalones"][0]["proyeccion_alcanza"] else "rojo"


def canal_de_origen(origen) -> str:
    return CANAL_POR_ORIGEN.get(str(origen), "Otro")


# ----------------------------------------------------------------------------- acceso a datos
def abrir_store() -> Store:
    """Abre el Store leyendo SOLO SIGMA_DATA_DIR y SIGMA_STORE_FORMAT (variable de entorno o `.env`).
    No carga el token de la API en el proceso del tablero."""
    env = dotenv_values(ROOT / ".env")
    data_dir = Path(os.getenv("SIGMA_DATA_DIR") or env.get("SIGMA_DATA_DIR") or "./data")
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    fmt = (os.getenv("SIGMA_STORE_FORMAT") or env.get("SIGMA_STORE_FORMAT") or "parquet").strip().lower()
    return Store(data_dir, fmt)


def meses_disponibles(store: Store) -> list[str]:
    """Meses (AAAA-MM) con ventas cargadas, del más viejo al más nuevo."""
    carpeta = store.fact_dir("fact_ventas_item")
    return sorted(p.stem for p in carpeta.glob(f"*.{store.ext}")) if carpeta.exists() else []


def cargar_ventas_mes(store: Store, mes: str) -> pd.DataFrame:
    anio, m = (int(x) for x in mes.split("-"))
    desde = date(anio, m, 1)
    hasta = (pd.Timestamp(desde) + pd.offsets.MonthEnd(0)).date()
    return store.read_facts("fact_ventas_item", desde, hasta)


def ultimo_dia_con_ventas(ventas: pd.DataFrame) -> date | None:
    v = T.ventas_validas(ventas)
    return None if v.empty else pd.to_datetime(v["fecha"]).max().date()


# ----------------------------------------------------------------------------- facturación por vendedor
def facturacion_vendedores(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, dim_vendedor: pd.DataFrame,
                           corte: date) -> tuple[pd.DataFrame, dict]:
    """Una fila por vendedor con escala de preventa (aunque no haya vendido) y un resumen.

    `ventas`: ventas del mes (fact_ventas_item). `corte`: último día contado (inclusive).
    Devuelve (tabla, resumen). Las columnas de dinero son neto s/IVA en pesos."""
    v = T.ventas_para_objetivos(ventas, dim_articulo)
    v = v[pd.to_datetime(v["fecha"]) <= pd.Timestamp(corte)].copy()
    v["vendedor_id"] = v["vendedor_id"].astype("string")
    v["canal"] = v["origen"].map(canal_de_origen)

    por_canal = v.pivot_table(index="vendedor_id", columns="canal", values="importe_neto", aggfunc="sum", fill_value=0.0)
    for c in CANALES:
        if c not in por_canal.columns:
            por_canal[c] = 0.0
    por_canal = por_canal[list(CANALES)].astype(float)
    nombres = (dim_vendedor.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype("string"))
               .set_index("vendedor_id")["nombre"].to_dict()) if len(dim_vendedor) else {}

    filas = []
    for vid, perfil in sorted(N.VENDEDOR_PERFIL.items()):
        canales = por_canal.loc[vid] if vid in por_canal.index else pd.Series(0.0, index=CANALES)
        vendido = float(canales.sum())
        ev = O.evaluar_facturacion(vendido, perfil, corte)
        e1, e2, e3 = (e["objetivo"] for e in ev["escalones"])
        sig = ev["siguiente"]
        estado = estado_facturacion(ev)
        sup_id = N.SUPERVISOR_VENDEDOR.get(vid)
        filas.append({
            "vendedor_id": vid, "vendedor": nombres.get(vid, vid), "perfil": perfil,
            "supervisor": N.SUPERVISORES.get(sup_id, "") if sup_id else "",
            "vendido": vendido, **{c: float(canales[c]) for c in CANALES},
            "objetivo_esc1": e1, "objetivo_esc2": e2, "objetivo_esc3": e3,
            "avance_esc1": vendido / e1, "pct_esc3": vendido / e3, "tick_esc1": e1 / e3, "tick_esc2": e2 / e3,
            "estado": estado, "estado_txt": ESTADO_TXT[estado],
            "escalon": ev["escalon"], "premio": ev["premio"], "premio_proyectado": ev["premio_proyectado"],
            "ritmo_diario": ev["ritmo_diario"], "proyeccion": ev["proyeccion"],
            "siguiente_escalon": sig["escalon"] if sig else None,
            "siguiente_objetivo": sig["objetivo"] if sig else None,
            "faltante_siguiente": sig["faltante"] if sig else 0.0,
            "media_necesaria": sig["media_necesaria"] if sig else 0.0,
        })
    tabla = pd.DataFrame(filas)

    fuera = por_canal.drop(index=[i for i in por_canal.index if i in N.VENDEDOR_PERFIL])
    sin_escala = pd.DataFrame({"vendedor_id": fuera.index.astype(str), "vendido": fuera.sum(axis=1).to_numpy()})
    sin_escala["vendedor"] = sin_escala["vendedor_id"].map(lambda i: nombres.get(i, i))
    sin_escala = sin_escala[["vendedor_id", "vendedor", "vendido"]].sort_values("vendido", ascending=False).reset_index(drop=True)

    resumen = {
        "corte": corte, "dias_transcurridos": O.dias_transcurridos(corte), "dias_restantes": O.dias_restantes(corte),
        "total_con_escala": float(tabla["vendido"].sum()), "total_sin_escala": float(sin_escala["vendido"].sum()),
        "total_empresa": float(v["importe_neto"].sum()),
        "por_canal_empresa": {c: float(por_canal[c].sum()) for c in CANALES},
        "con_escalon": int((tabla["escalon"] > 0).sum()), "vendedores": len(tabla),
        "por_estado": {e: int((tabla["estado"] == e).sum()) for e in ESTADO_TXT},
        "premio_alcanzado": int(tabla["premio"].sum()), "premio_proyectado": int(tabla["premio_proyectado"].sum()),
        "sin_escala": sin_escala,
    }
    return tabla, resumen


# ----------------------------------------------------------------------------- ritmo del mes
def ritmo_mes(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, corte: date,
              vendedor_ids: list[str] | None = None) -> pd.DataFrame:
    """Venta acumulada día por día del mes de `corte` frente a la ruta de cada escalón.

    Una fila por día calendario del mes. `acumulado` llega hasta `corte` (después es NaN).
    `esc1/esc2/esc3` = ruta recta hasta el objetivo del escalón: objetivo × (días de venta pasados / 26), tope 100 %
    (objetivo diario = mensual / 26). Con varios vendedores, el acumulado y los objetivos se suman (la ruta es
    "si todos llegan a ese escalón"). Solo vendedores con escala de preventa."""
    ids = [str(i) for i in (vendedor_ids if vendedor_ids else sorted(N.VENDEDOR_PERFIL)) if str(i) in N.VENDEDOR_PERFIL]
    v = T.ventas_para_objetivos(ventas, dim_articulo)
    v = v[v["vendedor_id"].astype("string").isin(ids)]
    primero = date(corte.year, corte.month, 1)
    ultimo = (pd.Timestamp(primero) + pd.offsets.MonthEnd(0)).date()
    dias = pd.date_range(primero, ultimo, freq="D")
    por_dia = v.assign(dia=pd.to_datetime(v["fecha"]).dt.normalize()).groupby("dia")["importe_neto"].sum()
    diario = por_dia.reindex(dias, fill_value=0.0)
    acumulado = diario.cumsum().where(dias <= pd.Timestamp(corte))
    objetivos = [sum(N.ESCALAS_FACTURACION[N.VENDEDOR_PERFIL[i]][k] for i in ids) for k in range(3)]
    fraccion = [min(O.dias_de_venta(primero, d.date()) / N.DIAS_OBJETIVO_MES, 1.0) for d in dias]
    out = pd.DataFrame({"fecha": dias, "acumulado": acumulado.to_numpy()})
    for k in range(3):
        out[f"esc{k + 1}"] = [objetivos[k] * f for f in fraccion]
    return out


# ----------------------------------------------------------------------------- cobertura (BPC / FOOD / HC)
# Semáforo de avance contra el ritmo esperado (propuesta aceptada por Juan, 2026-10-02):
#   verde    = ya cumplió el objetivo, o va en o por encima del avance esperado a hoy
#   amarillo = va entre el 80 % y el 100 % del avance esperado
#   rojo     = va por debajo del 80 % del avance esperado
UMBRAL_AMARILLO = 0.8
ESTADO_AVANCE_TXT = {"verde": "✔ En ritmo", "amarillo": "▲ Algo atrasado", "rojo": "✖ Atrasado"}
ESTADO_CF_TXT = {**ESTADO_AVANCE_TXT, "sin_objetivo": "• Sin objetivo cargado"}   # Club Faro: vendedor de la base sin objetivo en el Excel


def bimestre_de(mes: str) -> tuple[date, date]:
    """Bimestre calendario (ene–feb, mar–abr, …, sep–oct, …) al que pertenece el mes AAAA-MM."""
    anio, m = (int(x) for x in mes.split("-"))
    m0 = m if m % 2 == 1 else m - 1
    inicio = date(anio, m0, 1)
    fin = (pd.Timestamp(date(anio, m0 + 1, 1)) + pd.offsets.MonthEnd(0)).date()
    return inicio, fin


def cargar_ventas_rango(store: Store, desde: date, hasta: date) -> pd.DataFrame:
    return store.read_facts("fact_ventas_item", desde, hasta)


def estado_avance(avance: float, esperado: float) -> str:
    """`avance` = logrado / objetivo; `esperado` = fracción del objetivo que debería llevar a hoy (0–1)."""
    if avance >= 1 or avance >= esperado:
        return "verde"
    return "amarillo" if avance >= UMBRAL_AMARILLO * esperado else "rojo"


def fraccion_esperada(inicio: date, fin: date, corte: date) -> float:
    """Avance lineal esperado por días de venta (lun–sáb) entre `inicio` y `fin`, medido hasta `corte` inclusive."""
    total = O.dias_de_venta(inicio, fin)
    if total == 0:
        return 1.0
    return min(O.dias_de_venta(inicio, min(corte, fin)) / total, 1.0)


def clientes_con_compra(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, inicio: date, corte: date) -> pd.DataFrame:
    """Una fila por (vendedor, categoría, cliente) con al menos una compra válida de la categoría entre `inicio` y `corte`.

    Compra válida = ítem de `ventas_para_objetivos` (sin anuladas, sin Morillo, sin VARIOS de Unilever) que no es nota de
    crédito y tiene unidades > 0. La categoría sale de `categoria_cobertura` (los combos van a la de su asignación);
    los combos sin asignar no cuentan. Las NC no descuentan clientes (convención)."""
    v = T.ventas_para_objetivos(ventas, dim_articulo)
    f = pd.to_datetime(v["fecha"])
    v = v[(f >= pd.Timestamp(inicio)) & (f <= pd.Timestamp(corte)) & ~v["es_nc"].astype(bool) & (v["unidades"] > 0)]
    cat = dim_articulo.drop_duplicates("articulo_id").assign(articulo_id=lambda d: d["articulo_id"].astype("string")) \
        .set_index("articulo_id")["categoria_cobertura"]
    v = v.assign(categoria=v["articulo_id"].astype("string").map(cat), vendedor_id=v["vendedor_id"].astype("string"))
    v = v[v["categoria"].isin(N.CATEGORIAS_COBERTURA)]
    return v[["vendedor_id", "categoria", "cliente_id"]].drop_duplicates().reset_index(drop=True)


def cobertura_vendedores(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, dim_vendedor: pd.DataFrame,
                         obj_cobertura: pd.DataFrame, inicio: date, fin: date, corte: date) -> tuple[pd.DataFrame, dict]:
    """Cobertura (clientes con compra) por vendedor y categoría contra su objetivo del bimestre.

    Devuelve (tabla, resumen). La tabla trae una fila por (vendedor con objetivo × categoría), aunque no tenga clientes.
    El resumen trae, por categoría, los clientes distintos de TODA la distribuidora frente al objetivo total."""
    cc = clientes_con_compra(ventas, dim_articulo, inicio, corte)
    por_vc = cc.groupby(["vendedor_id", "categoria"])["cliente_id"].nunique()
    esperado = fraccion_esperada(inicio, fin, corte)
    nombres = (dim_vendedor.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype("string"))
               .set_index("vendedor_id")["nombre"].to_dict()) if len(dim_vendedor) else {}
    filas = []
    for r in obj_cobertura.itertuples():
        vid, cat = str(r.vendedor_id), str(r.categoria)
        clientes = int(por_vc.get((vid, cat), 0))
        objetivo = float(r.objetivo)
        avance = clientes / objetivo if objetivo else 0.0
        estado = estado_avance(avance, esperado)
        filas.append({
            "vendedor_id": vid, "vendedor": nombres.get(vid, vid), "grupo": r.grupo, "categoria": cat,
            "clientes": clientes, "objetivo": objetivo, "avance": avance, "esperado_pct": esperado,
            "esperado_clientes": objetivo * esperado, "faltan": max(objetivo - clientes, 0.0),
            "estado": estado, "estado_txt": ESTADO_AVANCE_TXT[estado],
        })
    tabla = pd.DataFrame(filas)
    por_cat = {}
    for cat in N.CATEGORIAS_COBERTURA:
        sub = obj_cobertura[obj_cobertura["categoria"] == cat]
        total = float(sub["total_distribuidora"].iloc[0]) if len(sub) else 0.0
        clientes = int(cc.loc[cc["categoria"] == cat, "cliente_id"].nunique())
        av = clientes / total if total else 0.0
        por_cat[cat] = {"clientes": clientes, "objetivo": total, "avance": av, "esperado_clientes": total * esperado,
                        "estado": estado_avance(av, esperado)}
    resumen = {"inicio": inicio, "fin": fin, "corte": corte, "esperado_pct": esperado, "por_categoria": por_cat,
               "periodo": str(obj_cobertura["periodo"].iloc[0]) if len(obj_cobertura) else ""}
    return tabla, resumen


# ----------------------------------------------------------------------------- Mis Ventas (campañas Unilever)
def mis_ventas_vendedores(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, dim_vendedor: pd.DataFrame,
                          obj_mis_ventas: pd.DataFrame, cfg_campana: pd.DataFrame,
                          inicio: date, fin: date, corte: date) -> pd.DataFrame:
    """Avance de cada vendedor en cada campaña de Mis Ventas contra su target del bimestre.

    Una fila por fila de `obj_mis_ventas` (vendedor × campaña × tipo). Los artículos de cada campaña salen de
    `cfg_campana` (solo los de `incluir=True`). **COBERTURA** = clientes distintos con al menos una compra de la
    campaña (sin NC, unidades > 0); **VOLUMEN** = unidades netas de la campaña (las NC restan). Mismas reglas de
    base que el resto de los objetivos (`ventas_para_objetivos`, todos los canales). Semáforo = `estado_avance`."""
    v = T.ventas_para_objetivos(ventas, dim_articulo)
    f = pd.to_datetime(v["fecha"])
    v = v[(f >= pd.Timestamp(inicio)) & (f <= pd.Timestamp(corte))].copy()
    v["articulo_id"] = v["articulo_id"].astype("string")
    v["vendedor_id"] = v["vendedor_id"].astype("string")
    cfg = cfg_campana[cfg_campana["incluir"].astype(bool)][["articulo_id", "campana"]].astype({"articulo_id": "string"})
    vc = v.merge(cfg, on="articulo_id", how="inner")
    unidades = vc.groupby(["vendedor_id", "campana"])["unidades"].sum()
    compras = vc[~vc["es_nc"].astype(bool) & (vc["unidades"] > 0)]
    clientes = compras.groupby(["vendedor_id", "campana"])["cliente_id"].nunique()
    esperado = fraccion_esperada(inicio, fin, corte)
    nombres = (dim_vendedor.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype("string"))
               .set_index("vendedor_id")["nombre"].to_dict()) if len(dim_vendedor) else {}
    filas = []
    for r in obj_mis_ventas.itertuples():
        vid, camp, tipo = str(r.vendedor_id), str(r.campana), str(r.tipo)
        logrado = float(clientes.get((vid, camp), 0)) if tipo == "COBERTURA" else float(unidades.get((vid, camp), 0.0))
        target = float(r.target)
        avance = logrado / target if target else 0.0
        estado = estado_avance(avance, esperado)
        unidad = "clientes" if tipo == "COBERTURA" else "unidades"
        filas.append({
            "vendedor_id": vid, "vendedor": nombres.get(vid, vid), "campana": camp,
            "campana_nombre": N.CAMPANA_NOMBRE.get(camp, camp), "tipo": tipo, "unidad": unidad,
            "panel": f"{N.CAMPANA_NOMBRE.get(camp, camp)} · {tipo.lower()} ({unidad})",
            "logrado": logrado, "target": target, "avance": avance, "esperado_pct": esperado,
            "esperado_valor": target * esperado, "faltan": max(target - logrado, 0.0),
            "estado": estado, "estado_txt": ESTADO_AVANCE_TXT[estado],
        })
    return pd.DataFrame(filas)


# ----------------------------------------------------------------------------- Club Faro (Peñaflor)
def tipo_cliente(rubro_cod) -> str:
    """AS (autoservicio) o TRAD (kioscos, maxikioscos, almacenes, etc.) según el rubro del cliente en SIGMA."""
    return "AS" if str(rubro_cod).strip() in N.RUBROS_AS else "TRAD"


def club_faro_compras(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, dim_cliente: pd.DataFrame,
                      cfg_art: pd.DataFrame, inicio: date, corte: date) -> pd.DataFrame:
    """Compras que cuentan para Club Faro: una fila por (vendedor, línea, cliente, artículo) entre `inicio` y `corte`.

    Compra válida = ítem de `ventas_para_objetivos` que no es nota de crédito y tiene unidades > 0 (con 1 unidad alcanza);
    solo artículos con INCLUIR = S. El cliente tiene que ser del tipo que pide la línea (AS o TRAD según su rubro).
    Las NC no descuentan clientes (misma convención que la cobertura de Unilever)."""
    v = T.ventas_para_objetivos(ventas, dim_articulo)
    f = pd.to_datetime(v["fecha"])
    v = v[(f >= pd.Timestamp(inicio)) & (f <= pd.Timestamp(corte)) & ~v["es_nc"].astype(bool) & (v["unidades"] > 0)]
    art = cfg_art[cfg_art["incluir"].astype(bool)][["articulo_id", "linea"]].rename(columns={"linea": "linea_cf"}).assign(
        articulo_id=lambda d: d["articulo_id"].astype("string"))   # `linea` ya existe en ventas (línea de SIGMA)
    v = v.assign(articulo_id=v["articulo_id"].astype("string"), vendedor_id=v["vendedor_id"].astype("string"),
                 cliente_id=v["cliente_id"].astype("string"))
    v = v.merge(art, on="articulo_id", how="inner")
    rubro = dim_cliente.drop_duplicates("cliente_id").assign(cliente_id=lambda d: d["cliente_id"].astype("string")) \
        .set_index("cliente_id")["rubro_cod"]
    v["tipo_cliente"] = v["cliente_id"].map(rubro).map(tipo_cliente)
    v = v[v["tipo_cliente"] == v["linea_cf"].map(lambda k: N.CLUB_FARO_LINEAS[k]["tipo_cliente"])]
    return v[["vendedor_id", "linea_cf", "cliente_id", "articulo_id"]].rename(columns={"linea_cf": "linea"}) \
        .drop_duplicates().reset_index(drop=True)


def club_faro_vendedores(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, dim_cliente: pd.DataFrame,
                         dim_vendedor: pd.DataFrame, cfg_art: pd.DataFrame, obj: pd.DataFrame,
                         inicio: date, fin: date, corte: date) -> tuple[pd.DataFrame, dict]:
    """Avance de Club Faro por vendedor y línea contra su objetivo (clientes con compra) y lo que falta.

    Líneas con modo `clientes`: clientes distintos con compra. Línea `cliente_sku` (blancos dulces): cada par
    (cliente, SKU) suma 1. Devuelve (tabla, resumen); la tabla trae una fila por (vendedor con objetivo × línea), con
    las mismas columnas de semáforo que cobertura (`logrado`, `objetivo`, `avance`, `esperado_valor`, `faltan`, `estado`)."""
    compras = club_faro_compras(ventas, dim_articulo, dim_cliente, cfg_art, inicio, corte)
    logrado = {}
    for (vid, linea), g in compras.groupby(["vendedor_id", "linea"]):
        modo = N.CLUB_FARO_LINEAS[linea]["modo"]
        logrado[(str(vid), linea)] = int(g["cliente_id"].nunique() if modo == "clientes" else len(g))
    esperado = fraccion_esperada(inicio, fin, corte)
    nombres = (dim_vendedor.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype("string"))
               .set_index("vendedor_id")["nombre"].to_dict()) if len(dim_vendedor) else {}
    filas = []
    for r in obj[obj["vendedor_id"].astype(str) != ""].itertuples():
        vid, linea = str(r.vendedor_id), str(r.linea)
        lg = logrado.get((vid, linea), 0)
        objetivo = float(r.objetivo)
        avance = lg / objetivo if objetivo else 0.0
        estado = estado_avance(avance, esperado)
        filas.append({
            "vendedor_id": vid, "vendedor": nombres.get(vid) or r.nombre_excel, "nombre_excel": r.nombre_excel,
            "supervisor": r.supervisor_excel,
            "linea": linea, "panel": N.CLUB_FARO_LINEAS[linea]["nombre"], "tipo_cliente": r.tipo_cliente,
            "logrado": lg, "objetivo": objetivo, "avance": avance, "esperado_pct": esperado,
            "esperado_valor": objetivo * esperado, "faltan": max(objetivo - lg, 0.0),
            "estado": estado, "estado_txt": ESTADO_AVANCE_TXT[estado], "supuesto": bool(r.supuesto)})
    # Vendedores de la base que compraron-vendieron la línea pero no tienen objetivo en el Excel: aparecen igual
    con_obj = {(f["vendedor_id"], f["linea"]) for f in filas}
    for (vid, linea), lg in sorted(logrado.items()):
        if (vid, linea) in con_obj or lg <= 0 or vid not in nombres:
            continue
        filas.append({
            "vendedor_id": vid, "vendedor": nombres[vid], "nombre_excel": "", "supervisor": "",
            "linea": linea, "panel": N.CLUB_FARO_LINEAS[linea]["nombre"], "tipo_cliente": N.CLUB_FARO_LINEAS[linea]["tipo_cliente"],
            "logrado": lg, "objetivo": 0.0, "avance": 0.0, "esperado_pct": float("nan"),
            "esperado_valor": 0.0, "faltan": 0.0,
            "estado": "sin_objetivo", "estado_txt": ESTADO_CF_TXT["sin_objetivo"], "supuesto": False})
    tabla = pd.DataFrame(filas)
    por_linea = {}
    for linea in N.CLUB_FARO_LINEAS:
        sub = tabla[(tabla["linea"] == linea) & (tabla["objetivo"] > 0)] if len(tabla) else tabla
        lg, ob = (float(sub["logrado"].sum()), float(sub["objetivo"].sum())) if len(sub) else (0.0, 0.0)
        av = lg / ob if ob else 0.0
        por_linea[linea] = {"logrado": lg, "objetivo": ob, "avance": av, "faltan": max(ob - lg, 0.0),
                            "esperado_valor": ob * esperado, "estado": estado_avance(av, esperado)}
    resumen = {"inicio": inicio, "fin": fin, "corte": corte, "esperado_pct": esperado, "por_linea": por_linea,
               "periodo": str(obj["periodo"].iloc[0]) if len(obj) else ""}
    return tabla, resumen


# ----------------------------------------------------------------------------- 11 Titulares (Peñaflor, distribuidor)
def titulares_compras(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, dim_cliente: pd.DataFrame,
                      cfg_art: pd.DataFrame, inicio: date, corte: date) -> pd.DataFrame:
    """Clientes que califican en cada línea de 11 Titulares: una fila por (cliente, línea) con canal y subcanal.

    Base: `ventas_para_objetivos` sin NC (no descuentan), unidades > 0, entre `inicio` y `corte`, solo artículos con INCLUIR.
    Un cliente califica en una línea si, en UN mismo artículo de la línea, compró lo mínimo de su canal: Autoservicios y
    OP & VTK = 1 caja cerrada/bulto (unidades >= unidades por bulto); Tradicionales = 3 unidades iguales
    (`TITULARES_UNIDADES_NO_AS`)."""
    v = T.ventas_para_objetivos(ventas, dim_articulo)
    f = pd.to_datetime(v["fecha"])
    v = v[(f >= pd.Timestamp(inicio)) & (f <= pd.Timestamp(corte)) & ~v["es_nc"].astype(bool) & (v["unidades"] > 0)]
    art = cfg_art[cfg_art["incluir"].astype(bool)][["articulo_id", "linea"]].rename(columns={"linea": "linea_t"}).assign(
        articulo_id=lambda d: d["articulo_id"].astype("string"))   # `linea` ya existe en ventas (línea de SIGMA)
    v = v.assign(articulo_id=v["articulo_id"].astype("string"), cliente_id=v["cliente_id"].astype("string")).merge(
        art, on="articulo_id", how="inner")
    cols = ["cliente_id", "linea", "canal", "subcanal"]
    if v.empty:
        return pd.DataFrame(columns=cols)
    g = v.groupby(["cliente_id", "linea_t", "articulo_id"], as_index=False)["unidades"].sum()
    da = dim_articulo.drop_duplicates("articulo_id").assign(articulo_id=lambda d: d["articulo_id"].astype("string"))
    upb = da.set_index("articulo_id")["unidades_por_bulto"] if "unidades_por_bulto" in da.columns else pd.Series(dtype=float)
    g["upb"] = pd.to_numeric(g["articulo_id"].map(upb), errors="coerce").fillna(1).clip(lower=1)
    dc = dim_cliente.drop_duplicates("cliente_id").assign(cliente_id=lambda d: d["cliente_id"].astype("string")).set_index("cliente_id")
    g["rubro_cod"] = g["cliente_id"].map(dc["rubro_cod"]).astype("string")
    g["canal"] = g["rubro_cod"].map(N.canal_titulares)
    g["subcanal"] = g["rubro_cod"].map(N.TITULARES_SUBCANAL_RUBRO)
    minimo = g["upb"].where(g["canal"].isin(N.TITULARES_CANALES_POR_CAJA), float(N.TITULARES_UNIDADES_NO_AS))
    ok = g[g["unidades"] >= minimo]
    return ok.rename(columns={"linea_t": "linea"})[cols].drop_duplicates(["cliente_id", "linea"]).reset_index(drop=True)


def titulares_resumen(ventas: pd.DataFrame, dim_articulo: pd.DataFrame, dim_cliente: pd.DataFrame, cfg_art: pd.DataFrame,
                      inicio: date, fin: date, corte: date) -> dict:
    """CCC de 11 Titulares del distribuidor: por línea, por canal y por subcanal de OP & VTK, contra sus objetivos.

    Devuelve {'lineas', 'canales', 'subcanales'} (DataFrames con logrado, objetivo, avance, esperado_valor, faltan, estado)
    y 'esperado_pct'. Por canal/subcanal el logrado son clientes distintos que califican en AL MENOS una línea."""
    c = titulares_compras(ventas, dim_articulo, dim_cliente, cfg_art, inicio, corte)
    esperado = fraccion_esperada(inicio, fin, corte)

    def fila(nombre, logrado, objetivo, **extra):
        av = logrado / objetivo if objetivo else 0.0
        est = estado_avance(av, esperado) if objetivo else "sin_objetivo"
        return {**extra, "nombre": nombre, "logrado": int(logrado), "objetivo": float(objetivo), "avance": av,
                "esperado_valor": objetivo * esperado, "faltan": max(objetivo - logrado, 0.0), "estado": est,
                "estado_txt": ESTADO_CF_TXT[est]}
    lineas = pd.DataFrame([fila(i["nombre"], c.loc[c["linea"] == k, "cliente_id"].nunique(), i["objetivo"], linea=k)
                           for k, i in N.TITULARES_LINEAS.items()])
    canales = pd.DataFrame([fila(k, c.loc[c["canal"] == k, "cliente_id"].nunique(), N.TITULARES_OBJ_CANAL[k]) for k in N.TITULARES_CANALES])
    sub = [fila(k, c.loc[c["subcanal"] == k, "cliente_id"].nunique(), o) for k, o in N.TITULARES_OBJ_SUBCANAL.items()]
    return {"lineas": lineas, "canales": canales, "subcanales": pd.DataFrame(sub), "esperado_pct": esperado,
            "inicio": inicio, "fin": fin, "corte": corte}


# ----------------------------------------------------------------------------- formato (es-AR)
def fmt_pesos(x) -> str:
    """$ 1.234.567 (punto de miles, sin decimales)."""
    if x is None or x != x:
        return "—"
    return "$ " + f"{x:,.0f}".replace(",", ".")


def fmt_millones(x, dec: int = 1) -> str:
    if x is None or x != x:
        return "—"
    return f"{x / 1e6:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".") + " M$"
