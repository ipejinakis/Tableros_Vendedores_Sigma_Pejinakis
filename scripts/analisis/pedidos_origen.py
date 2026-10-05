"""Averigua qué sistema emitió cada pedido (Axum / Compre Ahora / otro) cruzando contra las ventas.

Llama a 2 endpoints de SOLO LECTURA para un mes (una llamada grande por endpoint; la espera 429 cae al final):
  - ExportPedidosEnviados: pedidos que entraron por API; trae `deviceId` (sistema emisor) y `numeroPedido`
    (= `pedido_id` de las ventas).
  - ExportPedidos: todos los pedidos; trae `tipoPedido` y `datosAdicionales`.
Guarda el JSON crudo en ../muestra/ y muestra cruces contra `origen` de fact_ventas_item. No imprime
datos de clientes.

Uso (desde la raíz del repo, venv activo):
    python scripts/analisis/pedidos_origen.py --mes 2026-08
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sigma_conn.client import SigmaClient  # noqa: E402
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402
from sigma_conn.transform import ventas_validas  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--mes", default="2026-08")
a = ap.parse_args()

cfg = load_settings()
anio, mes = (int(x) for x in a.mes.split("-"))
dde = pd.Timestamp(anio, mes, 1)
hta = dde + pd.offsets.MonthEnd(0)
dde_s, hta_s = dde.strftime("%Y-%m-%d"), hta.strftime("%Y-%m-%d")
carpeta = Path(cfg.data_dir).resolve().parents[1] / "muestra"
carpeta.mkdir(exist_ok=True)
cl = SigmaClient(cfg)


def bajar(nombre: str, endpoint: str, params: dict) -> list[dict]:
    t0 = time.time()
    rows = cl.get_json(endpoint, {**params, "page": 1, "pagesize": 200000})
    print(f"{endpoint}: {len(rows):,} filas en {time.time()-t0:.0f}s", flush=True)
    (carpeta / f"{nombre}_{a.mes}.json").write_text(json.dumps(rows, ensure_ascii=False))
    return rows


env = bajar("pedidos_enviados", "ExportPedidosEnviados", {"dde": dde_s, "hta": hta_s})
ped = bajar("pedidos", "ExportPedidos", {"fechadde": dde_s, "fechahta": hta_s, "estado": "todos"})

print("\nCampos ExportPedidosEnviados:", sorted(env[0].keys()) if env else "(vacío)")
print("Campos ExportPedidos:", sorted(ped[0].keys()) if ped else "(vacío)")

st = Store(cfg.data_dir, cfg.store_format)
v = ventas_validas(st.read_facts("fact_ventas_item", dde.date(), hta.date()))
fact = (v.groupby("pedido_id", as_index=False)
        .agg(origen=("origen", "first"), neto=("importe_neto", "sum"), facturas=("factura_id", "nunique")))
fact["pedido_id"] = fact["pedido_id"].astype("int64")
pd.options.display.float_format = "{:,.0f}".format
pd.options.display.width = 200

# --- 1) deviceId de ExportPedidosEnviados
if env:
    e = pd.DataFrame(env)
    e["numeroPedido"] = pd.to_numeric(e["numeroPedido"], errors="coerce")
    print("\n== deviceId (todos los pedidos enviados del mes) ==")
    print(e["deviceId"].value_counts(dropna=False).head(30).to_string())
    m = fact.merge(e[["numeroPedido", "deviceId"]].drop_duplicates("numeroPedido"),
                   left_on="pedido_id", right_on="numeroPedido", how="left")
    m["deviceId"] = m["deviceId"].fillna("(sin match en PedidosEnviados)")
    print("\n== origen (ventas) x deviceId, neto s/IVA y cantidad de pedidos ==")
    print(m.groupby(["origen", "deviceId"]).agg(pedidos=("pedido_id", "size"), neto=("neto", "sum"))
          .sort_values("neto", ascending=False).head(40).to_string())

# --- 2) tipoPedido y claves de datosAdicionales de ExportPedidos
if ped:
    p = pd.DataFrame(ped)
    p["id"] = pd.to_numeric(p["id"], errors="coerce")
    p["da_claves"] = [",".join(sorted(d.keys())) if isinstance(d, dict) and d else "(vacío)" for d in p["datosAdicionales"]]
    print("\n== tipoPedido (todos los pedidos del mes) ==")
    print(p["tipoPedido"].value_counts(dropna=False).to_string())
    m2 = fact.merge(p[["id", "tipoPedido", "da_claves"]].drop_duplicates("id"),
                    left_on="pedido_id", right_on="id", how="left")
    m2["tipoPedido"] = m2["tipoPedido"].fillna("(sin match en Pedidos)")
    print("\n== origen (ventas) x tipoPedido x claves datosAdicionales ==")
    print(m2.groupby(["origen", "tipoPedido", "da_claves"]).agg(pedidos=("pedido_id", "size"), neto=("neto", "sum"))
          .sort_values("neto", ascending=False).head(40).to_string())
    # valores de datosAdicionales que NO son identificadores (para ver si algo dice 'axum'/'compre ahora')
    vals = Counter()
    for d in p["datosAdicionales"]:
        if isinstance(d, dict):
            for k, val in d.items():
                if k.upper() not in ("MAGENTOID", "API_ID", "DISTCODE"):
                    vals[(k, str(val)[:40])] += 1
    print("\n== valores frecuentes en datosAdicionales (excluye ids) ==")
    for (k, val), n in vals.most_common(25):
        print(f"{n:7,}  {k} = {val}")
