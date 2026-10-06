"""Lectura del Excel de objetivos (`DATOS PARA REPORTE COMERCIAL.xlsx`) a tablas.

- Cobertura Unilever (hoja OBJ_COBERTURA, SEP-OCT): total de la distribuidora por categoría y reparto por grupo.
- Mis Ventas (hojas TARGET_AX_UNIL_*): cobertura y volumen por campaña y vendedor.
Los nombres de personas del Excel NO se usan (mandan los códigos de vendedor).
"""
from __future__ import annotations

import pandas as pd

from . import negocio as N

PERIODO_COBERTURA = "2026-09/2026-10"
PERIODO_MIS_VENTAS = "2026-09/2026-10"


def build_obj_cobertura(wb) -> pd.DataFrame:
    """Objetivo de clientes con compra por vendedor y categoría (BPC/FOOD/HC) para el bimestre.

    Hoja OBJ_COBERTURA, filas 7-9: C=total distribuidora, G=AASS (grupo de 2), I=Emilia AC, K=Fili y
    N=resto para los preventistas generales (se reparte entre los 9)."""
    ws = wb["OBJ_COBERTURA"]
    rows = []
    for r in (7, 8, 9):
        cat = str(ws[f"B{r}"].value).strip().upper()
        if cat not in N.CATEGORIAS_COBERTURA:
            raise ValueError(f"OBJ_COBERTURA!B{r}: categoría inesperada {cat!r}")
        total, aass, emilia, fili = (float(ws[f"{c}{r}"].value) for c in ("C", "G", "I", "K"))
        resto = total - aass - emilia - fili
        por_grupo = {"PREVENTA": resto / len(N.COBERTURA_GRUPOS["PREVENTA"]),
                     "AASS": aass / len(N.COBERTURA_GRUPOS["AASS"]), "EMILIA": emilia, "FILI": fili}
        for grupo, vendedores in N.COBERTURA_GRUPOS.items():
            for v in vendedores:
                rows.append({"vendedor_id": v, "categoria": cat, "grupo": grupo, "objetivo": por_grupo[grupo],
                             "total_distribuidora": total, "periodo": PERIODO_COBERTURA})
    return pd.DataFrame(rows)


def campana_clave(nombre: str) -> str:
    n = str(nombre).upper()
    if "DOVE" in n:
        return "DOVE_180ML"
    if "SABORIZADA" in n or "H`S" in n or "HELLMAN" in n:
        return "HELLMANNS_SAB_LIV"
    if "REXONA" in n:
        return "REXONA_AERO"
    if "VIM" in n:
        return "VIM_BLOQUE"
    raise ValueError(f"campaña desconocida en el Excel: {nombre!r}")


def build_obj_mis_ventas(wb) -> pd.DataFrame:
    """Targets de Mis Ventas (hojas TARGET_AX_UNIL_*): A=campaña, B=tipo, C=supervisor, D=vendedor, F=target,
    G=remanente. Las filas de datos empiezan en la 5."""
    rows = []
    for ws in wb.worksheets:
        if not ws.title.strip().upper().startswith("TARGET_AX_UNIL"):
            continue
        for r in range(5, ws.max_row + 1):
            camp, tipo, sup, emp, _nombre, target, rem = (ws.cell(r, c).value for c in range(1, 8))
            if camp is None or emp is None or target is None:
                continue
            rows.append({"campana": campana_clave(camp), "campana_excel": str(camp).strip(),
                         "tipo": str(tipo).strip().upper(), "supervisor_id": str(int(sup)),
                         "vendedor_id": str(int(emp)), "target": float(target),
                         "remanente": None if rem is None else float(rem), "periodo": PERIODO_MIS_VENTAS})
    df = pd.DataFrame(rows)
    if not df.empty and not set(df["tipo"]) <= {"COBERTURA", "VOLUMEN"}:
        raise ValueError(f"tipo de objetivo inesperado: {sorted(set(df['tipo']))}")
    return df


