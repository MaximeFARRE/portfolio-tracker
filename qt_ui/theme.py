"""
Theme centralisé pour l'application Patrimoine Desktop.
Toutes les couleurs, styles et constantes visuelles sont définies ici.
"""

# ─── Couleurs de base ──────────────────────────────────────────────────────

BG_PRIMARY = "#0e1117"       # Fond principal de l'application
BG_SIDEBAR = "#0f1623"       # Fond sidebar / headers
BG_CARD = "#1a1f2e"          # Fond des cartes, inputs, tableaux (alt row)
BG_CARD_ALT = "#151b27"      # Fond alterné des lignes de tableaux
BG_HOVER = "#1e2538"         # Fond hover des éléments interactifs
BG_ACTIVE = "#1e3a5f"        # Fond des éléments actifs (boutons, sélection)
BG_ACTIVE_HOVER = "#1e4a7f"  # Fond hover des éléments actifs

BORDER_DEFAULT = "#2a3040"   # Bordures des inputs, tableaux
BORDER_SUBTLE = "#1e2538"    # Bordures subtiles (séparateurs, groupbox)

TEXT_PRIMARY = "#e2e8f0"      # Texte principal
TEXT_SECONDARY = "#94a3b8"    # Texte secondaire (labels, titres de section)
TEXT_MUTED = "#64748b"        # Texte discret (statuts, hints)
TEXT_DISABLED = "#475569"     # Texte désactivé
TEXT_DARK = "#334155"         # Texte très discret (version)

ACCENT_BLUE = "#60a5fa"      # Accent principal (onglets actifs, liens)
ACCENT_BLUE_BORDER = "#2563eb"

COLOR_SUCCESS = "#22c55e"    # Vert succès
COLOR_ERROR = "#ef4444"      # Rouge erreur
COLOR_WARNING = "#f59e0b"    # Orange avertissement
COLOR_SELECTION = "#2563eb"  # Bleu sélection tableau

# ─── Couleurs KPI tones ───────────────────────────────────────────────────

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
    # Tones dynamiques (gain/perte)
    "success": ("#0a2e1a", "#4ade80"),
    "alert":   ("#2e0a0a", "#f87171"),
}

# ─── Couleurs spécifiques ─────────────────────────────────────────────────

COLOR_UNDO_BG = "#431407"
COLOR_UNDO_FG = "#fb923c"
COLOR_UNDO_HOVER = "#7c2d12"

COLOR_BTN_SUCCESS_BG = "#166534"
COLOR_BTN_SUCCESS_FG = "#86efac"
COLOR_BTN_SUCCESS_HOVER = "#14532d"

COLOR_DANGER_BG = "#7f1d1d"
COLOR_DANGER_FG = "#fca5a5"
COLOR_DANGER_HOVER = "#991b1b"

# Couleurs des graphiques
CHART_GREEN = "#22c55e"
CHART_RED = "#ef4444"
CHART_BLUE = "#60a5fa"
CHART_PURPLE = "#a78bfa"
CHART_SANKEY = "rgba(37,99,235,0.3)"

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
        color: #e0e0e0;
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

# ─── Plotly layout commun ─────────────────────────────────────────────────

PLOTLY_LAYOUT = dict(
    paper_bgcolor=BG_PRIMARY,
    plot_bgcolor=BG_PRIMARY,
    template="plotly_dark",
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
    bgcolor="rgba(30, 41, 59, 0.4)",
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
