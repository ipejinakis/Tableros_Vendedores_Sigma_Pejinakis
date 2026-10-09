"""Campañas de Mis Ventas y líneas de Club Faro, editables por bimestre (catálogo, artículos y objetivos por vendedor).

Cada bimestre cambian las campañas/líneas, sus artículos y los objetivos. Una DEFINICIÓN de bimestre tiene tres partes:
- catálogo: las campañas (Mis Ventas: nombre y tipos COBERTURA/VOLUMEN) o líneas (Club Faro: nombre, tipo de cliente AS/TRAD
  y modo `clientes` o `cliente_sku`);
- artículos: la lista de códigos de artículo de cada campaña/línea (un artículo cuenta si está en la lista);
- objetivos: valor por vendedor (y por tipo, en Mis Ventas) de cada campaña/línea.

Reglas (Juan, 2026-10-09): cada definición vale para un bimestre completo; el bimestre en curso se edita (recalcula todo)
y los cerrados son de solo lectura; un bimestre nuevo arranca VACÍO (no hereda) y se puede copiar del anterior; los
vendedores no se editan acá (salen de SIGMA / `negocio.py`); todo cambio queda en el historial.
La semilla es lo cargado desde el Excel (silver `obj_*` / `cfg_*`) cuando es del mismo bimestre.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from . import negocio as N
from .config_bimestre import bimestre_clave, bimestre_texto
from .config_objetivos import ConfigError, ConflictoError, _LOCK, ruta_config, vendedores_con_escala

MODULOS = ("mis_ventas", "club_faro", "titulares", "cobertura")
CATEGORIAS_COB = ("BPC", "FOOD", "HC")
SIN_CATEGORIA = "NINGUNA"      # el artículo no cuenta para ninguna categoría de cobertura
TIPOS_MV = ("COBERTURA", "VOLUMEN")
TIPOS_CLIENTE = ("AS", "TRAD")
MODOS_CF = ("clientes", "cliente_sku")
_CLAVE_RE = re.compile(r"^[A-Z0-9_]{1,40}$")

VACIA = {"catalogo": {}, "articulos": {}, "objetivos": [], "canales": {}, "subcanales": {}, "excepciones": {}}


def slug(nombre: str) -> str:
    """Clave estable a partir del nombre: 'Dove 180 ml' -> 'DOVE_180_ML'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nombre).upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", "_", s).strip("_")[:40]