def build_cfg_campana_articulo(wb, hoja: str | None = None) -> pd.DataFrame:
    """Artículos de cada campaña de Mis Ventas, desde el Excel de clasificación de campañas.

    Hoja: `hoja` si se pasa; si no, `Campanas_candidatos` cuando existe, y si no la primera hoja
    (el archivo `articulos_en_campana.xlsx` trae una sola, `Hoja1`).
    Columnas leídas por encabezado: CAMPAÑA, ARTICULO_ID, DESCRIPCION, INCLUIR (S / N) y, opcional, SUGERENCIA.
    Regla de Juan (2026-10-02): mientras `INCLUIR` esté vacío el artículo cuenta como **S** (provisorio); cuando
    Juan completa la columna con S o N, manda lo que puso. Se pueden agregar filas al final con su ARTICULO_ID.
    Varias filas de campaña pueden apuntar a la misma clave (p. ej. "VIM BLOQUE (MOCHILA)" y
    "VIM BLOQUE (pastilla / mochila)" son ambas `VIM_BLOQUE`); un artículo repetido se resuelve por la última fila."""
    if hoja is None:
        hoja = "Campanas_candidatos" if "Campanas_candidatos" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[hoja]
    cab = {str(c.value).strip().upper(): i for i, c in enumerate(ws[1]) if c.value is not None}
    def col(prefijo, obligatoria=True):
        for k, i in cab.items():
            if k.startswith(prefijo):
                return i
        if obligatoria:
            raise ValueError(f"{hoja}: falta la columna {prefijo!r}")
        return None
    i_camp, i_id, i_desc, i_inc = col("CAMPA"), col("ARTICULO_ID"), col("DESCRIPCION"), col("INCLUIR")
    i_sug = col("SUGERENCIA", obligatoria=False)
    rows = []
    for fila in ws.iter_rows(min_row=2, values_only=True):
        if fila[i_id] is None or fila[i_camp] is None:
            continue
        inc = None if fila[i_inc] is None else str(fila[i_inc]).strip().upper()
        if inc not in (None, "", "S", "N"):
            raise ValueError(f"{hoja}: INCLUIR debe ser S o N (artículo {fila[i_id]}: {inc!r})")
        rows.append({
            "articulo_id": str(fila[i_id]).strip(), "campana": campana_clave(fila[i_camp]),
            "descripcion": str(fila[i_desc] or "").strip(),
            "sugerencia": "" if i_sug is None or fila[i_sug] is None else str(fila[i_sug]).strip().upper(),
            "incluir": inc != "N", "fuente": "INCLUIR" if inc in ("S", "N") else "por defecto (S)",
            "periodo": PERIODO_MIS_VENTAS})
    df = pd.DataFrame(rows, columns=["articulo_id", "campana", "descripcion", "sugerencia", "incluir", "fuente", "periodo"])
    return df.drop_duplicates(subset=["articulo_id", "campana"], keep="last").reset_index(drop=True)


# ----------------------------------------------------------------------------- Club Faro (Peñaflor)
def cruzar_vendedores_por_nombre(nombres, dim_vendedor: pd.DataFrame) -> dict:
    """Cruza nombres de personas (de un Excel) con `dim_vendedor` (la base). Devuelve, por nombre:
    (vendedor_id, coincidencia, nombre_en_base, similitud). `coincidencia` es "exacta" (mismo nombre sin tildes y sin
    importar el orden), "aproximada" (similitud >= CLUB_FARO_UMBRAL_NOMBRE: típico error de tipeo, hay que mirarla) o
    "sin coincidencia" (vendedor_id vacío; en `nombre_en_base` va el más parecido, solo informativo)."""
    import difflib
    base, por_id = {}, {}
    for r in dim_vendedor.itertuples():
        if isinstance(r.nombre, str) and r.nombre.strip():
            base.setdefault(N.clave_nombre(r.nombre), (str(r.vendedor_id), r.nombre))
            por_id.setdefault(str(r.vendedor_id), r.nombre)
    confirmados = {N.clave_nombre(k): v for k, v in N.CLUB_FARO_NOMBRES_CONFIRMADOS.items()}
    out = {}
    for n in nombres:
        k = N.clave_nombre(n)
        if k not in base and confirmados.get(k) in por_id:      # cruce aproximado ya confirmado por Juan
            out[n] = (confirmados[k], "confirmada", por_id[confirmados[k]], 1.0)
            continue
        if k in base:
            out[n] = (base[k][0], "exacta", base[k][1], 1.0)
            continue
        mejor, score = None, 0.0
        for b in base:
            sc = difflib.SequenceMatcher(None, k, b).ratio()
            if sc > score:
                mejor, score = b, sc
        if mejor and score >= N.CLUB_FARO_UMBRAL_NOMBRE:
            out[n] = (base[mejor][0], "aproximada", base[mejor][1], round(score, 2))
        else:
            out[n] = ("", "sin coincidencia", base[mejor][1] if mejor else "", round(score, 2))
    return out


