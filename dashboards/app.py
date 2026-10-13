"""Punto de entrada de los tableros: ingreso con usuario y clave, y vista según el rol.

    streamlit run dashboards/app.py

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

st.set_page_config(page_title="Tableros de ventas", layout="wide")

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
from sigma_conn import auth as A  # noqa: E402

usuario = auth_ui.requerir_login()
auth_ui.barra_usuario(usuario)
vista = "gerentes.py" if A.ve_todo(usuario) else "vendedor.py"
runpy.run_path(str(HERE / vista), run_name="__main__")