# ----------------------------------------------------------------------------- validación
def validar(modulo: str, d: dict, vendedores_ok: set[str]) -> dict:
    """Valida y normaliza una definición; levanta ConfigError con un mensaje legible."""
    if modulo not in MODULOS:
        raise ConfigError(f"Módulo desconocido: {modulo!r}.")
    if modulo == "cobertura":
        # Cobertura: no hay campañas ni vendedores; solo excepciones artículo -> categoría sobre la regla automática del ETL
        exc = {}
        for a, c in (d.get("excepciones") or {}).items():
            a, c = str(a).strip(), str(c).strip().upper()
            if not a:
                continue
            if c not in CATEGORIAS_COB + (SIN_CATEGORIA,):
                raise ConfigError(f"Categoría inválida para el artículo {a}: {c!r} (usar {', '.join(CATEGORIAS_COB)} o {SIN_CATEGORIA}).")
            exc[a] = c
        return {"catalogo": {}, "articulos": {}, "objetivos": [], "excepciones": dict(sorted(exc.items()))}
    cat = d.get("catalogo") or {}
    out_cat, nombres = {}, set()
    for k, info in cat.items():
        k = str(k).strip().upper()
        nombre = str(info.get("nombre", "")).strip()
        if not _CLAVE_RE.match(k):
            raise ConfigError(f"Clave inválida: {k!r} (usar letras, números y guion bajo).")
        if not nombre:
            raise ConfigError("Cada campaña/línea necesita un nombre.")
        if nombre.lower() in nombres:
            raise ConfigError(f"Nombre repetido: {nombre!r}.")
        nombres.add(nombre.lower())
        if modulo == "mis_ventas":
            tipos = [t for t in TIPOS_MV if t in [str(x).upper() for x in info.get("tipos", [])]]
            if not tipos:
                raise ConfigError(f"{nombre}: elegí al menos un tipo (cobertura y/o volumen).")
            out_cat[k] = {"nombre": nombre, "tipos": tipos}
        elif modulo == "titulares":
            try:
                obj_l = float(info.get("objetivo", 0))
            except (TypeError, ValueError) as e:
                raise ConfigError(f"{nombre}: el objetivo debe ser un número.") from e
            if obj_l < 0:
                raise ConfigError("Los objetivos no pueden ser negativos.")
            out_cat[k] = {"nombre": nombre, "objetivo": int(round(obj_l)), "propia": bool(info.get("propia", False))}
        else:
            tc, modo = str(info.get("tipo_cliente", "")).upper(), str(info.get("modo", ""))
            if tc not in TIPOS_CLIENTE:
                raise ConfigError(f"{nombre}: el tipo de cliente debe ser AS o TRAD.")
            if modo not in MODOS_CF:
                raise ConfigError(f"{nombre}: el modo debe ser 'clientes' o 'cliente_sku'.")
            out_cat[k] = {"nombre": nombre, "tipo_cliente": tc, "modo": modo}
    arts = {}
    for k, ids in (d.get("articulos") or {}).items():
        k = str(k).strip().upper()
        if k not in out_cat:
            raise ConfigError(f"Hay artículos asignados a una campaña/línea que no existe: {k!r}.")
        limpio = []
        for a in ids:
            a = str(a).strip()
            if a and a not in limpio:
                limpio.append(a)
        arts[k] = limpio
    objs, vistos = [], set()
    for o in ([] if modulo == "titulares" else d.get("objetivos") or []):          # 11 Titulares: el objetivo es del distribuidor
        k, v = str(o["clave"]).strip().upper(), str(o["vendedor_id"]).strip()
        tipo = str(o.get("tipo") or "").upper()
        if k not in out_cat:
            raise ConfigError(f"Objetivo para una campaña/línea que no existe: {k!r}.")
        if modulo == "mis_ventas" and tipo not in out_cat[k]["tipos"]:
            raise ConfigError(f"{out_cat[k]['nombre']}: no tiene el tipo {tipo or '?'}.")
        if v not in vendedores_ok:
            raise ConfigError(f"El vendedor {v} no está entre los vendedores con escala de Facturación: la lista de vendedores no se edita acá, la incorpora el administrador.")
        try:
            val = float(o["valor"])
        except (TypeError, ValueError) as e:
            raise ConfigError(f"Objetivo no numérico: {o.get('valor')!r}.") from e
        if val < 0:
            raise ConfigError("Los objetivos no pueden ser negativos.")
        clave_o = (k, tipo, v)
        if clave_o in vistos:
            raise ConfigError("Objetivo repetido para el mismo vendedor.")
        vistos.add(clave_o)
        objs.append({"clave": k, "tipo": tipo if modulo == "mis_ventas" else "", "vendedor_id": v, "valor": val})
    res = {"catalogo": out_cat, "articulos": arts,
           "objetivos": sorted(objs, key=lambda o: (o["clave"], o["tipo"], o["vendedor_id"]))}
    if modulo == "titulares":
        res["canales"] = _validar_objetivos_fijos(d.get("canales"), N.TITULARES_CANALES, "canal")
        res["subcanales"] = _validar_objetivos_fijos(d.get("subcanales"), tuple(N.TITULARES_OBJ_SUBCANAL), "subcanal")
    return res


def _validar_objetivos_fijos(valores, nombres: tuple, que: str) -> dict:
    """Objetivos por canal/subcanal de 11 Titulares: los nombres son fijos (salen del rubro del cliente en SIGMA); solo cambia el número."""
    valores = valores or {}
    extra = set(valores) - set(nombres)
    if extra:
        raise ConfigError(f"{que.capitalize()} desconocido: {', '.join(sorted(extra))}.")
    out = {}
    for n in nombres:
        try:
            v = float(valores.get(n, 0))
        except (TypeError, ValueError) as e:
            raise ConfigError(f"Objetivo de {n} no numérico.") from e
        if v < 0:
            raise ConfigError("Los objetivos no pueden ser negativos.")
        out[n] = int(round(v))
    return out


