"""
Widget QWebEngineView encapsulant un graphique Plotly.
Remplace st.plotly_chart() et st.line_chart() / st.bar_chart() de Streamlit.
Supporte le lazy loading : le chart n'est chargé que quand le widget est visible.
"""
import logging
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl
import plotly.graph_objects as go

from qt_ui.theme import BG_PRIMARY

logger = logging.getLogger(__name__)

_EMPTY_HTML = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;background:{BG_PRIMARY};display:flex;align-items:center;justify-content:center;height:100vh;">
<p style="color:#555;font-family:sans-serif;font-size:14px;">Aucune donn\u00e9e</p>
</body>
</html>
"""


class PlotlyView(QWebEngineView):
    """Widget pour afficher un graphique Plotly dans une vue web embarquée.
    Supporte le lazy loading : si le widget n'est pas visible, le rendu est
    différé jusqu'à ce qu'il le devienne.
    """

    def __init__(self, parent=None, min_height: int = 350):
        super().__init__(parent)
        self.setMinimumHeight(min_height)
        self._pending_fig: go.Figure | None = None
        self._loaded = False
        self.setHtml(_EMPTY_HTML)

    def set_figure(self, fig: go.Figure) -> None:
        """Affiche un graphique Plotly (Figure ou express)."""
        if fig is None:
            self.clear_figure()
            return
        if self.isVisible():
            self._render(fig)
        else:
            self._pending_fig = fig

    def clear_figure(self) -> None:
        """Affiche l'état vide et libère la figure en attente."""
        self._pending_fig = None
        self._loaded = False
        self.setHtml(_EMPTY_HTML)

    def showEvent(self, event) -> None:
        """Rendu différé : charge la figure quand le widget devient visible."""
        super().showEvent(event)
        if self._pending_fig is not None:
            self._render(self._pending_fig)
            self._pending_fig = None

    def _render(self, fig: go.Figure) -> None:
        try:
            html = fig.to_html(
                include_plotlyjs="cdn",
                config={"displayModeBar": False, "responsive": True},
                full_html=True,
            )
            self.setHtml(html)
            self._loaded = True
        except Exception as e:
            logger.error("Erreur rendu Plotly : %s", e)
            self.setHtml(_EMPTY_HTML)
