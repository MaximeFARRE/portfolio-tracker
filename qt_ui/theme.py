"""
Theme centralisé pour l'application Patrimoine Desktop.
Toutes les couleurs, styles et constantes visuelles sont définies ici.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings

_SETTINGS_ORG = "Famille"
_SETTINGS_APP = "PatrimoineDesktop"
_THEME_KEY = "ui_theme"

THEME_DARK = "dark"
THEME_LIGHT = "light"
AVAILABLE_THEMES = (THEME_DARK, THEME_LIGHT)


def _normalize_theme(value: object) -> str:
    mode = str(value or "").strip().lower()
    return THEME_LIGHT if mode == THEME_LIGHT else THEME_DARK


def get_saved_theme() -> str:
    try:
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        return _normalize_theme(settings.value(_THEME_KEY, THEME_DARK))
    except Exception:
        return THEME_DARK


def set_saved_theme(theme_mode: str) -> str:
    mode = _normalize_theme(theme_mode)
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    settings.setValue(_THEME_KEY, mode)
    settings.sync()
    return mode


def get_current_theme() -> str:
    return _ACTIVE_THEME


def is_dark_theme() -> bool:
    return _ACTIVE_THEME == THEME_DARK


_PALETTE_DARK = {
    "BG_PRIMARY": "#0e1117",
    "BG_SIDEBAR": "#0f1623",
    "BG_CARD": "#1a1f2e",
    "BG_CARD_ALT": "#151b27",
    "BG_HOVER": "#1e2538",
    "BG_ACTIVE": "#1e3a5f",
    "BG_ACTIVE_HOVER": "#1e4a7f",
    "BORDER_DEFAULT": "#2a3040",
    "BORDER_SUBTLE": "#1e2538",
    "TEXT_PRIMARY": "#e2e8f0",
    "TEXT_SECONDARY": "#94a3b8",
    "TEXT_MUTED": "#64748b",
    "TEXT_DISABLED": "#475569",
    "TEXT_DARK": "#334155",
    "ACCENT_BLUE": "#60a5fa",
    "ACCENT_BLUE_BORDER": "#2563eb",
    "COLOR_SUCCESS": "#22c55e",
    "COLOR_ERROR": "#ef4444",
    "COLOR_WARNING": "#f59e0b",
    "COLOR_SELECTION": "#2563eb",
    "COLOR_UNDO_BG": "#431407",
    "COLOR_UNDO_FG": "#fb923c",
    "COLOR_UNDO_HOVER": "#7c2d12",
    "COLOR_BTN_SUCCESS_BG": "#166534",
    "COLOR_BTN_SUCCESS_FG": "#86efac",
    "COLOR_BTN_SUCCESS_HOVER": "#14532d",
    "COLOR_DANGER_BG": "#7f1d1d",
    "COLOR_DANGER_FG": "#fca5a5",
    "COLOR_DANGER_HOVER": "#991b1b",
    "CHART_GREEN": "#22c55e",
    "CHART_RED": "#ef4444",
    "CHART_BLUE": "#60a5fa",
    "CHART_PURPLE": "#a78bfa",
    "CHART_SANKEY": "rgba(37,99,235,0.3)",
}

_PALETTE_LIGHT = {
    "BG_PRIMARY": "#f4f7fb",
    "BG_SIDEBAR": "#ecf1f8",
    "BG_CARD": "#ffffff",
    "BG_CARD_ALT": "#f8fafc",
    "BG_HOVER": "#dde6f2",
    "BG_ACTIVE": "#dbeafe",
    "BG_ACTIVE_HOVER": "#bfdbfe",
    "BORDER_DEFAULT": "#cbd5e1",
    "BORDER_SUBTLE": "#d7e0ed",
    "TEXT_PRIMARY": "#0f172a",
    "TEXT_SECONDARY": "#334155",
    "TEXT_MUTED": "#475569",
    "TEXT_DISABLED": "#64748b",
    "TEXT_DARK": "#94a3b8",
    "ACCENT_BLUE": "#2563eb",
    "ACCENT_BLUE_BORDER": "#1d4ed8",
    "COLOR_SUCCESS": "#16a34a",
    "COLOR_ERROR": "#dc2626",
    "COLOR_WARNING": "#d97706",
    "COLOR_SELECTION": "#93c5fd",
    "COLOR_UNDO_BG": "#ffedd5",
    "COLOR_UNDO_FG": "#c2410c",
    "COLOR_UNDO_HOVER": "#fed7aa",
    "COLOR_BTN_SUCCESS_BG": "#dcfce7",
    "COLOR_BTN_SUCCESS_FG": "#166534",
    "COLOR_BTN_SUCCESS_HOVER": "#bbf7d0",
    "COLOR_DANGER_BG": "#fee2e2",
    "COLOR_DANGER_FG": "#b91c1c",
    "COLOR_DANGER_HOVER": "#fecaca",
    "CHART_GREEN": "#16a34a",
    "CHART_RED": "#dc2626",
    "CHART_BLUE": "#2563eb",
    "CHART_PURPLE": "#7c3aed",
    "CHART_SANKEY": "rgba(37,99,235,0.25)",
}

_ACTIVE_THEME = get_saved_theme()
_PALETTE = _PALETTE_LIGHT if _ACTIVE_THEME == THEME_LIGHT else _PALETTE_DARK

# ─── Couleurs de base ──────────────────────────────────────────────────────

BG_PRIMARY = _PALETTE["BG_PRIMARY"]       # Fond principal de l'application
BG_SIDEBAR = _PALETTE["BG_SIDEBAR"]       # Fond sidebar / headers
BG_CARD = _PALETTE["BG_CARD"]             # Fond des cartes, inputs, tableaux (alt row)
BG_CARD_ALT = _PALETTE["BG_CARD_ALT"]     # Fond alterné des lignes de tableaux
BG_HOVER = _PALETTE["BG_HOVER"]           # Fond hover des éléments interactifs
BG_ACTIVE = _PALETTE["BG_ACTIVE"]         # Fond des éléments actifs (boutons, sélection)
BG_ACTIVE_HOVER = _PALETTE["BG_ACTIVE_HOVER"]  # Fond hover des éléments actifs

BORDER_DEFAULT = _PALETTE["BORDER_DEFAULT"]   # Bordures des inputs, tableaux
BORDER_SUBTLE = _PALETTE["BORDER_SUBTLE"]     # Bordures subtiles (séparateurs, groupbox)

TEXT_PRIMARY = _PALETTE["TEXT_PRIMARY"]      # Texte principal
TEXT_SECONDARY = _PALETTE["TEXT_SECONDARY"]  # Texte secondaire (labels, titres de section)
TEXT_MUTED = _PALETTE["TEXT_MUTED"]          # Texte discret (statuts, hints)
TEXT_DISABLED = _PALETTE["TEXT_DISABLED"]    # Texte désactivé
TEXT_DARK = _PALETTE["TEXT_DARK"]            # Texte très discret (version)

ACCENT_BLUE = _PALETTE["ACCENT_BLUE"]      # Accent principal (onglets actifs, liens)
ACCENT_BLUE_BORDER = _PALETTE["ACCENT_BLUE_BORDER"]

COLOR_SUCCESS = _PALETTE["COLOR_SUCCESS"]    # Vert succès
COLOR_ERROR = _PALETTE["COLOR_ERROR"]        # Rouge erreur
COLOR_WARNING = _PALETTE["COLOR_WARNING"]    # Orange avertissement
COLOR_SELECTION = _PALETTE["COLOR_SELECTION"]  # Bleu sélection tableau

# ─── Couleurs KPI tones ───────────────────────────────────────────────────

if _ACTIVE_THEME == THEME_LIGHT:
    KPI_TONES = {
        "primary": ("#dbeafe", "#1e3a8a"),
        "blue":    ("#dbeafe", "#1e3a8a"),
        "green":   ("#dcfce7", "#166534"),
        "purple":  ("#ede9fe", "#5b21b6"),
        "neutral": (BG_CARD, TEXT_SECONDARY),
        "red":     ("#fee2e2", "#991b1b"),
        "bank":    ("#dcfce7", "#166534"),
        "broker":  ("#dbeafe", "#1e3a8a"),
        "pe":      ("#ede9fe", "#5b21b6"),
        "success": ("#dcfce7", "#166534"),
        "alert":   ("#fee2e2", "#b91c1c"),
    }
else:
    KPI_TONES = {
        "primary": ("#111827", "#E5E7EB"),
        "blue":    ("#1E3A8A", "#DBEAFE"),
        "green":   ("#0B3B2E", "#D1FAE5"),
        "purple":  ("#4C1D95", "#EDE9FE"),
        "neutral": (BG_CARD, TEXT_SECONDARY),
        "red":     ("#7F1D1D", "#FEE2E2"),
        "bank":    ("#0B3B2E", "#D1FAE5"),
        "broker":  ("#1E3A8A", "#DBEAFE"),
        "pe":      ("#4C1D95", "#EDE9FE"),
        "success": ("#0a2e1a", "#4ade80"),
        "alert":   ("#2e0a0a", "#f87171"),
    }

# ─── Couleurs spécifiques ─────────────────────────────────────────────────

COLOR_UNDO_BG = _PALETTE["COLOR_UNDO_BG"]
COLOR_UNDO_FG = _PALETTE["COLOR_UNDO_FG"]
COLOR_UNDO_HOVER = _PALETTE["COLOR_UNDO_HOVER"]

COLOR_BTN_SUCCESS_BG = _PALETTE["COLOR_BTN_SUCCESS_BG"]
COLOR_BTN_SUCCESS_FG = _PALETTE["COLOR_BTN_SUCCESS_FG"]
COLOR_BTN_SUCCESS_HOVER = _PALETTE["COLOR_BTN_SUCCESS_HOVER"]

COLOR_DANGER_BG = _PALETTE["COLOR_DANGER_BG"]
COLOR_DANGER_FG = _PALETTE["COLOR_DANGER_FG"]
COLOR_DANGER_HOVER = _PALETTE["COLOR_DANGER_HOVER"]

# Couleurs des graphiques
CHART_GREEN = _PALETTE["CHART_GREEN"]
CHART_RED = _PALETTE["CHART_RED"]
CHART_BLUE = _PALETTE["CHART_BLUE"]
CHART_PURPLE = _PALETTE["CHART_PURPLE"]
CHART_SANKEY = _PALETTE["CHART_SANKEY"]

# ─── Styles réutilisables ─────────────────────────────────────────────────

STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background: {BG_ACTIVE}; color: {ACCENT_BLUE}; border: none;
        border-radius: 6px; padding: 8px 16px; font-size: 13px;
    }}
    QPushButton:hover {{ background: {BG_ACTIVE_HOVER}; }}
    QPushButton:disabled {{ background: {BG_CARD}; color: {TEXT_DISABLED}; }}
"""

