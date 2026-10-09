"""Configuración editable de los objetivos de Facturación (escalas, premios y perfil de cada vendedor).

Reglas (Juan, 2026-10-09):
- Cada cambio vale para un MES completo. Un mes sin configuración propia hereda la del último mes anterior que la tenga;
  si no hay ninguna, valen los valores de `negocio.py` (semilla): el tablero se ve igual hasta que alguien edite.
- El mes en curso se puede editar (recalcula todo el mes con el valor nuevo); los meses cerrados son de solo lectura.
- Edita cualquier gerente o supervisor, sin aprobación, pero todo queda registrado (quién, cuándo, qué, antes y después).
- La lista de vendedores y el equipo de cada uno (vendedor → supervisor) NO son editables acá: vienen de SIGMA / `negocio.py`.
  Tampoco se edita el perfil de cada vendedor: solo escalas y premios.

Almacenamiento: `<data_dir>/config/facturacion.json` (estado) y `historial.jsonl` (un renglón por cambio).
`subir.sh --con-datos` no toca esta carpeta. El estado lleva un número de versión: si dos personas editan a la vez,
la segunda recibe `ConflictoError` en vez de pisar el cambio de la primera.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import negocio as N

PERFILES = (N.PERFIL_GENERAL, N.PERFIL_AASS, N.PERFIL_INTERIOR)
ESCALONES = 3
_LOCK = threading.Lock()


class ConfigError(ValueError):
    """Dato inválido o cambio no permitido."""


class ConflictoError(ConfigError):
    """Alguien guardó otra versión mientras se editaba."""


# ----------------------------------------------------------------------------- configuración de un mes
@dataclass(frozen=True)
class ConfigFact:
    mes: str                                   # AAAA-MM al que se pidió
    vendedor_perfil: dict                      # {"101": "GENERAL", ...}
    escalas: dict                              # {"GENERAL": (50e6, 60e6, 72e6), ...}
    premios: tuple                             # (200_000, 400_000, 600_000)
    origen: str = "codigo"                     # "codigo" (semilla) | AAAA-MM de la config que se hereda/usa
    version: int = 0                           # versión del archivo con que se leyó (para el control de choques)
    propia: bool = field(default=False)        # True si el mes tiene configuración propia

    def a_dict(self) -> dict:
        return {"vendedor_perfil": dict(self.vendedor_perfil),
                "escalas": {p: list(e) for p, e in self.escalas.items()}, "premios": list(self.premios)}


def semilla(mes: str = "") -> ConfigFact:
    """Valores de `negocio.py`: lo que rige mientras nadie edite nada."""
    return ConfigFact(mes=mes, vendedor_perfil=dict(N.VENDEDOR_PERFIL),
                      escalas={p: tuple(e) for p, e in N.ESCALAS_FACTURACION.items()}, premios=tuple(N.PREMIOS_ESCALON))


DEFAULT = semilla()


def validar(datos: dict) -> dict:
    """Valida y normaliza {"vendedor_perfil", "escalas", "premios"}; devuelve el dict limpio o levanta ConfigError."""
    try:
        escalas = {p: [int(x) for x in datos["escalas"][p]] for p in PERFILES}
        premios = [int(x) for x in datos["premios"]]
        perfiles = {str(v).strip(): str(p).strip().upper() for v, p in datos["vendedor_perfil"].items()}
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ConfigError(f"Configuración incompleta o con valores no numéricos ({e}).") from e
    if len(premios) != ESCALONES or any(x <= 0 for x in premios) or premios != sorted(premios):
        raise ConfigError("Los 3 premios deben ser montos positivos y crecientes.")
    for p, e in escalas.items():
        if len(e) != ESCALONES or any(x <= 0 for x in e):
            raise ConfigError(f"La escala {p} necesita 3 objetivos positivos.")
        if e != sorted(e) or len(set(e)) != ESCALONES:
            raise ConfigError(f"La escala {p} debe ser creciente (escalón 1 < 2 < 3).")
    for v, p in perfiles.items():
        if not v.isdigit():
            raise ConfigError(f"Código de vendedor inválido: {v!r}.")
        if p not in PERFILES:
            raise ConfigError(f"Perfil inválido para {v}: {p!r} (usar {', '.join(PERFILES)}).")
    if not perfiles:
        raise ConfigError("Tiene que haber al menos un vendedor con escala.")
    return {"vendedor_perfil": dict(sorted(perfiles.items())), "escalas": escalas, "premios": premios}


def _a_config(mes: str, d: dict, origen: str, version: int, propia: bool) -> ConfigFact:
    return ConfigFact(mes=mes, vendedor_perfil=dict(d["vendedor_perfil"]),
                      escalas={p: tuple(e) for p, e in d["escalas"].items()}, premios=tuple(d["premios"]),
                      origen=origen, version=version, propia=propia)


def mes_de(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


# ----------------------------------------------------------------------------- almacén
class ConfigStore:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self.ruta = self.carpeta / "facturacion.json"
        self.ruta_historial = self.carpeta / "historial.jsonl"

    # --- lectura
    def _leer(self) -> dict:
        try:
            return json.loads(self.ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 0, "meses": {}}

    def _escribir(self, datos: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.ruta)

    def version(self) -> int:
        return int(self._leer().get("version", 0))

    def meses_con_config(self) -> list[str]:
        return sorted(self._leer()["meses"])

    def cargar(self, mes: str) -> ConfigFact:
        """Configuración vigente para `mes` (AAAA-MM): la propia, o la del último mes anterior, o la semilla."""
        datos = self._leer()
        ver = int(datos.get("version", 0))
        previos = [m for m in datos["meses"] if m <= mes]
        if not previos:
            base = semilla(mes)
            return ConfigFact(mes=mes, vendedor_perfil=base.vendedor_perfil, escalas=base.escalas, premios=base.premios,
                              origen="codigo", version=ver, propia=False)
        usado = max(previos)
        return _a_config(mes, datos["meses"][usado]["config"], usado, ver, propia=(usado == mes))

    # --- reglas de período
    @staticmethod
    def es_editable(mes: str, hoy: date) -> bool:
        """El mes en curso y los futuros se pueden editar; los meses cerrados, no."""
        return mes >= mes_de(hoy)

    # --- escritura
    def guardar(self, actor: str, mes: str, nueva: dict, motivo: str = "", version_base: int | None = None,
                hoy: date | None = None) -> ConfigFact:
        """Guarda la configuración completa de `mes`. `version_base` = versión que leyó quien edita (control de choques)."""
        hoy = hoy or date.today()
        if not self.es_editable(mes, hoy):
            raise ConfigError(f"El mes {mes} ya está cerrado: solo se puede consultar.")
        limpia = validar(nueva)
        with _LOCK:
            datos = self._leer()
            if version_base is not None and int(datos.get("version", 0)) != int(version_base):
                raise ConflictoError("Otra persona guardó cambios mientras editabas. Recargá y volvé a aplicar tu cambio.")
            antes = self.cargar(mes).a_dict()
            if limpia["vendedor_perfil"] != antes["vendedor_perfil"]:
                raise ConfigError("Los vendedores y su perfil no se editan acá: se administran en SIGMA y los carga el administrador.")
            if json.dumps(antes, sort_keys=True) == json.dumps(limpia, sort_keys=True) and mes in datos["meses"]:
                raise ConfigError("No hay cambios para guardar.")
            cambios = diferencias(antes, limpia)
            if not cambios:
                raise ConfigError("No hay cambios para guardar.")
            datos["version"] = int(datos.get("version", 0)) + 1
            datos["meses"][mes] = {"config": limpia, "actor": actor, "cuando": _ahora()}
            self._escribir(datos)
            self._historial({"cuando": _ahora(), "actor": actor, "mes": mes, "motivo": motivo.strip(),
                             "version": datos["version"], "cambios": cambios, "tipo": "edicion"})
        return self.cargar(mes)

    def volver_a_heredar(self, actor: str, mes: str, motivo: str = "", hoy: date | None = None) -> ConfigFact:
        """Borra la configuración propia de `mes` (vuelve a heredar la del mes anterior)."""
        hoy = hoy or date.today()
        if not self.es_editable(mes, hoy):
            raise ConfigError(f"El mes {mes} ya está cerrado: solo se puede consultar.")
        with _LOCK:
            datos = self._leer()
            if mes not in datos["meses"]:
                raise ConfigError("Ese mes no tiene configuración propia.")
            antes = datos["meses"][mes]["config"]
            del datos["meses"][mes]
            datos["version"] = int(datos.get("version", 0)) + 1
            self._escribir(datos)
            despues = self.cargar(mes).a_dict()
            self._historial({"cuando": _ahora(), "actor": actor, "mes": mes, "motivo": motivo.strip(),
                             "version": datos["version"], "cambios": diferencias(antes, despues), "tipo": "herencia"})
        return self.cargar(mes)

    # --- historial
    def _historial(self, registro: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with self.ruta_historial.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    def historial(self, mes: str | None = None, limite: int = 200) -> list[dict]:
        """Cambios más recientes primero."""
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
            if mes is None or r.get("mes") == mes:
                out.append(r)
            if len(out) >= limite:
                break
        return out


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def diferencias(antes: dict, despues: dict) -> list[dict]:
    """Lista legible de cambios: [{"campo": "Escala GENERAL · escalón 1", "antes": ..., "despues": ...}]."""
    out = []
    for p in PERFILES:
        a, d = antes["escalas"].get(p, [None] * 3), despues["escalas"].get(p, [None] * 3)
        for i in range(ESCALONES):
            if a[i] != d[i]:
                out.append({"campo": f"Escala {p} · escalón {i + 1}", "antes": a[i], "despues": d[i]})
    for i in range(ESCALONES):
        if antes["premios"][i] != despues["premios"][i]:
            out.append({"campo": f"Premio escalón {i + 1}", "antes": antes["premios"][i], "despues": despues["premios"][i]})
    va, vd = antes["vendedor_perfil"], despues["vendedor_perfil"]
    for v in sorted(set(va) | set(vd)):
        if va.get(v) != vd.get(v):
            out.append({"campo": f"Perfil del vendedor {v}", "antes": va.get(v), "despues": vd.get(v)})
    return out


# ----------------------------------------------------------------------------- acceso desde los tableros
def ruta_config() -> Path:
    from .config import load_settings
    return load_settings().data_dir / "config"


def store_por_defecto() -> ConfigStore:
    return ConfigStore(ruta_config())


def config_del_mes(mes: str, store: ConfigStore | None = None) -> ConfigFact:
    """Config de `mes`; si el almacén no se puede leer, cae a los valores del código (el tablero nunca se rompe por esto)."""
    try:
        return (store or store_por_defecto()).cargar(mes)
    except Exception:  # noqa: BLE001
        return semilla(mes)


def vendedores_con_escala(mes: str | None = None) -> list[str]:
    return sorted(config_del_mes(mes or mes_de(date.today())).vendedor_perfil)
