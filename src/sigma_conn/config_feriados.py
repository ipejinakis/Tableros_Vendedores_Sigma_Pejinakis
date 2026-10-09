"""Feriados del calendario de venta, cargados desde el tablero por gerentes y supervisores.

Reglas (Juan, 2026-10-09):
- Un solo calendario para toda la empresa (sin zonas).
- Un feriado resta un día de venta: baja los días de venta del mes (y del bimestre) y los transcurridos. Los objetivos, los
  escalones y los premios NO cambian; sí cambia el avance esperado a hoy, la proyección y la media diaria necesaria.
- Los domingos no se marcan (ya no son día de venta). Se marcan los feriados que caen de lunes a sábado.
- Se guardan por mes. Mes en curso y futuros editables (el del mes en curso recalcula todo el mes y el bimestre); meses
  cerrados, de solo lectura.
- Todo cambio queda en el historial (quién, cuándo, qué, motivo) y con control de versión (dos personas a la vez).

Archivos: `<data_dir>/config/feriados.json` y `historial_feriados.jsonl`.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .config_objetivos import ConfigError, ConflictoError, _LOCK, mes_de, ruta_config

_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FeriadosStore:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self.ruta = self.carpeta / "feriados.json"
        self.ruta_historial = self.carpeta / "historial_feriados.jsonl"

    def _leer(self) -> dict:
        try:
            d = json.loads(self.ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 0, "meses": {}}
        d.setdefault("meses", {})
        return d

    def _escribir(self, datos: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.ruta)

    def version(self) -> int:
        return int(self._leer().get("version", 0))

    @staticmethod
    def es_editable(mes: str, hoy: date) -> bool:
        return mes >= mes_de(hoy)

    def del_mes(self, mes: str) -> list[date]:
        return sorted(date.fromisoformat(x) for x in self._leer()["meses"].get(mes, []))

    def todos(self) -> frozenset[date]:
        return frozenset(date.fromisoformat(x) for fs in self._leer()["meses"].values() for x in fs)

    def guardar(self, actor: str, mes: str, fechas: Iterable[date], motivo: str = "",
                version_base: int | None = None, hoy: date | None = None) -> None:
        """Reemplaza los feriados de `mes` por `fechas`."""
        hoy = hoy or date.today()
        if not _MES.match(mes):
            raise ConfigError(f"Mes inválido: {mes!r}.")
        if not self.es_editable(mes, hoy):
            raise ConfigError(f"{mes} es un mes cerrado: solo se puede consultar.")
        nuevas = sorted(set(fechas))
        for f in nuevas:
            if mes_de(f) != mes:
                raise ConfigError(f"{f:%d/%m/%Y} no pertenece a {mes}.")
            if f.weekday() == 6:
                raise ConfigError(f"{f:%d/%m/%Y} es domingo: los domingos no son día de venta, no hace falta marcarlos.")
        with _LOCK:
            datos = self._leer()
            if version_base is not None and int(datos.get("version", 0)) != int(version_base):
                raise ConflictoError("Otra persona guardó cambios mientras editabas. Recargá y volvé a aplicar tu cambio.")
            antes = {date.fromisoformat(x) for x in datos["meses"].get(mes, [])}
            ahora = set(nuevas)
            cambios = ([{"campo": f"Feriado {f:%d/%m/%Y}", "antes": "día de venta", "despues": "feriado"} for f in sorted(ahora - antes)] +
                       [{"campo": f"Feriado {f:%d/%m/%Y}", "antes": "feriado", "despues": "día de venta"} for f in sorted(antes - ahora)])
            if not cambios:
                raise ConfigError("No hay cambios para guardar.")
            if nuevas:
                datos["meses"][mes] = [f.isoformat() for f in nuevas]
            else:
                datos["meses"].pop(mes, None)
            datos["version"] = int(datos.get("version", 0)) + 1
            self._escribir(datos)
            self._historial({"cuando": _ahora(), "actor": actor, "mes": mes, "motivo": motivo.strip(),
                             "version": datos["version"], "cambios": cambios})

    def _historial(self, registro: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with self.ruta_historial.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    def historial(self, mes: str | None = None, limite: int = 300) -> list[dict]:
        try:
            lineas = self.ruta_historial.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        out = []
        for ln in reversed(lineas):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if mes in (None, r.get("mes")):
                out.append(r)
            if len(out) >= limite:
                break
        return out


def store_por_defecto() -> FeriadosStore:
    return FeriadosStore(ruta_config())


def feriados_vigentes(store: FeriadosStore | None = None) -> frozenset[date]:
    """Todos los feriados cargados. Si el archivo no se puede leer devuelve vacío: el tablero nunca se rompe por esto."""
    try:
        return (store or store_por_defecto()).todos()
    except Exception:  # noqa: BLE001
        return frozenset()
