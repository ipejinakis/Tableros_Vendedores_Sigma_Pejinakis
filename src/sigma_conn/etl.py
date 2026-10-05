"""Pipeline: API Sigma -> tablas silver.

Dimensiones (clientes, artículos, vendedores, saldos): reemplazo completo en cada corrida.
Hechos (ventas, facturas): ventana de fechas. Cada corrida recarga los últimos
``window_days`` días para captar anulaciones y notas de crédito tardías.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Iterator

from . import transform as T
from .client import SigmaClient, SigmaResponseTooLarge
from .store import Store

log = logging.getLogger(__name__)

DIMS = ("dim_vendedor", "dim_articulo", "dim_cliente", "saldos")
FACTS = ("ventas",)


def date_chunks(dde: date, hta: date, days: int) -> Iterator[tuple[date, date]]:
    """Parte [dde, hta] en tramos de ``days`` días, sin solaparse."""
    if days < 1:
        raise ValueError("days debe ser >= 1")
    cur = dde
    while cur <= hta:
        end = min(cur + timedelta(days=days - 1), hta)
        yield cur, end
        cur = end + timedelta(days=1)


def load_dims(client: SigmaClient, store: Store, only: set[str] | None = None) -> dict[str, int]:
    out: dict[str, int] = {}

    def want(n: str) -> bool:
        return only is None or n in only

    if want("dim_vendedor"):
        rows = client.get_all("ExportVendedores")
        df = T.build_dim_vendedor(rows)
        store.write_table("dim_vendedor", df)
        out["dim_vendedor"] = len(df)
        log.info("dim_vendedor: %d", len(df))

    if want("dim_articulo"):
        # soloactivos=false: sin esto la API EXCLUYE los artículos desactivados, y sus ventas quedarían sin
        # proveedor/división (ej. artículo 2040 con 183 K$ vendidos en septiembre).
        rows = client.get_all("ExportArticulos", {"soloactivos": "false"})
        df = T.build_dim_articulo(rows)
        store.write_table("dim_articulo", df)
        out["dim_articulo"] = len(df)
        log.info("dim_articulo: %d", len(df))

    if want("dim_cliente"):
        rows = client.get_all("ExportClientes", {"soloactivos": "false"})
        df = T.build_dim_cliente(rows)
        store.write_table("dim_cliente", df)
        cv = T.build_cliente_vendedor(rows)
        store.write_table("cliente_vendedor", cv)
        out["dim_cliente"] = len(df)
        out["cliente_vendedor"] = len(cv)
        log.info("dim_cliente: %d | cliente_vendedor: %d", len(df), len(cv))

    if want("saldos"):
        rows = client.get_all("ExportClientesCtaCte")
        df = T.build_saldos(rows, date.today())
        store.write_table("saldos", df)
        out["saldos"] = len(df)
        log.info("saldos: %d", len(df))

    return out


def load_ventas(client: SigmaClient, store: Store, dde: date, hta: date, chunk_days: int) -> dict[str, int]:
    """Carga ventas + cabeceras de factura para [dde, hta] en tramos.

    La API devuelve como máximo ~200 MB por respuesta (~150.000 ítems). Si un tramo es demasiado grande
    se parte a la mitad y se reintenta (el cliente no reintenta ese error).
    """
    n_items = n_fact = 0
    pendientes = list(reversed(list(date_chunks(dde, hta, chunk_days))))
    while pendientes:
        a, b = pendientes.pop()
        params = {"dde": a.isoformat(), "hta": b.isoformat()}
        try:
            av = client.get_all("ExportArticulosVendidos", params)
        except SigmaResponseTooLarge:
            if a >= b:
                raise
            mitad = a + timedelta(days=(b - a).days // 2)
            log.warning("ventas %s..%s: respuesta demasiado grande, se parte en %s y %s", a, b, mitad,
                        mitad + timedelta(days=1))
            pendientes.append((mitad + timedelta(days=1), b))
            pendientes.append((a, mitad))
            continue
        fa = client.get_all("ExportFacturas", {**params, "items": "N"})

        ventas = T.build_fact_ventas(av, fa)
        facturas = T.build_dim_factura(fa)
        n_items += store.upsert_window("fact_ventas_item", ventas, a, b)
        n_fact += store.upsert_window("dim_factura", facturas, a, b)
        log.info("ventas %s..%s: %d ítems, %d facturas", a, b, len(ventas), len(facturas))
        if len(ventas) == 0 and (b - a).days >= 6:
            log.warning("Tramo %s..%s sin ventas: verificar que sea correcto", a, b)
    return {"fact_ventas_item": n_items, "dim_factura": n_fact}


def run(client: SigmaClient, store: Store, *, dde: date, hta: date, chunk_days: int,
        what: str = "all") -> dict:
    """Corrida completa. ``what``: all | dims | ventas."""
    if hta < dde:
        raise ValueError(f"Rango inválido: {dde}..{hta}")
    t0 = time.time()
    result: dict = {"status": "running", "desde": dde.isoformat(), "hasta": hta.isoformat(), "what": what}
    try:
        counts: dict[str, int] = {}
        if what in ("all", "dims"):
            counts.update(load_dims(client, store))
        if what in ("all", "ventas"):
            counts.update(load_ventas(client, store, dde, hta, chunk_days))
        result.update(status="ok", rows=counts)
    except Exception as exc:  # se registra y se re-lanza: el cron debe fallar de forma visible
        result.update(status="error", error=str(exc)[:500])
        raise
    finally:
        result["seconds"] = round(time.time() - t0, 1)
        store.write_meta(result)
    return result
