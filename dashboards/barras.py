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


def tablas_resumen_mis_ventas(mv) -> None:
    """Dos tablas (cobertura en clientes y volumen en unidades) con el resumen de Mis Ventas por vendedor.
    `mv`: tabla de `mis_ventas_vendedores` (ya filtrada a los vendedores que se muestran)."""
    import streamlit as st

    nombres = {"COBERTURA": ("Cobertura (clientes)", "clientes"), "VOLUMEN": ("Volumen (unidades)", "unidades")}
    for tipo, (titulo, unidad) in nombres.items():
        r = TB.resumen_mis_ventas(mv, tipo)
        if r.empty:
            continue
        st.markdown(f"**Resumen por vendedor · {titulo}**")
        t = r.rename(columns={"vendedor": "Vendedor", "objetivo": "Objetivo", "avance": "Avance actual", "pct_avance": "% avance actual",
                              "proyectado": "Proyectado", "pct_proyeccion": "% proyección", "media_necesaria": "Media necesaria"})
        for c in ("% avance actual", "% proyección", "Media necesaria"):
            t[c] = t[c] * 100
        st.dataframe(t[["Vendedor", "Objetivo", "Avance actual", "% avance actual", "Proyectado", "% proyección", "Media necesaria"]],
                     hide_index=True, use_container_width=True, column_config={
                         "Objetivo": st.column_config.NumberColumn(format="%.0f", help=f"Suma de los objetivos de sus campañas ({unidad})."),
                         "Avance actual": st.column_config.NumberColumn(format="%.0f", help=f"Suma de lo logrado en sus campañas ({unidad})."),
                         "% avance actual": st.column_config.NumberColumn(format="%.0f%%"),
                         "Proyectado": st.column_config.NumberColumn(format="%.0f", help="Suma de lo que cada campaña llegaría a lograr al cierre del bimestre al ritmo actual."),
                         "% proyección": st.column_config.NumberColumn(format="%.0f%%"),
                         "Media necesaria": st.column_config.NumberColumn(format="%.0f%%", help="Avance actual ÷ objetivo.")})
