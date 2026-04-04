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
<p style="color:#555;font-family:sans-serif;font-size:14px;">Aucune donnée</p>
</body>
</html>
"""

_LOADING_HTML = f"""
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ margin:0; background:{BG_PRIMARY}; height:100vh; display:flex; flex-direction:column; justify-content:center; padding: 20px; box-sizing: border-box; overflow: hidden; }}
  .pulse {{ 
    background: linear-gradient(90deg, #1e293b 25%, #334155 50%, #1e293b 75%);
    background-size: 200% 100%;
    animation: loading 1.5s infinite;
    border-radius: 8px;
    margin-bottom: 12px;
  }}
  @keyframes loading {{
    0% {{ background-position: 200% 0; }}
    100% {{ background-position: -200% 0; }}
  }}
  .bar-chart {{ height: 100%; display: flex; align-items: flex-end; gap: 8px; }}
  .bar {{ flex: 1; border-radius: 4px 4px 0 0; background: #1e293b; animation: pulse 1.5s infinite ease-in-out; }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 0.3; }}
    50% {{ opacity: 0.7; }}
  }}
</style>
</head>
<body>
  <div class="pulse" style="height: 20px; width: 40%; margin-bottom: 20px;"></div>
  <div class="bar-chart">
    <div class="bar" style="height: 60%;"></div>
    <div class="bar" style="height: 80%; animation-delay: 0.2s;"></div>
    <div class="bar" style="height: 40%; animation-delay: 0.4s;"></div>
    <div class="bar" style="height: 90%; animation-delay: 0.6s;"></div>
    <div class="bar" style="height: 50%; animation-delay: 0.8s;"></div>
    <div class="bar" style="height: 70%; animation-delay: 1.0s;"></div>
  </div>
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
        self._loading = False
        self.setHtml(_EMPTY_HTML)

    def set_loading(self, loading: bool) -> None:
        """Active/Désactive l'état de chargement visuel (skeleton)."""
        self._loading = loading
        if loading:
            self.setHtml(_LOADING_HTML)
        elif not self._loaded and not self._pending_fig:
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
