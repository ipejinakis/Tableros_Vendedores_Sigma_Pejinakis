"""Punto de entrada de los tableros: ingreso con usuario y clave, y vista según el rol.

    streamlit run dashboards/app.py

Barra lateral (mismo orden que Rentabilidad y Torre de control): menú de tableros, filtros de la página y, al pie, el
usuario con "Cerrar sesión" y el cartel "Datos al".

- gerente y supervisor: tablero completo (`gerentes.py`), todos los vendedores y todos los premios.
- vendedor: solo lo suyo (`vendedor.py`), atado al código de vendedor de su usuario.
"""
import runpy
import sys
from pathlib import Path

try:
    HERE = Path(__file__).resolve().parent
except NameError:  # pragma: no cover
    HERE = Path.cwd() / "dashboards"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Ventas · Pejinakis", page_icon="📈", layout="wide")

# Streamlit publica la página con lang="en": el navegador cree que el texto está en inglés, ofrece traducirlo y rompe cosas
# ("M$" pasaba a "millones de dólares", "Escalón alcanzado" a "Escalan alcanzar"). Se marca como español y sin traducción.
try:
    import streamlit.components.v1 as _components
    _components.html("""<script>
      const d = window.parent.document;
      d.documentElement.lang = "es";
      d.documentElement.setAttribute("translate", "no");
      if (!d.querySelector('meta[name="google"]')) {
        const m = d.createElement("meta"); m.name = "google"; m.content = "notranslate"; d.head.appendChild(m);
      }
    </script>""", height=0)
except Exception:  # noqa: BLE001  (si cambia la API, el tablero sigue funcionando)
    pass

import auth_ui  # noqa: E402
import estilo_pej as E  # noqa: E402
from sigma_conn import auth as A  # noqa: E402

E.aplicar_estilo()                      # el CSS del proyecto también vale para la pantalla de ingreso
usuario = auth_ui.requerir_login()
E.barra_lateral_nav("Ventas", usuario["rol"])      # el menú va primero; cada rol ve solo los tableros que le corresponden
st.session_state["_pj_bloque_ok"] = False
vista = "gerentes.py" if A.ve_todo(usuario) else "vendedor.py"
try:
    runpy.run_path(str(HERE / vista), run_name="__main__")
finally:
    # La página dibuja el bloque del usuario después de sus filtros. Si se cortó antes (st.stop por falta de datos),
    # se dibuja acá para que siempre se pueda cerrar la sesión.
    if not st.session_state.get("_pj_bloque_ok") and st.session_state.get("usuario"):
        try:
            auth_ui.bloque_usuario(usuario)
        except Exception:  # noqa: BLE001  (no tapar el error original de la página)
            pass
