"""Menú de tableros de la barra lateral de Ventas.

Es una copia de la lista de `config/tableros.yaml` del repo de Rentabilidad y Torre de control (este proyecto no
usa YAML). Si se agrega, se saca o se cambia de URL un tablero allá, actualizar también acá.

`roles`: roles de ESTE sistema de usuarios (`gerente`, `supervisor`, `vendedor`) que ven el tablero en el menú.
`None` = lo ve cualquier usuario con sesión. OJO: esto es solo el menú. Lo que impide entrar a Rentabilidad o a
Torre de control es el login de esos tableros (`require_login(roles=[ROL_GERENCIA])`), que no depende de este archivo.
"""

ORDEN_GRUPOS = ("Análisis", "Finanzas", "Gerencia")

TABLEROS = [
    {"titulo": "Rentabilidad", "grupo": "Análisis", "url": "https://tablerosrentabilidad.pejinakisit.com", "roles": ("gerente",)},
    {"titulo": "Control tower", "grupo": "Gerencia", "url": "https://tablerostorre.pejinakisit.com", "roles": ("gerente",)},
    {"titulo": "Ventas", "grupo": "Análisis", "url": "https://tablerosventas.pejinakisit.com", "roles": None},
    # "Chequeo de transferencias" (Finanzas) está apagado en tableros.yaml hasta publicar su hostname.
]


def visibles(rol: str | None) -> list[dict]:
    """Tableros que ve un usuario con ese rol (sin rol conocido: solo los abiertos a todos)."""
    return [t for t in TABLEROS if t["roles"] is None or (rol is not None and rol in t["roles"])]