def diferencias(antes: dict, despues: dict) -> list[dict]:
    out = []
    ca, cd = antes.get("catalogo", {}), despues.get("catalogo", {})
    for k in sorted(set(ca) | set(cd)):
        if k not in ca:
            out.append({"campo": f"Se agregó «{cd[k]['nombre']}»", "antes": "", "despues": "nueva"})
        elif k not in cd:
            out.append({"campo": f"Se quitó «{ca[k]['nombre']}»", "antes": "existía", "despues": ""})
        elif ca[k] != cd[k]:
            out.append({"campo": f"Datos de «{cd[k]['nombre']}»", "antes": json.dumps(ca[k], ensure_ascii=False),
                        "despues": json.dumps(cd[k], ensure_ascii=False)})
    aa, ad = antes.get("articulos", {}), despues.get("articulos", {})
    for k in sorted(set(aa) | set(ad)):
        a, d = set(aa.get(k, [])), set(ad.get(k, []))
        nombre = (cd.get(k) or ca.get(k) or {}).get("nombre", k)
        if d - a:
            out.append({"campo": f"Artículos agregados a «{nombre}»", "antes": "", "despues": ", ".join(sorted(d - a))})
        if a - d:
            out.append({"campo": f"Artículos quitados de «{nombre}»", "antes": ", ".join(sorted(a - d)), "despues": ""})
    ea, ed = antes.get("excepciones", {}), despues.get("excepciones", {})
    for a in sorted(set(ea) | set(ed)):
        if ea.get(a) != ed.get(a):
            out.append({"campo": f"Categoría de cobertura del artículo {a}", "antes": ea.get(a, "según la regla automática"),
                        "despues": ed.get(a, "según la regla automática")})
    for campo, etiqueta in (("canales", "Canal"), ("subcanales", "Subcanal")):
        xa, xd = antes.get(campo, {}), despues.get(campo, {})
        for k in sorted(set(xa) | set(xd)):
            if xa.get(k, 0) != xd.get(k, 0):
                out.append({"campo": f"Objetivo {etiqueta.lower()} «{k}»", "antes": xa.get(k, 0), "despues": xd.get(k, 0)})
    oa = {(o["clave"], o["tipo"], o["vendedor_id"]): o["valor"] for o in antes.get("objetivos", [])}
    od = {(o["clave"], o["tipo"], o["vendedor_id"]): o["valor"] for o in despues.get("objetivos", [])}
    for k in sorted(set(oa) | set(od)):
        if oa.get(k) != od.get(k):
            nombre = (cd.get(k[0]) or ca.get(k[0]) or {}).get("nombre", k[0])
            etiqueta = f"Objetivo «{nombre}»" + (f" ({k[1].lower()})" if k[1] else "") + f" · vendedor {k[2]}"
            out.append({"campo": etiqueta, "antes": oa.get(k, ""), "despues": od.get(k, "")})
    return out


