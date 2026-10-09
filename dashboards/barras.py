"""Tramo de proyección para las barras de avance (cobertura, Mis Ventas, Club Faro y 11 Titulares).

La barra de color (según el semáforo) es lo logrado; a continuación se dibuja, en azul y más claro, el tramo que falta
para llegar a la proyección al cierre del período si se sigue al ritmo actual (`tableros.agregar_proyeccion`).
Los gráficos no llevan leyenda propia: `leyenda_avance()` dibuja una sola, arriba de todos los gráficos de la pestaña.
Las capas que usan estos helpers llevan `.resolve_scale(color="independent")` (el color del estado y el del tramo azul son escalas distintas)."""
import altair as alt

from estilo import AZUL
from sigma_conn import tableros as TB


def capa_proyeccion(y, x, size: int, data=None) -> alt.Chart:
    """Tramo azul desde `avance_pct` hasta `tramo_fin` (vacío cuando ya cumplió o no hay objetivo). `x` es el mismo eje de la barra."""
    base = alt.Chart() if data is None else alt.Chart(data)       # sin datos propios: hereda los de la capa que la contiene
    return base.mark_bar(size=size, cornerRadiusEnd=4, opacity=0.5).encode(
        y=y, x=x, x2="tramo_fin:Q",
        color=alt.Color("tramo:N", title=None, scale=alt.Scale(domain=[TB.PROYECCION_TXT], range=[AZUL]), legend=None),
        tooltip=[alt.Tooltip("proy_txt:N", title="Proyección al cierre")])


def x_texto(x) -> alt.X:
    """Eje x para la etiqueta de texto: va al final del tramo azul (no encima), con el mismo dominio y eje que la barra."""
    spec = x.to_dict()       # en Altair 6 `x.scale` / `x.axis` son métodos, no valores: se leen del diccionario
    return alt.X("tramo_fin:Q", scale=spec.get("scale"), axis=spec.get("axis"))


def leyenda_avance(sin_objetivo: bool = False) -> None:
    """Leyenda única de colores (estado + tramo de proyección) en una línea; se dibuja una vez arriba de los gráficos de la pestaña."""
    import streamlit as st

    items = [(TB.ESTADO_COLOR[e], 1.0, t) for e, t in TB.ESTADO_AVANCE_TXT.items()] + [(AZUL, 0.5, TB.PROYECCION_TXT)]
    if sin_objetivo:
        items.append((TB.ESTADO_COLOR["sin_objetivo"], 1.0, TB.ESTADO_CF_TXT["sin_objetivo"]))
    chips = "".join(
        f'<span style="white-space:nowrap"><span style="display:inline-block;width:.8rem;height:.8rem;border-radius:2px;'
        f'margin-right:.4rem;vertical-align:-1px;background:{c};opacity:{o}"></span>{t}</span>' for c, o, t in items)
    st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:.35rem 1.4rem;font-size:.85rem;margin:.1rem 0 .75rem 0">{chips}</div>',
                unsafe_allow_html=True)
