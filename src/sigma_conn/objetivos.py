"""Cálculos comunes de los tableros: calendario de venta, escalones de facturación, premios y avance.

Reglas (Juan): se vende de lunes a sábado; feriados sin tratamiento (un feriado es un día sin venta);
objetivo diario = objetivo mensual / 26; la facturación se mide s/IVA con `ventas_para_objetivos`.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd

from . import negocio as N
from .config_objetivos import DEFAULT as _CFG0, ConfigFact


# ----------------------------------------------------------------------------- calendario
def es_dia_de_venta(d: date) -> bool:
    return d.weekday() != 6  # lunes=0 ... sábado=5; domingo no


def dias_de_venta(desde: date, hasta: date) -> int:
    """Días lunes–sábado entre `desde` y `hasta`, ambos inclusive."""
    if hasta < desde:
        return 0
    return sum(es_dia_de_venta(desde + timedelta(days=i)) for i in range((hasta - desde).days + 1))


def _ultimo_dia(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def dias_de_venta_mes(anio: int, mes: int) -> int:
    return dias_de_venta(date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1]))


def dias_transcurridos(fecha: date) -> int:
    """Días de venta del mes desde el 1 hasta `fecha` inclusive."""
    return dias_de_venta(date(fecha.year, fecha.month, 1), fecha)


def dias_restantes(fecha: date) -> int:
    """Días de venta del mes DESPUÉS de `fecha` (no cuenta `fecha`)."""
    return dias_de_venta(fecha + timedelta(days=1), _ultimo_dia(fecha))


# ----------------------------------------------------------------------------- facturación
def objetivo_diario(objetivo_mensual: float) -> float:
    return objetivo_mensual / N.DIAS_OBJETIVO_MES


def perfil_de(vendedor_id, cfg: ConfigFact | None = None) -> str | None:
    return (cfg or _CFG0).vendedor_perfil.get(str(vendedor_id))


def evaluar_facturacion(vendido: float, perfil: str, fecha: date, cfg: ConfigFact | None = None) -> dict:
    """Estado de un vendedor frente a su escala del mes.

    `vendido`: neto s/IVA del mes hasta `fecha` (usar el último día con ventas completas).
    Devuelve el escalón alcanzado, el premio en $ y, por escalón, avance, faltante, media diaria necesaria
    con los días de venta que quedan y si la proyección al ritmo actual lo alcanza.
    """
    cfg = cfg or _CFG0
    escalas, premios = cfg.escalas[perfil], cfg.premios
    transc, rest = dias_transcurridos(fecha), dias_restantes(fecha)
    proyeccion = vendido / transc * (transc + rest) if transc else 0.0
    escalones = []
    for i, (obj, premio) in enumerate(zip(escalas, premios), start=1):
        falta = max(obj - vendido, 0.0)
        escalones.append({
            "escalon": i, "objetivo": obj, "premio": premio, "objetivo_diario": objetivo_diario(obj),
            "avance_pct": vendido / obj, "alcanzado": vendido >= obj, "faltante": falta,
            "media_necesaria": (falta / rest) if rest else (0.0 if falta == 0 else None),
            "proyeccion_alcanza": proyeccion >= obj,
        })
    logrados = [e for e in escalones if e["alcanzado"]]
    escalon = logrados[-1]["escalon"] if logrados else 0
    return {
        "perfil": perfil, "vendido": vendido, "fecha": fecha, "dias_transcurridos": transc, "dias_restantes": rest,
        "ritmo_diario": vendido / transc if transc else 0.0, "proyeccion": proyeccion,
        "escalon": escalon, "premio": premios[escalon - 1] if escalon else 0,
        "premio_proyectado": max([e["premio"] for e in escalones if e["proyeccion_alcanza"]], default=0),
        "siguiente": escalones[escalon] if escalon < len(escalones) else None, "escalones": escalones,
    }


def avance(real: float, objetivo: float) -> float | None:
    """Avance real/objetivo (None si no hay objetivo). Para cobertura y Mis Ventas."""
    return None if not objetivo else real / objetivo


# ----------------------------------------------------------------------------- tablas de configuración
def build_obj_facturacion() -> pd.DataFrame:
    rows = [{"perfil": p, "escalon": i, "objetivo_neto": obj, "premio": prem, "objetivo_diario": obj / N.DIAS_OBJETIVO_MES}
            for p, escalas in N.ESCALAS_FACTURACION.items()
            for i, (obj, prem) in enumerate(zip(escalas, N.PREMIOS_ESCALON), start=1)]
    return pd.DataFrame(rows)


def build_obj_mix_marca() -> pd.DataFrame:
    return pd.DataFrame([{"perfil": p, "marca": m, "pct": pct} for p, mix in N.MIX_MARCA.items() for m, pct in mix.items()])


def build_cfg_vendedor_perfil() -> pd.DataFrame:
    return pd.DataFrame([{"vendedor_id": v, "perfil": p, "supervisor_id": N.SUPERVISOR_VENDEDOR.get(v),
                          "supervisor": N.SUPERVISORES.get(N.SUPERVISOR_VENDEDOR.get(v, ""))}
                         for v, p in sorted(N.VENDEDOR_PERFIL.items())])


def build_cfg_supervisor_vendedor() -> pd.DataFrame:
    return pd.DataFrame([{"vendedor_id": v, "supervisor_id": s, "supervisor": N.SUPERVISORES[s]}
                         for v, s in sorted(N.SUPERVISOR_VENDEDOR.items())])
