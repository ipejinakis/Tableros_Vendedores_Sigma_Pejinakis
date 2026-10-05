"""Administración de usuarios de los tableros (altas, reseteo de claves, desactivación).

Las claves temporales se muestran UNA sola vez en pantalla (no se guardan en claro): repartirlas por un canal
privado a cada persona; en el primer ingreso el tablero obliga a cambiarlas. El archivo de usuarios es
`data/auth/usuarios.json` (fuera de git; otra ruta con SIGMA_AUTH_FILE).

Uso (desde la raíz del repo, venv activo):
    python scripts/admin/usuarios.py iniciales                 # los 14 vendedores con escala + los 2 supervisores
    python scripts/admin/usuarios.py agregar --usuario jperez --rol gerente --nombre "Juan Pérez"
    python scripts/admin/usuarios.py resetear 101              # clave temporal nueva (olvidó la suya)
    python scripts/admin/usuarios.py desactivar 126            # (o: activar)
    python scripts/admin/usuarios.py listar
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import auth as A  # noqa: E402
from sigma_conn import negocio as N  # noqa: E402

# Supervisores de los tableros (nombre corto de usuario → nombre); el código de supervisor sale de N.SUPERVISORES
SUPERVISORES_INICIALES = {"mamaya": N.SUPERVISORES["5"].title(), "nbuldurini": N.SUPERVISORES["3"].title()}


def nombres_vendedores() -> dict[str, str]:
    """Nombre oficial de SIGMA por código (dim_vendedor); si no hay datos, el código."""
    try:
        from sigma_conn.tableros import abrir_store
        dim = abrir_store().read_table("dim_vendedor")
        return dim.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype(str)) \
            .set_index("vendedor_id")["nombre"].astype(str).str.title().to_dict()
    except Exception:
        return {}


def mostrar(creados: list[tuple[str, str, str, str]]) -> None:
    if not creados:
        print("No se creó ningún usuario nuevo.")
        return
    print(f"\n{'USUARIO':<12}{'ROL':<12}{'NOMBRE':<28}CLAVE TEMPORAL")
    for usuario, rol, nombre, clave in creados:
        print(f"{usuario:<12}{rol:<12}{nombre:<28}{clave}")
    print("\nAnotalas ahora: no se vuelven a mostrar. Cada persona debe cambiarla en su primer ingreso.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("iniciales")
    ag = sub.add_parser("agregar")
    ag.add_argument("--usuario", required=True)
    ag.add_argument("--rol", required=True, choices=A.ROLES)
    ag.add_argument("--nombre", required=True)
    ag.add_argument("--vendedor-id")
    for nombre in ("resetear", "desactivar", "activar"):
        sub.add_parser(nombre).add_argument("usuario")
    sub.add_parser("listar")
    a = ap.parse_args()

    st = A.UsuariosStore(A.ruta_usuarios())
    try:
        if a.cmd == "iniciales":
            existentes = {u["usuario"] for u in st.listar()}
            nombres = nombres_vendedores()
            creados = []
            for vid in sorted(N.VENDEDOR_PERFIL):
                if vid not in existentes:
                    nombre = nombres.get(vid, vid)
                    creados.append((vid, A.ROL_VENDEDOR, nombre, st.crear(vid, A.ROL_VENDEDOR, nombre, vendedor_id=vid)))
            for usuario, nombre in SUPERVISORES_INICIALES.items():
                if usuario not in existentes:
                    creados.append((usuario, A.ROL_SUPERVISOR, nombre, st.crear(usuario, A.ROL_SUPERVISOR, nombre)))
            mostrar(creados)
            print("Faltan los gerentes: agregar cada uno con 'agregar --rol gerente'.")
        elif a.cmd == "agregar":
            clave = st.crear(a.usuario, a.rol, a.nombre, vendedor_id=a.vendedor_id)
            mostrar([(A.normalizar_usuario(a.usuario), a.rol, a.nombre, clave)])
        elif a.cmd == "resetear":
            mostrar([(A.normalizar_usuario(a.usuario), "", "(clave nueva)", st.resetear(a.usuario))])
        elif a.cmd in ("desactivar", "activar"):
            st.desactivar(a.usuario, activo=a.cmd == "activar")
            print(f"Usuario {a.usuario}: {'activado' if a.cmd == 'activar' else 'desactivado'}.")
        elif a.cmd == "listar":
            print(f"{'USUARIO':<12}{'ROL':<12}{'NOMBRE':<28}{'VEND':<6}{'ACTIVO':<8}CAMBIAR CLAVE")
            for u in st.listar():
                print(f"{u['usuario']:<12}{u['rol']:<12}{u['nombre']:<28}{str(u.get('vendedor_id') or ''):<6}"
                      f"{'sí' if u.get('activo', True) else 'no':<8}{'pendiente' if u.get('debe_cambiar') else 'hecho'}")
    except A.AuthError as exc:
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