def build_obj_club_faro(wb, hoja: str | None = None, dim_vendedor: pd.DataFrame | None = None) -> pd.DataFrame:
    """Objetivos de Club Faro por vendedor y línea (`Objetivos Club Faro Sept Oct 2026.xlsx`).

    De este Excel solo se toman los OBJETIVOS (y el nombre para ubicar al vendedor): el código del vendedor sale de la
    base (`dim_vendedor`, obligatoria) cruzando por nombre. Columnas: vendedor_id (vacío si el nombre no está en la
    base), nombre_excel, nombre_base, coincidencia, supervisor_excel, linea, objetivo, tipo_cliente, supuesto (True si el
    cruce fue aproximado), periodo.
    Una fila del Excel por vendedor; las columnas de objetivo son las líneas (encabezados que empiezan con K+T o AS).
    Solo la distribuidora de Peñaflor (se ignora la de Jujuy). Objetivo vacío = la línea no aplica (no genera fila)."""
    if dim_vendedor is None:
        raise ValueError("build_obj_club_faro necesita dim_vendedor: los códigos de vendedor salen de la base")
    if hoja is None:
        hoja = wb.sheetnames[0]
    ws = wb[hoja]
    cab = [("" if c.value is None else str(c.value).strip()) for c in ws[1]]
    def idx(pref):
        for i, c in enumerate(cab):
            if c.upper().startswith(pref):
                return i
        raise ValueError(f"{hoja}: falta la columna {pref!r}")
    i_dist, i_sup, i_ven = idx("DISTRIBUIDORA"), idx("SUPERVISOR"), idx("VENDEDORES")
    i_lineas = [(i, N.club_faro_linea(c)) for i, c in enumerate(cab) if c.upper().startswith(("K+T", "AS -", "AS+"))]
    filas = [f for f in ws.iter_rows(min_row=2, values_only=True)
             if f[i_ven] is not None and "JUJUY" not in str(f[i_dist] or "").upper()]
    cruce = cruzar_vendedores_por_nombre([str(f[i_ven]).strip() for f in filas], dim_vendedor)
    rows = []
    for fila in filas:
        nombre = str(fila[i_ven]).strip()
        vid, coinc, nombre_base, _score = cruce[nombre]
        for i, linea in i_lineas:
            if fila[i] is None:
                continue
            rows.append({"vendedor_id": vid, "nombre_excel": nombre.replace("?", "Ñ"), "nombre_base": nombre_base,
                         "coincidencia": coinc, "supervisor_excel": str(fila[i_sup] or "").strip(), "linea": linea,
                         "objetivo": float(fila[i]), "tipo_cliente": N.CLUB_FARO_LINEAS[linea]["tipo_cliente"],
                         "supuesto": coinc == "aproximada", "periodo": PERIODO_MIS_VENTAS})
    return pd.DataFrame(rows, columns=["vendedor_id", "nombre_excel", "nombre_base", "coincidencia", "supervisor_excel",
                                       "linea", "objetivo", "tipo_cliente", "supuesto", "periodo"])


