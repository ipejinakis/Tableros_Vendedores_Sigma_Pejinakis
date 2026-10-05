import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="session")
def sample_dir():
    """Muestra real (opcional). Definir SIGMA_SAMPLE_DIR o dejarla en ./muestra."""
    p = Path(os.getenv("SIGMA_SAMPLE_DIR", Path(__file__).resolve().parents[1] / "muestra"))
    needed = ["articulos_vendidos.json", "facturas.json", "clientes.json", "articulos.json", "vendedores.json"]
    if not all((p / n).exists() for n in needed):
        pytest.skip("No hay muestra real de la API (SIGMA_SAMPLE_DIR)")
    return p
