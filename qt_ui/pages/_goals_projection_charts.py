"""
qt_ui/pages/_goals_projection_charts.py

Fonctions de construction des figures Plotly pour la page Objectifs & Projection.
Ce module ne contient que de la logique de rendu graphique, aucun calcul métier.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from qt_ui.theme import plotly_layout


def build_projection_chart(
    active_df: pd.DataFrame,
    active_scenario_name: str,
    standard_results: dict[str, pd.DataFrame],
) -> go.Figure:
    """
    Construit la courbe principale de projection patrimoniale.

    Args:
        active_df: DataFrame de la projection active (colonnes: month_index, projected_net_worth, fire_target).
        active_scenario_name: Libellé du scénario actif (affiché dans la légende).
        standard_results: Dict {label: DataFrame} des scénarios Pessimiste/Médian/Optimiste à surposer.

    Returns:
        Figure Plotly prête à afficher.
    """
    fig = go.Figure()
    x_active = active_df["month_index"] / 12.0
    fig.add_trace(go.Scatter(
        x=x_active,
        y=active_df["projected_net_worth"],
        mode="lines",
        line=dict(color="#60a5fa", width=3),
        name=f"Scénario actif ({active_scenario_name})",
    ))

    fire_target = float(active_df.iloc[-1].get("fire_target", 0.0)) if not active_df.empty else 0.0
    fig.add_trace(go.Scatter(
        x=x_active,
        y=[fire_target] * len(active_df),
        mode="lines",
        line=dict(color="#f59e0b", width=2, dash="dash"),
        name="Objectif FIRE",
    ))

    std_colors = {"Pessimiste": "#ef4444", "Médian": "#22c55e", "Optimiste": "#93c5fd"}
    for label, df_std in standard_results.items():
        fig.add_trace(go.Scatter(
            x=df_std["month_index"] / 12.0,
            y=df_std["projected_net_worth"],
            mode="lines",
            line=dict(color=std_colors.get(label, "#94a3b8"), width=1.8, dash="dot"),
            name=label,
        ))

    fig.update_layout(**plotly_layout(
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    ))
    fig.update_xaxes(title="Années")
    fig.update_yaxes(title="Patrimoine net (€)")
    return fig


def build_fire_progress_chart(df: pd.DataFrame) -> go.Figure:
    """
    Construit le graphique de progression FIRE (% du cap FIRE atteint dans le temps).

    Args:
        df: DataFrame de la projection (colonnes: month_index, fire_progress_pct).

    Returns:
        Figure Plotly prête à afficher.
    """
    fig = go.Figure()
    x_vals = df["month_index"] / 12.0
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=df["fire_progress_pct"],
        mode="lines",
        line=dict(color="#22c55e", width=2.5),
        name="Progression FIRE",
    ))
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=[100.0] * len(df),
        mode="lines",
        line=dict(color="#f59e0b", width=1.5, dash="dash"),
        name="Seuil FIRE",
    ))
    fig.update_layout(**plotly_layout(
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    ))
    fig.update_xaxes(title="Années")
    fig.update_yaxes(title="Progression (%)")
    return fig