STYLE_BTN_PRIMARY_BORDERED = f"""
    QPushButton {{
        background: {BG_ACTIVE}; color: {ACCENT_BLUE}; border: 1px solid {ACCENT_BLUE_BORDER};
        border-radius: 4px; padding: 8px 18px; font-size: 13px; font-weight: bold;
    }}
    QPushButton:hover {{ background: {ACCENT_BLUE_BORDER}; color: white; }}
    QPushButton:pressed {{ background: #1d4ed8; }}
"""

STYLE_BTN_SUCCESS = f"""
    QPushButton {{
        background: #14532d; color: #4ade80; border: 1px solid #16a34a;
        border-radius: 4px; padding: 8px 18px; font-size: 13px; font-weight: bold;
    }}
    QPushButton:hover {{ background: #16a34a; color: white; }}
    QPushButton:pressed {{ background: #15803d; }}
"""

STYLE_BTN_CREATE = f"""
    QPushButton {{
        background: {COLOR_BTN_SUCCESS_BG}; color: {COLOR_BTN_SUCCESS_FG}; border: none;
        border-radius: 6px; padding: 8px 14px;
    }}
    QPushButton:hover {{ background: {COLOR_BTN_SUCCESS_HOVER}; }}
"""

STYLE_BTN_DANGER = f"""
    QPushButton {{
        background: {COLOR_DANGER_BG}; color: {COLOR_DANGER_FG}; border: none;
        border-radius: 6px; padding: 8px 16px;
    }}
    QPushButton:hover {{ background: {COLOR_DANGER_HOVER}; }}
"""

