import pytest

from sigma_conn.client import SigmaClient, SigmaError, SigmaResponseTooLarge
from sigma_conn.config import Settings


def settings(**kw):
    base = dict(base_url="https://x/api/v10", token="SECRETTOKEN", data_dir=".", store_format="csv",
                window_days=35, chunk_days=7, min_interval_s=0, timeout_s=5, paginate=False, page_size=2)
    base.update(kw)
    from pathlib import Path
    base["data_dir"] = Path(base["data_dir"])
    return Settings(**base)


class Resp:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, text

    def json(self):
        if self._body is _BAD:
            raise ValueError("no json")
        return self._body


_BAD = object()


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def client(responses, **kw):
    sleeps = []
    c = SigmaClient(settings(**kw), session=FakeSession(responses), sleep=sleeps.append)
    return c, sleeps


def test_solo_lectura_bloquea_import_y_modificacion():
    c, _ = client([])
    for ep in ("ImportPedidos", "ModificacionCliente", "ImportFactura", "../ExportClientes", "help"):
        with pytest.raises(ValueError):
            c.get_json(ep)


def test_token_va_en_header_y_falta_token_falla():
    c, _ = client([Resp(body=[])])
    assert c.session.headers["X-Auth-Token"] == "SECRETTOKEN"
    with pytest.raises(SigmaError):
        SigmaClient(settings(token=""))


def test_429_respeta_retry_after_y_reintenta():
    c, sleeps = client([Resp(429, headers={"X-Retry-After-ms": "2500"}), Resp(body=[{"id": 1}])])
    assert c.get_json("ExportVendedores") == [{"id": 1}]
    assert 2.5 in sleeps


def test_429_persistente_falla():
    c, _ = client([Resp(429)] * 20)
    with pytest.raises(SigmaError, match="429"):
        c.get_json("ExportVendedores")


def test_401_no_reintenta():
    c, _ = client([Resp(401)])
    with pytest.raises(SigmaError, match="401"):
        c.get_json("ExportVendedores")
    assert len(c.session.calls) == 1


def test_500_reintenta_y_no_filtra_el_token():
    c, _ = client([Resp(500, text="boom SECRETTOKEN")] * 5)
    with pytest.raises(SigmaError) as e:
        c.get_json("ExportVendedores")
    assert "SECRETTOKEN" not in str(e.value)


def test_dict_se_envuelve_y_mensaje_de_error_con_200_falla():
    c, _ = client([Resp(body={"id": 5, "x": 1})])
    assert c.get_json("ExportClientes") == [{"id": 5, "x": 1}]
    c, _ = client([Resp(body={"message": "algo salió mal"})])
    with pytest.raises(SigmaError):
        c.get_json("ExportClientes")


def test_respuesta_no_json_falla():
    c, _ = client([Resp(body=_BAD, text="<html>")])
    with pytest.raises(SigmaError, match="JSON"):
        c.get_json("ExportClientes")


def test_paginacion_funciona_y_corta_si_page_es_ignorado():
    pages = [Resp(body=[{"id": 1}, {"id": 2}]), Resp(body=[{"id": 3}, {"id": 4}]), Resp(body=[{"id": 5}])]
    c, _ = client(pages, paginate=True, page_size=2)
    assert [r["id"] for r in c.get_all("ExportClientes")] == [1, 2, 3, 4, 5]

    same = [Resp(body=[{"id": 1}, {"id": 2}])] * 5  # la API ignora 'page'
    c, _ = client(same, paginate=True, page_size=2)
    assert len(c.get_all("ExportClientes")) == 2


def test_settings_repr_no_muestra_token():
    assert "SECRETTOKEN" not in repr(settings())


def test_response_too_large_no_se_reintenta():
    c, sleeps = client([Resp(500, text="Response size exceeded, max: 204800KB")] * 5)
    with pytest.raises(SigmaResponseTooLarge):
        c.get_json("ExportArticulosVendidos", {"dde": "2026-04-01", "hta": "2026-09-30"})
    assert len(c.session.calls) == 1 and sleeps == []
