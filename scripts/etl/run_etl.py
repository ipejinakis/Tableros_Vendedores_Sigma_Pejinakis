#!/usr/bin/env python3
"""Corre el ETL de SIGMA. Pensado para cron (06:00 y 16:00).

Ejemplos:
    python scripts/etl/run_etl.py                       # ventana móvil (SIGMA_WINDOW_DAYS) + dimensiones
    python scripts/etl/run_etl.py --desde 2026-04-01    # carga inicial de 6 meses
    python scripts/etl/run_etl.py --solo dims           # solo dimensiones
    python scripts/etl/run_etl.py --solo ventas         # solo ventas (cron de las 16:00)
    python scripts/etl/run_etl.py --solo ventas --desde 2026-09-01 --hasta 2026-09-15
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sigma_conn import SigmaClient, load_settings  # noqa: E402
from sigma_conn import etl  # noqa: E402
from sigma_conn.store import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", type=date.fromisoformat, help="YYYY-MM-DD (default: hoy - SIGMA_WINDOW_DAYS)")
    ap.add_argument("--hasta", type=date.fromisoformat, help="YYYY-MM-DD (default: hoy)")
    ap.add_argument("--solo", choices=["all", "dims", "ventas"], default="all")
    ap.add_argument("--chunk-dias", type=int, help="días por pedido a la API (default SIGMA_CHUNK_DAYS)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    s = load_settings()
    hasta = args.hasta or date.today()
    desde = args.desde or (hasta - timedelta(days=s.window_days))

    s.data_dir.mkdir(parents=True, exist_ok=True)
    lock = open(s.data_dir / ".etl.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.error("Ya hay una corrida del ETL en curso; se aborta.")
        return 2

    client = SigmaClient(s)
    store = Store(s.data_dir, s.store_format)
    logging.info("ETL SIGMA %s..%s (%s) -> %s [%s]", desde, hasta, args.solo, s.data_dir, s.store_format)
    res = etl.run(client, store, dde=desde, hta=hasta, chunk_days=args.chunk_dias or s.chunk_days, what=args.solo)
    logging.info("OK en %ss: %s", res["seconds"], res["rows"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