STYLE_BTN_UNDO = f"""
    QPushButton {{
        background: {COLOR_UNDO_BG}; color: {COLOR_UNDO_FG}; border: none;
        border-radius: 6px; padding: 8px 14px;
    }}
    QPushButton:hover {{ background: {COLOR_UNDO_HOVER}; }}
"""

STYLE_INPUT = f"""
    background: {BG_CARD}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_DEFAULT};
    border-radius: 4px; padding: 4px 6px; font-size: 13px;
"""

STYLE_INPUT_FOCUS = f"""
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit {{
        background: {BG_CARD}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_DEFAULT};
        border-radius: 4px; padding: 6px 8px; font-size: 13px;
    }}
    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
    QComboBox:focus, QDateEdit:focus {{ border: 1px solid {ACCENT_BLUE}; }}
    QComboBox QAbstractItemView {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; }}
"""

STYLE_LABEL = f"color: {TEXT_SECONDARY}; font-size: 12px; margin-bottom: 2px;"

STYLE_GROUP = f"""
    QGroupBox {{
        color: {TEXT_SECONDARY}; border: 1px solid {BORDER_SUBTLE};
        border-radius: 6px; padding: 8px; margin-top: 6px;
    }}
    QGroupBox::title {{ subcontrol-position: top left; padding: 2px 8px; }}
"""

