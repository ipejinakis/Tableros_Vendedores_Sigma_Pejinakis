"""ETL de punta a punta con un cliente falso que sirve la muestra real filtrada por fecha."""

import json
from datetime import date

import pytest

from sigma_conn import etl
from sigma_conn.client import SigmaResponseTooLarge
from sigma_conn.store import Store


class FakeClient:
    def __init__(self, d):
        self.d = d
        self.calls = []

    def _load(self, name):
        return json.load(open(self.d / name))

    def get_all(self, endpoint, params=None):
        params = params or {}
        self.calls.append((endpoint, params))
        if endpoint in ("ExportArticulosVendidos", "ExportFacturas"):
            name = "articulos_vendidos.json" if endpoint == "ExportArticulosVendidos" else "facturas.json"
            return [r for r in self._load(name) if params["dde"] <= r["fecha"] <= params["hta"]]
        return {"ExportVendedores": self._load("vendedores.json"), "ExportArticulos": self._load("articulos.json"),
                "ExportClientes": self._load("clientes.json"), "ExportClientesCtaCte": []}[endpoint]


def test_run_completo_y_rerun_idempotente(sample_dir, tmp_path):
    store = Store(tmp_path, "csv")
    client = FakeClient(sample_dir)
    kw = dict(dde=date(2026, 9, 7), hta=date(2026, 9, 20), chunk_days=7)

    res = etl.run(client, store, **kw)
    assert res["status"] == "ok"
    ventas = store.read_facts("fact_ventas_item")
    n1 = len(ventas)
    assert n1 == 4243 and ventas["factura_id"].nunique() == 907

    etl.run(client, store, **kw)  # segunda corrida: mismo resultado, sin duplicar
    assert len(store.read_facts("fact_ventas_item")) == n1
    assert len(store.read_facts("dim_factura")) == 907

    assert len(store.read_table("dim_cliente")) == 4252
    assert store.read_meta()["status"] == "ok"
    # artículos desactivados con ventas: hay que pedirlos explícitamente
    assert ("ExportArticulos", {"soloactivos": "false"}) in client.calls
    # solo se llama a endpoints Export*
    assert all(ep.startswith("Export") for ep, _ in client.calls)


def test_error_deja_meta_en_error_y_relanza(sample_dir, tmp_path):
    class Boom(FakeClient):
        def get_all(self, endpoint, params=None):
            raise RuntimeError("API caída")

    store = Store(tmp_path, "csv")
    with pytest.raises(RuntimeError):
        etl.run(Boom(sample_dir), store, dde=date(2026, 9, 14), hta=date(2026, 9, 18), chunk_days=7)
    assert store.read_meta()["status"] == "error"


def test_tramo_demasiado_grande_se_parte_a_la_mitad(sample_dir, tmp_path):
    """Si la API responde 'Response size exceeded', el ETL parte el rango y el resultado es idéntico."""
    class Chico(FakeClient):
        def get_all(self, endpoint, params=None):
            if endpoint == "ExportArticulosVendidos":
                d0 = date.fromisoformat(params["dde"]); d1 = date.fromisoformat(params["hta"])
                if (d1 - d0).days >= 4:
                    self.calls.append((endpoint, params))
                    raise SigmaResponseTooLarge("Response size exceeded")
            return super().get_all(endpoint, params)

    base = Store(tmp_path / "a", "csv")
    etl.load_ventas(FakeClient(sample_dir), base, date(2026, 9, 7), date(2026, 9, 20), 14)
    partido = Store(tmp_path / "b", "csv")
    c = Chico(sample_dir)
    etl.load_ventas(c, partido, date(2026, 9, 7), date(2026, 9, 20), 14)
    a, b = base.read_facts("fact_ventas_item"), partido.read_facts("fact_ventas_item")
    assert len(a) == len(b) == 4243 and a["importe_neto"].sum() == pytest.approx(b["importe_neto"].sum())
    assert any(ep == "ExportArticulosVendidos" for ep, _ in c.calls)  # hubo al menos un rechazo

