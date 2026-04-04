"""
Widget KpiCard — remplace la fonction _kpi_card() dupliquée dans 5 fichiers ui/*.py.
"""
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from qt_ui.theme import KPI_TONES

# Nombre maximum de lignes de détail supportées par la carte
_MAX_DETAILS = 4


class KpiCard(QFrame):
    """
    Carte KPI avec titre, valeur principale, sous-titre optionnel et
    jusqu'à _MAX_DETAILS lignes de détail (label + valeur sur la même ligne).

    Utilisation :
        card.set_content(
            "Dividendes", "3 450 €",
            emoji="💵", tone="success",
            details=[
                ("12 derniers mois", "1 200 €"),
                ("Moy. / mois (12m)", "100 €"),
            ]
        )
    """

    def __init__(self, title: str = "", value: str = "", subtitle: str = "",
                 emoji: str = "", tone: str = "neutral", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(140)
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)

        self._title_label = QLabel()
        self._title_label.setWordWrap(True)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._value_label = QLabel()
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        font_val = QFont()
        font_val.setPointSize(15)
        font_val.setBold(True)
        self._value_label.setFont(font_val)

        # Sous-titre classique (rétrocompatibilité)
        self._subtitle_label = QLabel()
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._subtitle_label.setWordWrap(True)

        layout.addWidget(self._title_label)
        layout.addWidget(self._value_label)
        layout.addWidget(self._subtitle_label)

        # Séparateur discret avant les détails
        self._sep_label = QLabel()
        self._sep_label.setFixedHeight(1)
        self._sep_label.setVisible(False)
        layout.addWidget(self._sep_label)

        # Lignes de détail : paires (QLabel libellé, QLabel valeur)
        self._detail_rows: list[tuple[QLabel, QLabel]] = []
        for _ in range(_MAX_DETAILS):
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            lbl_key = QLabel()
            lbl_key.setAlignment(Qt.AlignmentFlag.AlignLeft)
            lbl_val = QLabel()
            lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight)
            row_layout.addWidget(lbl_key, stretch=1)
            row_layout.addWidget(lbl_val)
            container = QFrame()
            container.setLayout(row_layout)
            container.setVisible(False)
            layout.addWidget(container)
            self._detail_rows.append((lbl_key, lbl_val, container))  # type: ignore[misc]

        layout.addStretch()

        self.set_content(title, value, subtitle, emoji, tone)

    def set_content(self, title: str, value: str, subtitle: str = "",
                    emoji: str = "", tone: str = "neutral",
                    details: list[tuple[str, str]] | None = None) -> None:
        """
        Met à jour le contenu de la carte.

        Args:
            title:    Titre affiché en petit au-dessus de la valeur.
            value:    Valeur principale (grande police, en gras).
            subtitle: Ligne de sous-titre unique (rétrocompatibilité).
            emoji:    Emoji préfixé au titre.
            tone:     Clé dans KPI_TONES pour la couleur de fond/texte.
            details:  Liste de (libellé, valeur) affichés en mini-tableau
                      sous la valeur principale.  Ex : [("12 m", "1 200 €"), …]
        """
        bg, fg = KPI_TONES.get(tone, KPI_TONES["neutral"])
        fg_muted = _muted(fg)

        prefix = f"{emoji} " if emoji else ""
        self._title_label.setText(f"{prefix}{title}")
        self._value_label.setText(str(value))
        self._subtitle_label.setText(str(subtitle) if subtitle else "")
        self._subtitle_label.setVisible(bool(subtitle))

        # Lignes de détail
        details = details or []
        has_details = bool(details)
        self._sep_label.setVisible(has_details)
        self._sep_label.setStyleSheet(f"background: {fg_muted}; border: none;")

        for i, (lbl_key, lbl_val, container) in enumerate(self._detail_rows):
            if i < len(details):
                key_text, val_text = details[i]
                lbl_key.setText(str(key_text))
                lbl_val.setText(str(val_text))
                container.setVisible(True)
                lbl_key.setStyleSheet(f"color: {fg_muted}; font-size: 10px; background: transparent;")
                lbl_val.setStyleSheet(f"color: {fg}; font-size: 10px; font-weight: 500; background: transparent;")
            else:
                container.setVisible(False)

        self.setStyleSheet(f"""
            KpiCard {{
                background-color: {bg};
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.06);
            }}
            QLabel {{
                background: transparent;
                color: {fg};
            }}
        """)
        self._title_label.setStyleSheet(f"color: {fg_muted}; font-size: 11px;")
        self._value_label.setStyleSheet(f"color: {fg}; font-size: 15px; font-weight: bold;")
        self._subtitle_label.setStyleSheet(f"color: {fg_muted}; font-size: 11px;")


def _muted(hex_color: str, alpha: float = 0.65) -> str:
    """Retourne une version semi-transparente d'une couleur hex pour les textes secondaires."""
    # On utilise rgba() si possible, sinon on retourne la couleur telle quelle
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    except Exception:
        return hex_color