STYLE_TAB = f"""
    QTabWidget::pane {{ border: none; background: {BG_PRIMARY}; }}
    QTabBar::tab {{
        background: {BG_SIDEBAR}; color: {TEXT_MUTED}; padding: 10px 18px;
        border: none; border-bottom: 2px solid transparent; font-size: 13px;
    }}
    QTabBar::tab:selected {{ color: {ACCENT_BLUE}; border-bottom: 2px solid {ACCENT_BLUE}; }}
    QTabBar::tab:hover {{ color: {TEXT_SECONDARY}; }}
"""

STYLE_TAB_INNER = f"""
    QTabWidget::pane {{ border: none; background: {BG_PRIMARY}; }}
    QTabBar::tab {{
        background: {BG_SIDEBAR}; color: {TEXT_MUTED}; padding: 8px 16px;
        border: none; border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {ACCENT_BLUE}; border-bottom: 2px solid {ACCENT_BLUE}; }}
"""

STYLE_TABLE = f"""
    QTableView {{
        background-color: {BG_CARD_ALT};
        color: {TEXT_PRIMARY};
        gridline-color: {BORDER_DEFAULT};
        border: 1px solid {BORDER_DEFAULT};
        selection-background-color: {COLOR_SELECTION};
        font-size: 13px;
    }}
    QHeaderView::section {{
        background-color: {BG_CARD};
        color: {TEXT_SECONDARY};
        padding: 6px;
        border: none;
        border-bottom: 1px solid {BORDER_DEFAULT};
        font-weight: bold;
        font-size: 12px;
    }}
    QTableView::item:selected {{
        background-color: {BG_ACTIVE};
    }}
"""

STYLE_SCROLLAREA = f"QScrollArea {{ border: none; background: {BG_PRIMARY}; }}"

STYLE_PROGRESS = f"""
    QProgressBar {{ background: {BG_CARD}; border-radius: 4px; height: 16px; }}
    QProgressBar::chunk {{ background: {COLOR_SUCCESS}; border-radius: 4px; }}
"""

STYLE_NAV_BTN = f"""
    QPushButton {{{{
        background: transparent;
        color: {{color}};
        text-align: left;
        padding: 10px 16px;
        border: none;
        border-radius: 6px;
        font-size: 13px;
    }}}}
    QPushButton:hover {{{{
        background: {BG_HOVER};
        color: {TEXT_PRIMARY};
    }}}}
    QPushButton:checked {{{{
        background: {BG_ACTIVE};
        color: {ACCENT_BLUE};
        font-weight: bold;
    }}}}
"""

