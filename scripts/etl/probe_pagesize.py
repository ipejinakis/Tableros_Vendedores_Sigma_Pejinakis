"""Prueba qué tamaño de página acepta ExportArticulosVendidos y cuánto tarda (solo lectura).

Uso: python scripts/etl/probe_pagesize.py
Hace 2 llamadas grandes (cada una puede esperar ~75 s por el 429, es normal).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sigma_conn.client import SigmaClient  # noqa: E402
from sigma_conn.config import load_settings  # noqa: E402

cfg = load_settings()
cl = SigmaClient(cfg)

PRUEBAS = [  # (dde, hta, pagesize)
    ("2026-04-01", "2026-04-30", 50000),   # ~25.000 ítems: ¿entra en una sola página?
    ("2026-05-01", "2026-10-01", 200000),  # ~130.000 ítems: ¿entra todo el resto en una sola llamada?
]
for dde, hta, ps in PRUEBAS:
    t0 = time.time()
    try:
        rows = cl.get_json("ExportArticulosVendidos", {"dde": dde, "hta": hta, "page": 1, "pagesize": ps})
        dt = time.time() - t0
        print(f"{dde}..{hta} pagesize={ps}: {len(rows)} ítems en {dt:.0f}s "
              f"({'COMPLETO en 1 llamada' if len(rows) < ps else 'LLENÓ la página, hay más'})", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"{dde}..{hta} pagesize={ps}: FALLÓ tras {time.time()-t0:.0f}s: {str(exc)[:200]}", flush=True)
