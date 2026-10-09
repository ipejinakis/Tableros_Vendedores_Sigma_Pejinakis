"""Objetivos bimestrales editables: cobertura, Mis Ventas y Club Faro (objetivo por vendedor).

Mismas reglas que Facturación (`config_objetivos`), con período bimestral (ene-feb, mar-abr, …, sep-oct, …):
- Se edita el VALOR del objetivo de cada celda existente. No se suman ni se sacan vendedores, campañas ni líneas
  (los vendedores se administran en SIGMA; los equipos y las campañas las define el administrador).
- Cada cambio vale para un bimestre completo. Un bimestre sin tabla propia hereda la del último bimestre anterior que
  la tenga; si no hay ninguna, rige la tabla cargada desde el Excel (silver `obj_*`), que es la semilla.
- El bimestre en curso se edita (recalcula todo el bimestre); los cerrados son de solo lectura.
- Todo cambio queda en el historial (quién, cuándo, qué, antes y después, motivo) y en el control de versiones.

Se guarda la tabla COMPLETA de cada módulo en `<data_dir>/config/objetivos_bimestre.json` (así un bimestre nuevo hereda
todo aunque el Excel de la semilla sea de otro período) y el historial en `historial_bimestre.jsonl`.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .config_objetivos import ConfigError, ConflictoError, _LOCK, ruta_config

# módulo -> (columnas que identifican la fila, columnas de valor editables)
# (Mis Ventas y Club Faro, con campañas/líneas/artículos que cambian cada bimestre, están en `config_campanas`)
MODULOS = {
    "cobertura": (("vendedor_id", "categoria"), ("objetivo", "total_distribuidora")),
}
NOMBRE_MODULO = {"cobertura": "Cobertura"}


def bimestre_clave(d: date) -> str:
    """Primer mes (AAAA-MM) del bimestre al que pertenece `d`: sep y oct -> 2026-09."""
    m0 = d.month if d.month % 2 == 1 else d.month - 1
    return f"{d.year:04d}-{m0:02d}"


def bimestre_texto(clave: str) -> str:
    """'2026-09' -> '2026-09/2026-10' (el formato de la columna `periodo` de las tablas de objetivos)."""
    anio, m = (int(x) for x in clave.split("-"))
    return f"{clave}/{anio:04d}-{m + 1:02d}"


def siguiente_bimestre(clave: str) -> str:
    anio, m = (int(x) for x in clave.split("-"))
    m += 2
    if m > 12:
        anio, m = anio + 1, m - 12
    return f"{anio:04d}-{m:02d}"


def _limpiar(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return v.item() if hasattr(v, "item") else v


def _a_registros(df: pd.DataFrame) -> list[dict]:
    return [{k: _limpiar(v) for k, v in r.items()} for r in df.to_dict("records")]


def _a_df(registros: list[dict], base: pd.DataFrame | None = None) -> pd.DataFrame:
    cols = list(base.columns) if base is not None else None
    df = pd.DataFrame(registros, columns=cols)
    if base is not None:           # que los tipos de texto sigan siendo texto (códigos con ceros, etc.)
        for c in base.columns:
            if base[c].dtype == object:
                df[c] = df[c].astype(object)
    return df


def _clave_fila(modulo: str, fila) -> tuple:
    return tuple(str(fila[c]) for c in MODULOS[modulo][0])


class ObjetivosBimestreStore:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self.ruta = self.carpeta / "objetivos_bimestre.json"
        self.ruta_historial = self.carpeta / "historial_bimestre.jsonl"

    def _leer(self) -> dict:
        try:
            return json.loads(self.ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 0, "datos": {}}

    def _escribir(self, datos: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.ruta)

    def version(self) -> int:
        return int(self._leer().get("version", 0))

    def bimestres_con_config(self, modulo: str | None = None) -> list[str]:
        d = self._leer()["datos"]
        return sorted({p for m, ps in d.items() if modulo in (None, m) for p in ps})

    @staticmethod
    def es_editable(clave: str, hoy: date) -> bool:
        return clave >= bimestre_clave(hoy)

    # --- lectura
    def vigente(self, modulo: str, clave: str, base: pd.DataFrame | None) -> tuple[pd.DataFrame | None, str, int]:
        """Tabla vigente del módulo para el bimestre `clave`: (df, origen, versión).
        origen = AAAA-MM del bimestre de donde sale, o "excel" si rige la tabla cargada desde el Excel (`base`)."""
        datos = self._leer()
        ver = int(datos.get("version", 0))
        previos = [p for p in datos["datos"].get(modulo, {}) if p <= clave]
        if not previos:
            return base, "excel", ver
        usado = max(previos)
        df = _a_df(datos["datos"][modulo][usado]["filas"], base)
        if "periodo" in df.columns:
            df["periodo"] = bimestre_texto(clave)
        return df, usado, ver

    # --- escritura
    def guardar(self, actor: str, modulo: str, clave: str, nuevos: pd.DataFrame, base: pd.DataFrame | None,
                motivo: str = "", version_base: int | None = None, hoy: date | None = None) -> None:
        """`nuevos`: filas con las columnas clave + valores editables. Solo cambian los valores de las filas que ya existen."""
        hoy = hoy or date.today()
        if modulo not in MODULOS:
            raise ConfigError(f"Módulo desconocido: {modulo!r}.")
        if not self.es_editable(clave, hoy):
            raise ConfigError(f"El bimestre {bimestre_texto(clave)} ya está cerrado: solo se puede consultar.")
        claves, valores = MODULOS[modulo]
        with _LOCK:
            datos = self._leer()
            if version_base is not None and int(datos.get("version", 0)) != int(version_base):
                raise ConflictoError("Otra persona guardó cambios mientras editabas. Recargá y volvé a aplicar tu cambio.")
            actual, _origen, _ = self.vigente(modulo, clave, base)
            if actual is None or actual.empty:
                raise ConfigError("No hay una tabla de objetivos cargada para este bimestre.")
            actual = actual.copy()
            idx = {_clave_fila(modulo, f): i for i, f in actual.iterrows()}
            cambios = []
            for _, f in nuevos.iterrows():
                k = _clave_fila(modulo, f)
                if k not in idx:
                    raise ConfigError("Los vendedores, campañas y líneas no se editan acá: se administran en SIGMA y los carga el administrador.")
                i = idx[k]
                for col in valores:
                    if col not in nuevos.columns:
                        continue
                    nv = f[col]
                    if nv is None or nv != nv:
                        continue
                    try:
                        nv = float(nv)
                    except (TypeError, ValueError) as e:
                        raise ConfigError(f"Valor no numérico en {col}: {nv!r}.") from e
                    if nv < 0:
                        raise ConfigError("Los objetivos no pueden ser negativos.")
                    ant = float(actual.at[i, col])
                    if ant != nv:
                        cambios.append({"campo": f"{NOMBRE_MODULO[modulo]} · {' · '.join(k)} · {col}", "antes": ant, "despues": nv})
                        actual.at[i, col] = nv
            if modulo == "cobertura":
                disp = actual.groupby("categoria")["total_distribuidora"].nunique()
                if (disp > 1).any():
                    raise ConfigError("El total de la distribuidora debe ser el mismo para todos los vendedores de una categoría.")
            if not cambios:
                raise ConfigError("No hay cambios para guardar.")
            datos["version"] = int(datos.get("version", 0)) + 1
            datos["datos"].setdefault(modulo, {})[clave] = {"filas": _a_registros(actual), "actor": actor, "cuando": _ahora()}
            self._escribir(datos)
            self._historial({"cuando": _ahora(), "actor": actor, "modulo": modulo, "bimestre": clave, "motivo": motivo.strip(),
                             "version": datos["version"], "cambios": cambios, "tipo": "edicion"})

    def volver_a_heredar(self, actor: str, modulo: str, clave: str, motivo: str = "", hoy: date | None = None) -> None:
        hoy = hoy or date.today()
        if not self.es_editable(clave, hoy):
            raise ConfigError(f"El bimestre {bimestre_texto(clave)} ya está cerrado: solo se puede consultar.")
        with _LOCK:
            datos = self._leer()
            if clave not in datos["datos"].get(modulo, {}):
                raise ConfigError("Ese bimestre no tiene tabla propia en este módulo.")
            del datos["datos"][modulo][clave]
            datos["version"] = int(datos.get("version", 0)) + 1
            self._escribir(datos)
            self._historial({"cuando": _ahora(), "actor": actor, "modulo": modulo, "bimestre": clave, "motivo": motivo.strip(),
                             "version": datos["version"], "cambios": [], "tipo": "herencia"})

    # --- historial
    def _historial(self, registro: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with self.ruta_historial.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    def historial(self, modulo: str | None = None, clave: str | None = None, limite: int = 300) -> list[dict]:
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
            if modulo in (None, r.get("modulo")) and clave in (None, r.get("bimestre")):
                out.append(r)
            if len(out) >= limite:
                break
        return out


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------- acceso desde los tableros
def store_por_defecto() -> ObjetivosBimestreStore:
    return ObjetivosBimestreStore(ruta_config())


def objetivos_vigentes(modulo: str, inicio_bimestre: date, base: pd.DataFrame | None,
                       store: ObjetivosBimestreStore | None = None) -> pd.DataFrame | None:
    """Tabla de objetivos que rige para el bimestre que empieza en `inicio_bimestre` (la editada, la heredada o la del Excel).
    Si el almacén no se puede leer, devuelve `base`: el tablero nunca se rompe por esto."""
    try:
        df, _, _ = (store or store_por_defecto()).vigente(modulo, bimestre_clave(inicio_bimestre), base)
        return df
    except Exception:  # noqa: BLE001
        return base
