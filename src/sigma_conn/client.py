"""Cliente HTTP de solo lectura para la API Sigma v10.

Decisiones de diseño:
- Solo permite endpoints ``Export*`` (y ``CurrentTimeStamp``). El token de Api_Sigma también
  habilita Import*/Modificacion*, así que el cliente los bloquea por código.
- Secuencial: la API devuelve 429 con más de 5 requests simultáneos o dos conexiones de la
  misma IP al mismo endpoint. Se respeta ``X-Retry-After-ms``.
- El token nunca se loguea.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from .config import Settings

log = logging.getLogger(__name__)

ALLOWED_PREFIXES = ("Export", "CurrentTimeStamp")
MAX_RETRIES_429 = 8
MAX_RETRIES_5XX = 3


class SigmaError(RuntimeError):
    """Error al consultar la API Sigma."""


class SigmaResponseTooLarge(SigmaError):
    """La respuesta supera el máximo de la API (200 MB): hay que pedir un rango más chico."""


class SigmaClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not settings.token:
            raise SigmaError("Falta SIGMA_TOKEN (definirlo en .env)")
        self.s = settings
        self.session = session or requests.Session()
        self.session.headers.update({"X-Auth-Token": settings.token, "Accept": "application/json"})
        self._sleep = sleep
        self._clock = clock
        self._last_call = 0.0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _check_endpoint(endpoint: str) -> None:
        if "/" in endpoint or not endpoint.startswith(ALLOWED_PREFIXES):
            raise ValueError(
                f"Endpoint no permitido: {endpoint!r}. Este cliente es de solo lectura (Export*)."
            )

    def _throttle(self) -> None:
        wait = self.s.min_interval_s - (self._clock() - self._last_call)
        if wait > 0:
            self._sleep(wait)

    def _redact(self, text: str) -> str:
        return text.replace(self.s.token, "***") if self.s.token else text

    # ------------------------------------------------------------------ requests
    def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> list[dict]:
        """GET a un endpoint Export*. Devuelve siempre una lista de dicts."""
        self._check_endpoint(endpoint)
        url = f"{self.s.base_url}/{endpoint}"
        n429 = n5xx = 0

        while True:
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=self.s.timeout_s)
            except requests.RequestException as exc:
                n5xx += 1
                if n5xx > MAX_RETRIES_5XX:
                    raise SigmaError(f"{endpoint}: error de red: {self._redact(str(exc))}") from exc
                self._backoff(n5xx, endpoint, "error de red")
                continue
            finally:
                self._last_call = self._clock()

            if resp.status_code == 429:
                n429 += 1
                if n429 > MAX_RETRIES_429:
                    raise SigmaError(f"{endpoint}: 429 persistente tras {MAX_RETRIES_429} reintentos")
                retry_ms = resp.headers.get("X-Retry-After-ms")
                try:
                    wait = max(float(retry_ms) / 1000.0, 0.5) if retry_ms else min(2**n429, 60)
                except ValueError:
                    wait = min(2**n429, 60)
                log.warning("%s: 429, esperando %.1fs (intento %d)", endpoint, wait, n429)
                self._sleep(wait)
                continue

            if resp.status_code in (401, 403):
                raise SigmaError(f"{endpoint}: {resp.status_code} sin autorización (token inválido o sin permiso)")

            if resp.status_code >= 500 and "Response size exceeded" in resp.text[:300]:
                raise SigmaResponseTooLarge(f"{endpoint}: {self._redact(resp.text[:200])}")

            if resp.status_code >= 500:
                n5xx += 1
                if n5xx > MAX_RETRIES_5XX:
                    raise SigmaError(
                        f"{endpoint}: HTTP {resp.status_code}: {self._redact(resp.text[:200])}"
                    )
                self._backoff(n5xx, endpoint, f"HTTP {resp.status_code}")
                continue

            if resp.status_code != 200:
                raise SigmaError(f"{endpoint}: HTTP {resp.status_code}: {self._redact(resp.text[:200])}")

            return self._parse(endpoint, resp)

    def _backoff(self, attempt: int, endpoint: str, why: str) -> None:
        wait = min(5 * attempt, 30)
        log.warning("%s: %s, reintentando en %ss", endpoint, why, wait)
        self._sleep(wait)

    def _parse(self, endpoint: str, resp: requests.Response) -> list[dict]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise SigmaError(f"{endpoint}: la respuesta no es JSON: {self._redact(resp.text[:120])!r}") from exc
        if data is None:
            return []
        if isinstance(data, dict):
            # Errores con 200: {"message": "..."} / {"responseCode":..,"responseText":..}
            if data and set(data) <= {"message", "responseCode", "responseText"}:
                raise SigmaError(f"{endpoint}: {data}")
            return [data]
        if isinstance(data, list):
            return data
        raise SigmaError(f"{endpoint}: forma de respuesta inesperada ({type(data).__name__})")

    def get_all(self, endpoint: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Como get_json, paginando con page/pagesize si SIGMA_PAGINATE=true.

        Sin paginación, la API devolvió el conjunto completo del rango en las pruebas,
        por eso la carga larga se hace en ventanas de fechas chicas (ver etl.date_chunks).
        """
        if not self.s.paginate:
            return self.get_json(endpoint, params)

        rows: list[dict] = []
        first_of_prev: Any = None
        page = 1
        while True:
            p = dict(params or {}, page=page, pagesize=self.s.page_size)
            chunk = self.get_json(endpoint, p)
            if not chunk:
                break
            marker = repr(chunk[0])
            if marker == first_of_prev:  # la API ignoró 'page': evitar bucle infinito
                log.warning("%s: 'page' parece ignorado, se corta la paginación", endpoint)
                break
            first_of_prev = marker
            rows.extend(chunk)
            if len(chunk) < self.s.page_size:
                break
            page += 1
        return rows
