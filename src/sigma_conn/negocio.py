"""Reglas de negocio de los tableros (decididas por Juan, ver docs del proyecto).

Solo códigos y números de configuración: nada de datos de clientes ni de ventas.
"""
from __future__ import annotations

# ----------------------------------------------------------------------------- perfiles y escalas
PERFIL_GENERAL, PERFIL_AASS, PERFIL_INTERIOR = "GENERAL", "AASS", "INTERIOR"

# Perfil de facturación de cada vendedor (Excel: hojas OBJ_FACT_EMPRESA / premios).
# Juan confirmó AASS = 100 y 119, Interior = 120 y 111. Los demás preventistas van con la escala GENERAL;
# 122 (Fili) se asumió GENERAL (a confirmar). 124, 126, 118 y el resto no tienen escala de preventa.
VENDEDOR_PERFIL: dict[str, str] = {
    "100": PERFIL_AASS, "119": PERFIL_AASS,
    "120": PERFIL_INTERIOR, "111": PERFIL_INTERIOR,
    **{v: PERFIL_GENERAL for v in ("101", "102", "103", "105", "107", "110", "114", "115", "117", "122")},
}

# Escalas de venta neta mensual SIN IVA y premio en $ (los 3 escalones pagan 200.000 / 400.000 / 600.000).
PREMIOS_ESCALON = (200_000, 400_000, 600_000)
ESCALAS_FACTURACION: dict[str, tuple[int, int, int]] = {
    PERFIL_GENERAL: (50_000_000, 60_000_000, 72_000_000),   # la escala de 25 M$ NO existe
    PERFIL_AASS: (100_000_000, 120_000_000, 144_000_000),
    PERFIL_INTERIOR: (60_000_000, 70_000_000, 85_000_000),
}

# Reparto teórico de la facturación por marca (Excel OBJ_FACT_EMPRESA). Interior no trae reparto en el Excel.
MARCAS = ("PEÑAFLOR", "UNILEVER", "PALAU", "ENERGIZER", "LEDESMA", "CEREALES")
MIX_MARCA: dict[str, dict[str, float]] = {
    PERFIL_GENERAL: dict(zip(MARCAS, (0.30, 0.60, 0.03, 0.02, 0.02, 0.03))),
    PERFIL_AASS: dict(zip(MARCAS, (0.20, 0.70, 0.03, 0.02, 0.02, 0.03))),
}
_MARCA_KEYWORDS = {"PEÑAFLOR": "PEÑAFLOR", "UNILEVER": "UNILEVER", "PALAU": "PALAU", "YUANFEN": "PALAU",
                   "ENERGIZER": "ENERGIZER", "LEDESMA": "LEDESMA", "CEREALES": "CEREALES"}


def marca_de_proveedor(proveedor) -> str | None:
    """Marca de objetivos a partir del nombre de proveedor de SIGMA (None si no es una de las 6)."""
    if proveedor is None or proveedor != proveedor:  # None o NaN/NA
        return None
    p = str(proveedor).upper()
    for kw, marca in _MARCA_KEYWORDS.items():
        if kw in p:
            return marca
    return None


# ----------------------------------------------------------------------------- supervisores
# El supervisor de los tableros sale de acá, NO de SIGMA (Fili/122 va con Mauro Amaya).
SUPERVISORES: dict[str, str] = {"5": "AMAYA MAURO", "3": "BULDURINI NATALIA"}
SUPERVISOR_VENDEDOR: dict[str, str] = {
    **{v: "5" for v in ("100", "101", "103", "105", "107", "115", "120", "122")},
    **{v: "3" for v in ("102", "110", "111", "114", "117", "119")},
}

# ----------------------------------------------------------------------------- cobertura Unilever
CATEGORIAS_COBERTURA = ("BPC", "FOOD", "HC")
# Grupos de la hoja OBJ_COBERTURA (SEP-OCT): el total de la distribuidora se reparte así.
COBERTURA_GRUPOS = {
    "PREVENTA": ("101", "102", "103", "105", "107", "110", "114", "115", "117"),  # 9 preventistas generales
    "AASS": ("100", "119"),   # el objetivo del Excel es del grupo: se reparte parejo entre los 2
    "EMILIA": ("120",),
    "FILI": ("122",),
}

# ----------------------------------------------------------------------------- calendario de objetivo
DIAS_OBJETIVO_MES = 26  # objetivo diario = objetivo mensual / 26 (lunes a sábado; feriados sin tratamiento)


# Nombres para mostrar de las campañas de Mis Ventas (claves de `campana_clave` en objetivos_excel.py)
CAMPANA_NOMBRE = {
    "DOVE_180ML": "Dove 180 ml",
    "HELLMANNS_SAB_LIV": "Hellmann's saborizada + liviana",
    "REXONA_AERO": "Rexona aero",
    "VIM_BLOQUE": "Vim bloque",
}


# ----------------------------------------------------------------------------- Club Faro (Peñaflor), sep–oct 2026
# Objetivos de COBERTURA: clientes que compran (aunque sea 1 unidad) artículos de cada línea. Los de autoservicio (AS) y
# los de kioscos + tradicional (K+T / TRAD / almacén) se distinguen por el rubro del cliente en SIGMA (confirmado por Juan).
RUBROS_AS = ("01", "98", "70")   # 01 Autoservicio, 98 AAS Gold, 70 Cadena SAR; el resto de los rubros es TRAD

CLUB_FARO_LINEAS = {
    "SMIRNOFF": {"nombre": "K+T · Familia Smirnoff", "tipo_cliente": "TRAD", "modo": "clientes"},
    "BLANCOS_DULCES": {"nombre": "AS · Blancos dulces (cada SKU suma 1)", "tipo_cliente": "AS", "modo": "cliente_sku"},
    "FRIZZE": {"nombre": "AS · Familia Frizze", "tipo_cliente": "AS", "modo": "clientes"},
}


def club_faro_linea(texto) -> str:
    """Clave de línea a partir del encabezado/nombre del Excel ("K+T - FAMILIA SMIRNOFF", "AS - BLANCOS DULCES (...)")."""
    t = str(texto).upper()
    if "SMIRNOFF" in t:
        return "SMIRNOFF"
    if "BLANCO" in t:
        return "BLANCOS_DULCES"
    if "FRIZZE" in t:
        return "FRIZZE"
    raise ValueError(f"línea de Club Faro desconocida: {texto!r}")


def clave_nombre(nombre) -> str:
    """Nombre normalizado para cruzar personas entre archivos: sin tildes ni Ñ, '?' (Ñ rota) como N, tokens ordenados."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nombre).upper().replace("?", "N"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(sorted(s.replace(".", " ").split()))

# Los códigos de vendedor de Club Faro NO se escriben a mano: se cruzan por nombre contra `dim_vendedor` (la base) en
# `objetivos_excel.build_obj_club_faro`. Lo que figure en el Excel y no esté en la base se avisa y queda afuera.
CLUB_FARO_UMBRAL_NOMBRE = 0.85   # similitud mínima para aceptar un nombre "aproximado" (p. ej. GONZALBEZ vs GONZALBES)
# Cruces aproximados que Juan confirmó a mano (2026-10-05): nombre del Excel (sin tildes, "?"=Ñ) -> id en la base.
# Solo vale si ese id existe en dim_vendedor; no inventa vendedores.
CLUB_FARO_NOMBRES_CONFIRMADOS = {"MIGUEL GONZALBEZ": "100"}
