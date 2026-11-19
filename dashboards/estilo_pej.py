"""Estética compartida con los tableros de Rentabilidad y Torre de control (tarjetas con degradé, menú lateral, cartel
de datos). Portado de `oe_conn/estilo.py` de ese repo, SIN plotly ni yaml: Ventas no los usa y el servidor no los tiene.

Uso, al principio de `app.py` (después de `st.set_page_config`):

    import estilo_pej as E
    E.aplicar_estilo()

Y en las páginas: `E.tarjeta_kpi("Etiqueta", "$ 1.000", variacion="texto chico", tono="azul", donde=columna)`.

El color de una tarjeta SIGNIFICA algo. En Ventas casi ninguna cifra tiene un "mes anterior" comparable (el mes está a
medias hasta el corte), así que el color sale del semáforo que el tablero ya usaba (`tono_estado`) y el resto va en azul
(informativo, sin juicio). `tono_por_variacion` se conserva por si más adelante se compara contra el mes anterior.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st

import menu_tableros as MT


def _tema_activo() -> str:
    """'light' o 'dark', el tema que Streamlit tiene activo; si no se puede saber, 'light'."""
    try:
        tipo = st.context.theme.type
        if tipo in ("light", "dark"):
            return tipo
    except Exception:  # noqa: BLE001  (Streamlit viejo: sin st.context.theme)
        pass
    return "light"


# --------------------------------------------------------------------------- CSS general
_CSS = """
<style>
:root { color-scheme: light dark; --pj-acento: #2a78d6; }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1400px; }
header[data-testid="stHeader"] { background: transparent; }
footer { visibility: hidden; }
[data-testid="stAppDeployButton"], .stDeployButton { display: none !important; }
html, body, [class*="css"] { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }

h2, h3 {
  font-size: 1.02rem !important; font-weight: 600 !important;
  color: currentColor !important; letter-spacing: -.005em;
  margin-top: .4rem !important; margin-bottom: .1rem !important;
}
hr { border-color: color-mix(in srgb, currentColor 14%, transparent) !important; margin: 1.6rem 0 1.2rem 0 !important; }
[data-testid="stDataFrame"] { border-radius: 8px; }
button[data-baseweb="tab"] { font-size: .9rem; font-weight: 500; }
[data-baseweb="tab-highlight"] { background-color: var(--pj-acento); }

[data-testid="stSidebar"] {
  background: color-mix(in srgb, currentColor 6%, transparent);
  border-right: 1px solid color-mix(in srgb, currentColor 12%, transparent);
}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 { font-size: .95rem !important; }
[data-testid="stSidebar"] .stButton button, [data-testid="stFormSubmitButton"] button { width: 100%; }

@media (max-width: 640px) {
  .block-container { padding-left: .8rem; padding-right: .8rem; padding-top: 1rem; }
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .55rem; }
  [data-testid="stHorizontalBlock"] > div { min-width: calc(50% - .3rem); }
}
</style>
"""

# --------------------------------------------------------------------------- tarjetas, menú y cartel
TONOS = ("azul", "verde", "naranja", "rojo")

_TOKENS = {
    "light": {"verde": "#2a7f47", "rojo": "#b23838", "naranja": "#a85f12", "azul": "#3556bd",
              "datos_bg": "#e3f3e8", "datos_tx": "#1c6b3b", "viejo_bg": "#fdecc8", "viejo_tx": "#7a4d00"},
    "dark": {"verde": "#5cc27a", "rojo": "#f07570", "naranja": "#f2a550", "azul": "#86a3f2",
             "datos_bg": "#1f3a2b", "datos_tx": "#7bd89a", "viejo_bg": "#3d3220", "viejo_tx": "#f2c26b"},
}

_CSS_COMPONENTES = """
<style>
.pj-kpi{position:relative;overflow:hidden;border-radius:14px;padding:16px 18px 14px;min-height:114px;
  display:flex;flex-direction:column;gap:3px;color:#fff;margin-bottom:.4rem}
.pj-kpi .lab{font-size:.7rem;letter-spacing:.09em;text-transform:uppercase;font-weight:700}
.pj-kpi .val{font-size:clamp(1.15rem,1.7vw,1.7rem);font-weight:700;line-height:1.15;white-space:nowrap}
.pj-kpi .dlt{font-size:.83rem;margin-top:auto;padding-top:6px;opacity:.94}
.pj-kpi::after{content:"";position:absolute;right:-30px;top:-30px;width:112px;height:112px;
  border-radius:50%;background:rgba(255,255,255,.14)}
.pj-kpi.verde{background:linear-gradient(135deg,#4cae6e,#2b7f48)}
.pj-kpi.rojo{background:linear-gradient(135deg,#d4504a,#a93434)}
.pj-kpi.naranja{background:linear-gradient(135deg,#dd9030,#b2620f)}
.pj-kpi.azul{background:linear-gradient(135deg,#5a7de0,#3856bd)}

.pj-t-verde{--c:@verde@} .pj-t-rojo{--c:@rojo@} .pj-t-naranja{--c:@naranja@} .pj-t-azul{--c:@azul@}
.pj-leyenda{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:.82rem;opacity:.75;margin:2px 0 4px}
.pj-leyenda i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;background:var(--c)}

.pj-nav .sec{font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;font-weight:700;
  opacity:.6;margin:16px 8px 5px}
.pj-nav .sec:first-child{margin-top:2px}
.pj-nav a,.pj-nav .on{display:block;padding:7px 10px;border-radius:8px;font-size:.95rem;
  color:inherit !important;text-decoration:none !important}
.pj-nav a:hover{background:color-mix(in srgb,currentColor 7%,transparent)}
.pj-nav .on{background:color-mix(in srgb,currentColor 10%,transparent);font-weight:600}
.pj-user{border-top:1px solid color-mix(in srgb,currentColor 16%,transparent);padding:16px 8px 2px;margin-top:10px}
.pj-user b{display:block;font-size:1.02rem}
.pj-user span{display:block;opacity:.65;font-size:.88rem;margin:2px 0 10px}
.pj-datos{background:@datos_bg@;color:@datos_tx@;border-radius:10px;padding:10px 12px;
  font-size:.88rem;line-height:1.35;margin-top:12px}
.pj-datos.viejo{background:@viejo_bg@;color:@viejo_tx@}
@media (max-width:640px){.pj-kpi .val{font-size:1.4rem}}
</style>
"""


def _css_componentes() -> str:
    css = _CSS_COMPONENTES
    for clave, valor in _TOKENS[_tema_activo()].items():
        css = css.replace(f"@{clave}@", valor)
    return css


def aplicar_estilo() -> None:
    """Inyecta el CSS del proyecto. Llamar en cada ejecución del script, justo después de `st.set_page_config`."""
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(_css_componentes(), unsafe_allow_html=True)


def _h(texto) -> str:
    """Escapa para HTML y neutraliza el `$` (st.markdown lo toma por LaTeX y se come lo que haya entre dos pesos)."""
    return escape(str(texto), quote=True).replace("$", "&#36;")


# --------------------------------------------------------------------------- formato y tonos
_MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def etiqueta_periodo(periodo: str) -> str:
    """'2026-08' -> 'ago 2026'."""
    anio, mes = (int(x) for x in periodo.split("-"))
    return f"{_MESES_CORTOS[mes - 1]} {anio}"


def formato_pct(valor: float, decimales: int = 1) -> str:
    """19,8 % (coma decimal y espacio antes del signo)."""
    return f"{valor:.{decimales}f}".replace(".", ",") + " %"


def texto_variacion(cambio: float | None, unidad: str = "%", ref: str = "") -> str | None:
    """'▲ +2,2 % vs. ago 2026'. La flecha dice hacia dónde fue; el COLOR dice si eso es bueno."""
    if cambio is None:
        return None
    r = round(float(cambio), 1)
    flecha = "▲" if r > 0 else ("▼" if r < 0 else "■")
    num = f"{r:+.1f}".replace(".", ",")
    base = f"{flecha} {num} {unidad}"
    return f"{base} vs. {ref}" if ref else base


def tono_por_variacion(cambio: float | None, *, mejor: str = "sube", umbral: float = 5.0) -> str:
    """verde mejoró · naranja empeoró menos que `umbral` · rojo empeoró `umbral` o más · azul sin comparación."""
    if cambio is None or abs(cambio) < 0.05:
        return "azul"
    mejora = cambio > 0 if mejor == "sube" else cambio < 0
    if mejora:
        return "verde"
    return "naranja" if abs(cambio) < umbral else "rojo"


_TONO_ESTADO = {"verde": "verde", "amarillo": "naranja", "rojo": "rojo"}


def tono_estado(estado: str | None) -> str:
    """Estado del semáforo del tablero (verde / amarillo / rojo) -> tono de tarjeta. Otro estado (p. ej. sin objetivo): azul."""
    return _TONO_ESTADO.get(str(estado), "azul")


def tarjeta_kpi(etiqueta: str, valor, variacion: str | None = None, tono: str = "azul", ayuda: str = "", donde=None) -> None:
    """Tarjeta con degradé. `variacion` es el texto chico de abajo; `ayuda` sale como tooltip; `donde` = columna (o `st`)."""
    destino = donde if donde is not None else st
    if tono not in TONOS:
        tono = "azul"
    dlt = f'<div class="dlt">{_h(variacion)}</div>' if variacion else '<div class="dlt">&nbsp;</div>'
    tip = f' title="{_h(ayuda)}"' if ayuda else ""
    destino.markdown(
        f'<div class="pj-kpi {tono}"{tip}><div class="lab">{_h(etiqueta)}</div>'
        f'<div class="val">{_h(valor)}</div>{dlt}</div>',
        unsafe_allow_html=True,
    )


def leyenda_tonos() -> None:
    """Qué significa cada color de las tarjetas con estado. Va una vez por pantalla."""
    st.markdown(
        '<div class="pj-leyenda"><span>Color de las tarjetas con estado:</span>'
        '<span><i class="pj-t-verde"></i>cumplido</span>'
        '<span><i class="pj-t-naranja"></i>en camino al ritmo actual</span>'
        '<span><i class="pj-t-rojo"></i>en riesgo o proyección insuficiente</span>'
        '<span><i class="pj-t-azul"></i>informativo, sin juicio</span></div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- menú lateral y cartel de datos
def barra_lateral_nav(actual: str, rol: str | None) -> None:
    """Menú agrupado de la barra lateral, solo con los tableros que ve este rol. El abierto se marca y no es link."""
    grupos: dict[str, list[dict]] = {}
    for t in MT.visibles(rol):
        grupos.setdefault(t["grupo"], []).append(t)
    orden = [g for g in MT.ORDEN_GRUPOS if g in grupos] + [g for g in grupos if g not in MT.ORDEN_GRUPOS]
    partes = ['<div class="pj-nav">']
    for g in orden:
        partes.append(f'<div class="sec">{_h(g)}</div>')
        for t in grupos[g]:
            if t["titulo"].strip().lower() == actual.strip().lower():
                partes.append(f'<span class="on">{_h(t["titulo"])}</span>')
            else:
                partes.append(f'<a href="{_h(t["url"])}" target="_self">{_h(t["titulo"])}</a>')
    partes.append("</div>")
    with st.sidebar:
        st.markdown("".join(partes), unsafe_allow_html=True)


def cartel_datos_html(meta) -> str:
    """'Datos al: 29/10/2026 a las 18:55 hs' a partir del `written_at` (hora de Salta) de la última corrida del ETL.
    Pasa a ámbar si tiene más de 26 horas. Sin dato: cartel ámbar 'sin dato de actualización'."""
    try:
        mod = datetime.fromisoformat(str((meta or {})["written_at"]))
    except (KeyError, ValueError, TypeError):
        return '<div class="pj-datos viejo"><b>Datos al:</b> sin dato de actualización</div>'
    try:
        viejo = (datetime.now(mod.tzinfo) - mod).total_seconds() / 3600 > 26
    except Exception:  # noqa: BLE001
        viejo = False
    aviso = "<br>El dato no se actualiza desde hace más de un día" if viejo else ""
    return (f'<div class="pj-datos{" viejo" if viejo else ""}"><b>Datos al:</b> '
            f'{mod:%d/%m/%Y} a las {mod:%H:%M} hs{aviso}</div>')
