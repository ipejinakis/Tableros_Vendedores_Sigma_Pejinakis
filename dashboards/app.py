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

import auth_ui  # noqa: E402
from sigma_conn import auth as A  # noqa: E402

usuario = auth_ui.requerir_login()
auth_ui.barra_usuario(usuario)
vista = "gerentes.py" if A.ve_todo(usuario) else "vendedor.py"
runpy.run_path(str(HERE / vista), run_name="__main__")
