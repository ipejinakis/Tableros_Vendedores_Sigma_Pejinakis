"""Usuarios, claves y roles de los tableros (solo biblioteca estándar: sin dependencias nuevas).

Roles (decididos por Juan, 2026-10-02):
- `gerente` y `supervisor`: ven TODO (todos los vendedores y todos los premios).
- `vendedor`: ve solo lo suyo; su usuario es su código de vendedor (ej. "101") y queda ligado a ese código.

Las claves se guardan con scrypt (sal propia por usuario) en un JSON que NO va a git (`data/auth/usuarios.json`,
permisos 600). Nunca se guarda ni se imprime una clave en claro salvo la temporal, una sola vez, al crearla o
resetearla. Toda clave temporal obliga a cambiarla en el primer ingreso.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from . import negocio as N

ROOT = Path(__file__).resolve().parents[2]

ROL_GERENTE, ROL_SUPERVISOR, ROL_VENDEDOR = "gerente", "supervisor", "vendedor"
ROLES = (ROL_GERENTE, ROL_SUPERVISOR, ROL_VENDEDOR)
ROLES_VEN_TODO = (ROL_GERENTE, ROL_SUPERVISOR)

CLAVE_MIN = 8
_ALFABETO = "abcdefghijkmnpqrstuvwxyz23456789"          # sin caracteres confusos (0/o, 1/l)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


class AuthError(ValueError):
    """Error de validación al administrar usuarios (mensaje apto para mostrar)."""


# ----------------------------------------------------------------------------- claves
def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(sal)}${b64(h)}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        esquema, n, r, p, sal, esperado = guardado.split("$")
        if esquema != "scrypt":
            return False
        h = hashlib.scrypt(clave.encode("utf-8"), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(h, base64.b64decode(esperado))
    except Exception:
        return False


_HASH_FALSO = hash_clave("clave-que-no-existe")      # para gastar el mismo tiempo cuando el usuario no existe


def generar_clave(largo: int = 10) -> str:
    return "".join(secrets.choice(_ALFABETO) for _ in range(largo))


def validar_clave_nueva(clave: str) -> None:
    if len(clave) < CLAVE_MIN:
        raise AuthError(f"La clave debe tener al menos {CLAVE_MIN} caracteres.")
    if clave.isdigit() or clave.isalpha():
        raise AuthError("La clave debe combinar letras y números.")


# ----------------------------------------------------------------------------- almacenamiento
def ruta_usuarios() -> Path:
    """`SIGMA_AUTH_FILE` (variable de entorno o `.env`) o `data/auth/usuarios.json`. No lee el token de la API."""
    env = dotenv_values(ROOT / ".env")
    explicita = os.getenv("SIGMA_AUTH_FILE") or env.get("SIGMA_AUTH_FILE")
    if explicita:
        ruta = Path(explicita)
    else:
        data_dir = Path(os.getenv("SIGMA_DATA_DIR") or env.get("SIGMA_DATA_DIR") or "./data")
        ruta = data_dir / "auth" / "usuarios.json"
    return ruta if ruta.is_absolute() else ROOT / ruta


def normalizar_usuario(usuario: str) -> str:
    return str(usuario).strip().lower()


class UsuariosStore:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)

    # --- lectura / escritura atómica
    def _leer(self) -> dict:
        if not self.ruta.exists():
            return {}
        return json.loads(self.ruta.read_text(encoding="utf-8"))

    def _guardar(self, datos: dict) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.ruta)

    def existe(self) -> bool:
        return self.ruta.exists() and bool(self._leer())

    def listar(self) -> list[dict]:
        """Usuarios sin el hash de la clave."""
        return [{"usuario": u, **{k: v for k, v in d.items() if k != "hash"}} for u, d in sorted(self._leer().items())]

    # --- altas y cambios
    def crear(self, usuario: str, rol: str, nombre: str, vendedor_id: str | None = None,
              clave: str | None = None) -> str:
        """Crea un usuario con clave temporal (o la dada) y devuelve esa clave en claro. Debe cambiarla al entrar."""
        usuario = normalizar_usuario(usuario)
        if not usuario or not usuario.replace(".", "").replace("_", "").isalnum():
            raise AuthError("El usuario solo puede tener letras, números, punto y guion bajo.")
        if rol not in ROLES:
            raise AuthError(f"Rol inválido: {rol!r} (usar {', '.join(ROLES)}).")
        if rol == ROL_VENDEDOR:
            if vendedor_id is None or str(vendedor_id) not in N.VENDEDOR_PERFIL:
                raise AuthError(f"Un vendedor necesita un código con escala de preventa ({', '.join(sorted(N.VENDEDOR_PERFIL))}).")
            vendedor_id = str(vendedor_id)
            if usuario != vendedor_id:
                raise AuthError("El usuario de un vendedor debe ser su código de vendedor.")
        else:
            vendedor_id = None
        datos = self._leer()
        if usuario in datos:
            raise AuthError(f"El usuario {usuario!r} ya existe.")
        clave = clave or generar_clave()
        datos[usuario] = {"rol": rol, "nombre": nombre.strip(), "vendedor_id": vendedor_id, "hash": hash_clave(clave),
                          "debe_cambiar": True, "activo": True,
                          "creado": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._guardar(datos)
        return clave

    def resetear(self, usuario: str) -> str:
        usuario = normalizar_usuario(usuario)
        datos = self._leer()
        if usuario not in datos:
            raise AuthError(f"No existe el usuario {usuario!r}.")
        clave = generar_clave()
        datos[usuario].update({"hash": hash_clave(clave), "debe_cambiar": True})
        self._guardar(datos)
        return clave

    def cambiar_clave(self, usuario: str, actual: str, nueva: str) -> None:
        usuario = normalizar_usuario(usuario)
        datos = self._leer()
        d = datos.get(usuario)
        if not d or not verificar_clave(actual, d["hash"]):
            raise AuthError("La clave actual no es correcta.")
        validar_clave_nueva(nueva)
        if verificar_clave(nueva, d["hash"]):
            raise AuthError("La clave nueva tiene que ser distinta de la actual.")
        d.update({"hash": hash_clave(nueva), "debe_cambiar": False})
        self._guardar(datos)

    def desactivar(self, usuario: str, activo: bool = False) -> None:
        usuario = normalizar_usuario(usuario)
        datos = self._leer()
        if usuario not in datos:
            raise AuthError(f"No existe el usuario {usuario!r}.")
        datos[usuario]["activo"] = activo
        self._guardar(datos)

    # --- ingreso
    def autenticar(self, usuario: str, clave: str) -> dict | None:
        """Datos de sesión (sin hash) si usuario y clave son correctos y el usuario está activo; si no, None."""
        usuario = normalizar_usuario(usuario)
        d = self._leer().get(usuario)
        guardado = d["hash"] if d else _HASH_FALSO       # mismo costo exista o no el usuario
        correcta = verificar_clave(clave, guardado)
        if not d or not correcta or not d.get("activo", True):
            return None
        return {"usuario": usuario, "rol": d["rol"], "nombre": d["nombre"], "vendedor_id": d.get("vendedor_id"),
                "debe_cambiar": bool(d.get("debe_cambiar"))}


def ve_todo(sesion: dict | None) -> bool:
    return bool(sesion) and sesion.get("rol") in ROLES_VEN_TODO


# ----------------------------------------------------------------------------- límite de intentos
class Limitador:
    """Bloquea un usuario `max_intentos` fallos seguidos durante `bloqueo_s` segundos (en memoria del proceso)."""

    def __init__(self, max_intentos: int = 5, bloqueo_s: int = 300):
        self.max_intentos, self.bloqueo_s = max_intentos, bloqueo_s
        self._fallos: dict[str, list[float]] = {}

    def segundos_bloqueado(self, usuario: str, ahora: float | None = None) -> int:
        ahora = time.time() if ahora is None else ahora
        usuario = normalizar_usuario(usuario)
        fallos = [t for t in self._fallos.get(usuario, []) if ahora - t < self.bloqueo_s]
        self._fallos[usuario] = fallos
        if len(fallos) >= self.max_intentos:
            return int(self.bloqueo_s - (ahora - fallos[0])) + 1
        return 0

    def fallo(self, usuario: str, ahora: float | None = None) -> None:
        self._fallos.setdefault(normalizar_usuario(usuario), []).append(time.time() if ahora is None else ahora)

    def ok(self, usuario: str) -> None:
        self._fallos.pop(normalizar_usuario(usuario), None)