# ----------------------------------------------------------------------------- almacén
class CampanasStore:
    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self.ruta = self.carpeta / "campanas_bimestre.json"
        self.ruta_historial = self.carpeta / "historial_campanas.jsonl"

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

    def bimestres_con_config(self, modulo: str) -> list[str]:
        return sorted(self._leer()["datos"].get(modulo, {}))

    @staticmethod
    def es_editable(clave: str, hoy: date) -> bool:
        return clave >= bimestre_clave(hoy)

    def propia(self, modulo: str, clave: str) -> dict | None:
        return (self._leer()["datos"].get(modulo, {}).get(clave) or {}).get("definicion")

    def vigente(self, modulo: str, clave: str, semilla: tuple[str, dict] | None = None) -> tuple[dict, str, int]:
        """Definición vigente: la propia del bimestre ("propia"); si no, la del Excel si es de este bimestre ("excel");
        si no, vacía ("vacia"). NO hereda de bimestres anteriores. Devuelve (definición, origen, versión)."""
        datos = self._leer()
        ver = int(datos.get("version", 0))
        p = (datos["datos"].get(modulo, {}).get(clave) or {}).get("definicion")
        if p is not None:
            return p, "propia", ver
        if semilla and semilla[0] == bimestre_texto(clave):
            return semilla[1], "excel", ver
        return json.loads(json.dumps(VACIA)), "vacia", ver

    def guardar(self, actor: str, modulo: str, clave: str, definicion: dict, semilla: tuple[str, dict] | None = None,
                motivo: str = "", version_base: int | None = None, hoy: date | None = None, copia: bool = False) -> dict:
        hoy = hoy or date.today()
        if not self.es_editable(clave, hoy):
            raise ConfigError(f"El bimestre {bimestre_texto(clave)} ya está cerrado: solo se puede consultar.")
        with _LOCK:
            datos = self._leer()
            if version_base is not None and int(datos.get("version", 0)) != int(version_base):
                raise ConflictoError("Otra persona guardó cambios mientras editabas. Recargá y volvé a aplicar tu cambio.")
            antes, _, _ = self.vigente(modulo, clave, semilla)
            permitidos = set(vendedores_con_escala(clave)) | {o["vendedor_id"] for o in antes.get("objetivos", [])}
            if copia:       # al copiar de otro bimestre se conservan los vendedores que ya tenían objetivo allá (p. ej. uno sin escala)
                permitidos |= {o["vendedor_id"] for o in definicion.get("objetivos", [])}
            limpia = validar(modulo, definicion, permitidos)
            cambios = diferencias(antes, limpia)
            if not cambios:
                raise ConfigError("No hay cambios para guardar.")
            datos["version"] = int(datos.get("version", 0)) + 1
            datos["datos"].setdefault(modulo, {})[clave] = {"definicion": limpia, "actor": actor, "cuando": _ahora()}
            self._escribir(datos)
            self._historial({"cuando": _ahora(), "actor": actor, "modulo": modulo, "bimestre": clave, "motivo": motivo.strip(),
                             "version": datos["version"], "cambios": cambios, "tipo": "copia" if copia else "edicion"})
        return limpia

    def descartar(self, actor: str, modulo: str, clave: str, motivo: str = "", hoy: date | None = None) -> None:
        """Borra la definición propia del bimestre (vuelve a lo del Excel o a vacío)."""
        hoy = hoy or date.today()
        if not self.es_editable(clave, hoy):
            raise ConfigError(f"El bimestre {bimestre_texto(clave)} ya está cerrado: solo se puede consultar.")
        with _LOCK:
            datos = self._leer()
            if clave not in datos["datos"].get(modulo, {}):
                raise ConfigError("Ese bimestre no tiene definición propia.")
            del datos["datos"][modulo][clave]
            datos["version"] = int(datos.get("version", 0)) + 1
            self._escribir(datos)
            self._historial({"cuando": _ahora(), "actor": actor, "modulo": modulo, "bimestre": clave, "motivo": motivo.strip(),
                             "version": datos["version"], "cambios": [], "tipo": "descarte"})

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


def bimestre_anterior(clave: str) -> str:
    anio, m = (int(x) for x in clave.split("-"))
    m -= 2
    if m < 1:
        anio, m = anio - 1, m + 12
    return f"{anio:04d}-{m:02d}"


# ----------------------------------------------------------------------------- semilla (lo cargado desde el Excel)
def semilla_mis_ventas(obj: pd.DataFrame | None, art: pd.DataFrame | None) -> tuple[str, dict] | None:
    if obj is None or obj.empty:
        return None
    cat, objs = {}, []
    for r in obj.itertuples():
        c = cat.setdefault(str(r.campana), {"nombre": N.CAMPANA_NOMBRE.get(str(r.campana), str(r.campana)), "tipos": []})
        if str(r.tipo) not in c["tipos"]:
            c["tipos"].append(str(r.tipo))
        objs.append({"clave": str(r.campana), "tipo": str(r.tipo), "vendedor_id": str(r.vendedor_id), "valor": float(r.target)})
    arts = {}
    if art is not None and len(art):
        for r in art[art["incluir"].astype(bool)].itertuples():
            if str(r.campana) in cat:
                arts.setdefault(str(r.campana), []).append(str(r.articulo_id))
    return str(obj["periodo"].iloc[0]), {"catalogo": cat, "articulos": arts, "objetivos": objs}


