"""Constantes visuales compartidas por los tableros (ver `03`: estética elegida por Juan)."""
AZUL = "#2a78d6"        # serie única
GRIS_MARCA = "#8a8a85"  # marcas de referencia (escalones, avance esperado): legible en claro y oscuro
# Color de las etiquetas de texto dentro de los gráficos. Altair dibuja el texto en negro por defecto (invisible en el
# tema oscuro) y detectar el tema desde Python no es confiable: gris medio fijo, legible en ambos (4,4:1 y 4,3:1).
TXT = "#787878"          # todo mark_text debe llevar color=TXT (nunca dejar el color por defecto)


def mostrar_logo(ancho: int = 200) -> None:
    """Logo de Pejinakis con versión para tema claro y para tema oscuro (se alterna por CSS según el tema del
    navegador/sistema, igual que Streamlit en modo "automático"). Imágenes embebidas en base64: sin archivos estáticos."""
    import base64
    from pathlib import Path

    import streamlit as st

    def b64(nombre: str) -> str:
        return base64.b64encode((Path(__file__).resolve().parent / "assets" / nombre).read_bytes()).decode()

    css = (
        f".logo-pej{{width:{ancho}px;max-width:60%;height:auto;margin:0 0 .25rem 0;}}"
        ".logo-pej.oscuro{display:none;}"
        "@media (prefers-color-scheme: dark){.logo-pej.claro{display:none;}.logo-pej.oscuro{display:block;}}"
    )
    # Todo en una línea y sin sangría: con 4+ espacios al inicio Markdown lo toma como bloque de código.
    html = (
        f"<style>{css}</style>"
        f'<img class="logo-pej claro" alt="Pejinakis" src="data:image/png;base64,{b64("logo-claro.png")}">'
        f'<img class="logo-pej oscuro" alt="Pejinakis" src="data:image/png;base64,{b64("logo-oscuro.png")}">'
    )
    st.markdown(html, unsafe_allow_html=True)


def esc(texto: str) -> str:
    """Escapa el `$` para st.write/markdown/caption: de lo contrario Streamlit lo toma como fórmula LaTeX
    ("M$ ... M$" se dibuja como matemática en cursiva). No hace falta en st.metric ni en tablas."""
    return texto.replace("$", r"\$")


def texto_grande(html: str, tam: str = "1.35rem") -> None:
    """Mensaje destacado (letra más grande). Acepta <b>…</b>; los `$` se escapan como entidad HTML para que
    Streamlit no los tome como fórmula."""
    import streamlit as st

    st.markdown(f'<div style="font-size:{tam};line-height:1.5;margin:.25rem 0 .5rem 0">{html.replace("$", "&#36;")}</div>',
                unsafe_allow_html=True)