# ─── Styles pour les sections de titre ─────────────────────────────────────

STYLE_TITLE = f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: bold;"
STYLE_TITLE_LARGE = f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: bold;"
STYLE_TITLE_XL = f"color: {TEXT_PRIMARY}; font-size: 22px; font-weight: bold;"
STYLE_SECTION = f"color: {TEXT_SECONDARY}; font-size: 14px; font-weight: bold;"
STYLE_SECTION_MARGIN = f"color: {TEXT_SECONDARY}; font-size: 14px; font-weight: bold; margin-top: 12px;"
STYLE_SUBSECTION = f"color: {TEXT_SECONDARY}; font-size: 13px; font-weight: bold;"
STYLE_STATUS = f"color: {TEXT_MUTED}; font-size: 12px;"
STYLE_STATUS_SUCCESS = f"color: {COLOR_SUCCESS}; font-size: 12px;"
STYLE_STATUS_ERROR = f"color: {COLOR_ERROR}; font-size: 12px;"
STYLE_STATUS_WARNING = f"color: {COLOR_WARNING}; font-size: 12px;"

STYLE_FORM_LABEL = f"color: {TEXT_SECONDARY}; font-size: 13px;"

# ─── Styles globaux application ────────────────────────────────────────────

def app_style_sheet() -> str:
    """Styles globaux Qt appliqués au lancement de l'application."""
    return f"""
        QWidget {{
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 13px;
            color: {TEXT_PRIMARY};
        }}
        QLabel {{ color: {TEXT_PRIMARY}; }}
        QScrollBar:vertical {{
            background: {BG_SIDEBAR};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {TEXT_DARK};
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{
            background: {BG_SIDEBAR};
            height: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {TEXT_DARK};
            border-radius: 4px;
            min-width: 20px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {TEXT_MUTED}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QToolTip {{
            background: {BG_HOVER};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_DEFAULT};
            padding: 4px;
        }}
    """

# ─── Plotly layout commun ─────────────────────────────────────────────────

PLOTLY_LAYOUT = dict(
    paper_bgcolor=BG_PRIMARY,
    plot_bgcolor=BG_PRIMARY,
    template=("plotly_dark" if is_dark_theme() else "plotly_white"),
    margin=dict(l=0, r=0, t=10, b=0),
)

PLOTLY_RANGE_SELECTOR = dict(
    buttons=list([
        dict(count=1, label="1M", step="month", stepmode="backward"),
        dict(count=3, label="3M", step="month", stepmode="backward"),
        dict(count=6, label="6M", step="month", stepmode="backward"),
        dict(count=1, label="1Y", step="year", stepmode="backward"),
        dict(step="all", label="ALL")
    ]),
    bgcolor=("rgba(30, 41, 59, 0.4)" if is_dark_theme() else "rgba(148,163,184,0.25)"),
    activecolor=ACCENT_BLUE,
    font=dict(size=11, color=TEXT_PRIMARY),
    borderwidth=1,
    bordercolor=BORDER_SUBTLE,
    x=0, y=1.1,
)


def plotly_layout(**overrides) -> dict:
    """Retourne un dict de layout Plotly avec le thème de l'app."""
    layout = {**PLOTLY_LAYOUT}
    layout.update(overrides)
    return layout


def plotly_time_series_layout(**overrides) -> dict:
    """Layout spécialisé pour les séries temporelles (sélecteurs + slider)."""
    ts_overrides = {
        "xaxis": dict(
            rangeselector=PLOTLY_RANGE_SELECTOR,
            rangeslider=dict(visible=True, thickness=0.05, bgcolor="rgba(0,0,0,0)"),
            type="date"
        ),
        "margin": dict(l=10, r=10, t=40, b=10),
    }
    # Fusion récursive simple
    for k, v in overrides.items():
        if k in ts_overrides and isinstance(ts_overrides[k], dict) and isinstance(v, dict):
            ts_overrides[k].update(v)
        else:
            ts_overrides[k] = v
    return plotly_layout(**ts_overrides)