def semilla_club_faro(obj: pd.DataFrame | None, art: pd.DataFrame | None) -> tuple[str, dict] | None:
    if obj is None or obj.empty:
        return None
    cat = {k: {"nombre": i["nombre"], "tipo_cliente": i["tipo_cliente"], "modo": i["modo"]} for k, i in N.CLUB_FARO_LINEAS.items()}
    objs = [{"clave": str(r.linea), "tipo": "", "vendedor_id": str(r.vendedor_id), "valor": float(r.objetivo)}
            for r in obj.itertuples() if str(r.vendedor_id).strip()]
    arts = {}
    if art is not None and len(art):
        for r in art[art["incluir"].astype(bool)].itertuples():
            if str(r.linea) in cat:
                arts.setdefault(str(r.linea), []).append(str(r.articulo_id))
    return str(obj["periodo"].iloc[0]), {"catalogo": cat, "articulos": arts, "objetivos": objs}


def semilla_titulares(_obj, art: pd.DataFrame | None) -> tuple[str, dict] | None:
    """Semilla de 11 Titulares: líneas, canales y subcanales de `negocio.py` + artículos cargados desde el Excel."""
    if art is None or art.empty:
        return None
    cat = {k: {"nombre": i["nombre"], "objetivo": int(i["objetivo"]), "propia": bool(i.get("propia", False))}
           for k, i in N.TITULARES_LINEAS.items()}
    arts = {}
    for r in art[art["incluir"].astype(bool)].itertuples():
        if str(r.linea) in cat:
            arts.setdefault(str(r.linea), []).append(str(r.articulo_id))
    return str(art["periodo"].iloc[0]), {"catalogo": cat, "articulos": arts, "objetivos": [],
                                         "canales": dict(N.TITULARES_OBJ_CANAL), "subcanales": dict(N.TITULARES_OBJ_SUBCANAL)}


SEMILLAS = {"mis_ventas": semilla_mis_ventas, "club_faro": semilla_club_faro, "titulares": semilla_titulares}


# ----------------------------------------------------------------------------- definición -> tablas que leen los tableros
def _sup(v: str) -> tuple[str, str]:
    sid = N.SUPERVISOR_VENDEDOR.get(v, "")
    return sid, N.SUPERVISORES.get(sid, "")