def build_cfg_club_faro_articulo(wb, hoja: str | None = None) -> pd.DataFrame:
    """Artículos de cada línea de Club Faro (`articulos_club_faro.xlsx`): LINEA CLUB FARO, ARTICULO_ID, DESCRIPCION,
    INCLUIR (S / N). INCLUIR vacío = cuenta (provisorio), igual que en las campañas; S/N manda. Valor inválido → error."""
    if hoja is None:
        hoja = "Hoja1" if "Hoja1" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[hoja]
    cab = {str(c.value).strip().upper(): i for i, c in enumerate(ws[1]) if c.value is not None}
    def col(pref):
        for k, i in cab.items():
            if k.startswith(pref):
                return i
        raise ValueError(f"{hoja}: falta la columna {pref!r}")
    i_lin, i_id, i_desc, i_inc = col("LINEA CLUB"), col("ARTICULO_ID"), col("DESCRIPCION"), col("INCLUIR")
    rows = []
    for fila in ws.iter_rows(min_row=2, values_only=True):
        if fila[i_id] is None or fila[i_lin] is None:
            continue
        inc = None if fila[i_inc] is None else str(fila[i_inc]).strip().upper()
        if inc not in (None, "", "S", "N"):
            raise ValueError(f"{hoja}: INCLUIR debe ser S o N (artículo {fila[i_id]}: {inc!r})")
        rows.append({"linea": N.club_faro_linea(fila[i_lin]), "articulo_id": str(fila[i_id]).strip(),
                     "descripcion": str(fila[i_desc] or "").strip(), "incluir": inc != "N",
                     "fuente": "INCLUIR" if inc in ("S", "N") else "por defecto (S)", "periodo": PERIODO_MIS_VENTAS})
    df = pd.DataFrame(rows, columns=["linea", "articulo_id", "descripcion", "incluir", "fuente", "periodo"])
    return df.drop_duplicates(subset=["linea", "articulo_id"], keep="last").reset_index(drop=True)


def build_cfg_11_titulares_articulo(wb, hoja: str = "Articulos") -> pd.DataFrame:
    """Artículos de cada línea de 11 Titulares (`articulos_11_titulares.xlsx`, hoja Articulos): LINEA 11 TITULARES,
    ARTICULO_ID, DESCRIPCION, INCLUIR (S / N). INCLUIR vacío = cuenta (provisorio); S/N manda. Valor inválido → error."""
    ws = wb[hoja]
    cab = {str(c.value).strip().upper(): i for i, c in enumerate(ws[1]) if c.value is not None}
    def col(pref):
        for k, i in cab.items():
            if k.startswith(pref):
                return i
        raise ValueError(f"{hoja}: falta la columna {pref!r}")
    i_lin, i_id, i_desc, i_inc = col("LINEA"), col("ARTICULO_ID"), col("DESCRIPCION"), col("INCLUIR")
    rows = []
    for fila in ws.iter_rows(min_row=2, values_only=True):
        if fila[i_id] is None or fila[i_lin] is None:
            continue
        inc = None if fila[i_inc] is None else str(fila[i_inc]).strip().upper()
        if inc not in (None, "", "S", "N"):
            raise ValueError(f"{hoja}: INCLUIR debe ser S o N (artículo {fila[i_id]}: {inc!r})")
        rows.append({"linea": N.titulares_linea(fila[i_lin]), "articulo_id": str(fila[i_id]).strip(),
                     "descripcion": str(fila[i_desc] or "").strip(), "incluir": inc != "N",
                     "fuente": "INCLUIR" if inc in ("S", "N") else "por defecto (S)", "periodo": PERIODO_MIS_VENTAS})
    df = pd.DataFrame(rows, columns=["linea", "articulo_id", "descripcion", "incluir", "fuente", "periodo"])
    return df.drop_duplicates(subset=["linea", "articulo_id"], keep="last").reset_index(drop=True)


def vendedores_fuera_de_la_base(tablas: dict, dim_vendedor: pd.DataFrame) -> pd.DataFrame:
    """Chequeo de la regla "los vendedores salen de la base": para cada tabla cargada desde un Excel o desde la config
    (`negocio.py`) con columna `vendedor_id`, lista los códigos que NO están en `dim_vendedor` o que figuran
    desactivados en SIGMA. Devuelve columnas: tabla, vendedor_id, motivo ("no está en la base" / "desactivado en la base")."""
    base = dim_vendedor.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype(str)).set_index("vendedor_id")
    activo = base["activo"].to_dict() if "activo" in base.columns else {}
    filas = []
    for nombre, df in tablas.items():
        if df is None or "vendedor_id" not in df.columns:
            continue
        for v in sorted({str(x) for x in df["vendedor_id"].dropna() if str(x).strip()}):
            if v not in base.index:
                filas.append({"tabla": nombre, "vendedor_id": v, "motivo": "no está en la base"})
            elif activo.get(v) is False:
                filas.append({"tabla": nombre, "vendedor_id": v, "motivo": "desactivado en la base"})
    return pd.DataFrame(filas, columns=["tabla", "vendedor_id", "motivo"])