def a_tablas_mis_ventas(d: dict, clave: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    per = bimestre_texto(clave)
    obj = pd.DataFrame([{"campana": o["clave"], "campana_excel": d["catalogo"][o["clave"]]["nombre"], "tipo": o["tipo"],
                         "supervisor_id": _sup(o["vendedor_id"])[0], "vendedor_id": o["vendedor_id"], "target": o["valor"],
                         "remanente": None, "periodo": per} for o in d["objetivos"]],
                       columns=["campana", "campana_excel", "tipo", "supervisor_id", "vendedor_id", "target", "remanente", "periodo"])
    art = pd.DataFrame([{"articulo_id": a, "campana": k, "descripcion": "", "sugerencia": "", "incluir": True,
                         "fuente": "editado en el tablero", "periodo": per} for k, ids in d["articulos"].items() for a in ids],
                       columns=["articulo_id", "campana", "descripcion", "sugerencia", "incluir", "fuente", "periodo"])
    return obj, art, {k: i["nombre"] for k, i in d["catalogo"].items()}


def a_tablas_club_faro(d: dict, clave: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    per = bimestre_texto(clave)
    obj = pd.DataFrame([{"vendedor_id": o["vendedor_id"], "nombre_excel": "", "nombre_base": "", "coincidencia": "exacta",
                         "supervisor_excel": _sup(o["vendedor_id"])[1], "linea": o["clave"], "objetivo": o["valor"],
                         "tipo_cliente": d["catalogo"][o["clave"]]["tipo_cliente"], "supuesto": False, "periodo": per}
                        for o in d["objetivos"]],
                       columns=["vendedor_id", "nombre_excel", "nombre_base", "coincidencia", "supervisor_excel", "linea",
                                "objetivo", "tipo_cliente", "supuesto", "periodo"])
    art = pd.DataFrame([{"linea": k, "articulo_id": a, "descripcion": "", "incluir": True, "fuente": "editado en el tablero",
                         "periodo": per} for k, ids in d["articulos"].items() for a in ids],
                       columns=["linea", "articulo_id", "descripcion", "incluir", "fuente", "periodo"])
    return obj, art, {k: dict(i) for k, i in d["catalogo"].items()}


def a_tablas_titulares(d: dict, clave: str) -> tuple[pd.DataFrame, dict, dict, dict]:
    """(artículos, líneas, objetivos por canal, objetivos por subcanal) de 11 Titulares en el formato que lee `titulares_resumen`."""
    per = bimestre_texto(clave)
    art = pd.DataFrame([{"linea": k, "articulo_id": a, "descripcion": "", "incluir": True, "fuente": "editado en el tablero",
                         "periodo": per} for k, ids in d["articulos"].items() for a in ids],
                       columns=["linea", "articulo_id", "descripcion", "incluir", "fuente", "periodo"])
    lineas = {k: {"nombre": i["nombre"], "objetivo": i["objetivo"], **({"propia": True} if i.get("propia") else {})}
              for k, i in d["catalogo"].items()}
    return art, lineas, dict(d.get("canales") or {}), dict(d.get("subcanales") or {})


def excepciones_cobertura(inicio_bimestre: date, store: "CampanasStore | None" = None) -> dict:
    """{articulo_id: categoría} editadas para el bimestre (BPC / FOOD / HC / NINGUNA). Vacío si no hay o si falla la lectura."""
    try:
        d, origen, _ = (store or store_por_defecto()).vigente("cobertura", bimestre_clave(inicio_bimestre), None)
        return dict(d.get("excepciones") or {}) if origen == "propia" else {}
    except Exception:  # noqa: BLE001
        return {}


def categoria_efectiva(base: pd.Series, excepciones: dict) -> pd.Series:
    """Categoría de cobertura de cada artículo (índice articulo_id): la regla automática, salvo las excepciones.
    NINGUNA -> sin categoría (NA)."""
    out = base.astype("object").where(base.notna(), None)          # pd.NA -> None (con NA no se puede comparar)
    for a, c in excepciones.items():
        out.loc[str(a)] = None if c == SIN_CATEGORIA else c
    return out


def titulares_vigentes(inicio_bimestre: date, base_art: pd.DataFrame | None, store: "CampanasStore | None" = None):
    """(artículos, líneas, obj_canal, obj_subcanal) de 11 Titulares del bimestre. Sin definición propia ni del Excel: vacío.
    Si falla la lectura, usa lo de `negocio.py` y el Excel."""
    clave = bimestre_clave(inicio_bimestre)
    try:
        d, origen, _ = (store or store_por_defecto()).vigente("titulares", clave, semilla_titulares(None, base_art))
        if origen == "excel":
            return (base_art, {k: dict(i) for k, i in N.TITULARES_LINEAS.items()},
                    dict(N.TITULARES_OBJ_CANAL), dict(N.TITULARES_OBJ_SUBCANAL))
        return a_tablas_titulares(d, clave)
    except Exception:  # noqa: BLE001
        return base_art, {k: dict(i) for k, i in N.TITULARES_LINEAS.items()}, dict(N.TITULARES_OBJ_CANAL), dict(N.TITULARES_OBJ_SUBCANAL)


def store_por_defecto() -> CampanasStore:
    return CampanasStore(ruta_config())


def tablas_vigentes(modulo: str, inicio_bimestre: date, base_obj: pd.DataFrame | None, base_art: pd.DataFrame | None,
                    store: CampanasStore | None = None):
    """(objetivos, artículos, catálogo) que rigen para el bimestre que empieza en `inicio_bimestre`.
    El catálogo es {clave: nombre} en Mis Ventas y {clave: {nombre, tipo_cliente, modo}} en Club Faro.
    Si no hay definición propia ni del Excel para ese bimestre, devuelve tablas vacías. Si falla la lectura, usa las del Excel."""
    clave = bimestre_clave(inicio_bimestre)
    try:
        d, origen, _ = (store or store_por_defecto()).vigente(modulo, clave, SEMILLAS[modulo](base_obj, base_art))
        if origen == "excel":
            cat = ({k: i["nombre"] for k, i in d["catalogo"].items()} if modulo == "mis_ventas"
                   else {k: dict(i) for k, i in d["catalogo"].items()})
            return base_obj, base_art, cat
        conv = a_tablas_mis_ventas if modulo == "mis_ventas" else a_tablas_club_faro
        return conv(d, clave)
    except Exception:  # noqa: BLE001
        cat = N.CAMPANA_NOMBRE if modulo == "mis_ventas" else N.CLUB_FARO_LINEAS
        return base_obj, base_art, dict(cat)
