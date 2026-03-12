"""
ui/projections_overview.py
Page de projections patrimoniales multi-scénarios.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from services.projections import ScenarioParams, compute_three_scenarios, summary_table, project_patrimoine
from utils.format_monnaie import money


def _fmt(x) -> str:
    try:
        return money(float(x))
    except Exception:
        return "—"


def _load_patrimoine_initial(conn, person_id: int) -> dict:
    """Charge le dernier snapshot comme point de départ."""
    try:
        row = conn.execute(
            "SELECT bank_cash, bourse_holdings, pe_value, ent_value, credits_remaining "
            "FROM patrimoine_snapshots_weekly WHERE person_id=? ORDER BY week_date DESC LIMIT 1",
            (int(person_id),),
        ).fetchone()
        if row is None:
            return {"bank": 0.0, "bourse": 0.0, "pe": 0.0, "ent": 0.0, "credits": 0.0}
        def _v(row, key, idx):
            try:
                return float(row[key] or 0)
            except Exception:
                try:
                    return float(row[idx] or 0)
                except Exception:
                    return 0.0
        return {
            "bank": _v(row, "bank_cash", 0),
            "bourse": _v(row, "bourse_holdings", 1),
            "pe": _v(row, "pe_value", 2),
            "ent": _v(row, "ent_value", 3),
            "credits": _v(row, "credits_remaining", 4),
        }
    except Exception:
        return {"bank": 0.0, "bourse": 0.0, "pe": 0.0, "ent": 0.0, "credits": 0.0}


def _load_epargne_mensuelle(conn, person_id: int) -> float:
    """Épargne mensuelle approximative (derniers 3 mois)."""
    try:
        df_r = pd.read_sql_query(
            "SELECT SUM(montant) AS total FROM revenus WHERE person_id=? "
            "AND mois >= date('now', '-3 months')",
            conn, params=(int(person_id),),
        )
        df_d = pd.read_sql_query(
            "SELECT SUM(montant) AS total FROM depenses WHERE person_id=? "
            "AND mois >= date('now', '-3 months')",
            conn, params=(int(person_id),),
        )
        rev = float(df_r.iloc[0]["total"] or 0) if not df_r.empty else 0.0
        dep = float(df_d.iloc[0]["total"] or 0) if not df_d.empty else 0.0
        # moyenne mensuelle sur 3 mois
        return max(0.0, (rev - dep) / 3)
    except Exception:
        return 1_000.0


def afficher_projections_overview(conn, person_id: int):
    st.subheader("📈 Projections patrimoniales")
    st.caption("Simulation sur 3 scénarios avec hypothèses personnalisables.")

    pat = _load_patrimoine_initial(conn, person_id)
    epargne_auto = _load_epargne_mensuelle(conn, person_id)

    # ─── Point de départ ────────────────────────────────────────
    st.markdown("#### Point de départ (dernier snapshot)")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Banque", _fmt(pat["bank"]))
    c2.metric("Bourse", _fmt(pat["bourse"]))
    c3.metric("PE", _fmt(pat["pe"]))
    c4.metric("Entreprises", _fmt(pat["ent"]))
    c5.metric("Crédits", _fmt(pat["credits"]))

    if all(v == 0.0 for v in pat.values()):
        st.warning("Aucun snapshot disponible. Calcule d'abord un snapshot (Vue d'ensemble → Snapshot).")

    st.divider()

    # ─── Hypothèses globales ─────────────────────────────────────
    st.markdown("#### Hypothèses communes")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        horizon = st.slider("Horizon (années)", 1, 20, 10, key=f"proj_horizon_{person_id}")
    with col_b:
        epargne = st.number_input(
            "Épargne mensuelle (€)", min_value=0.0, max_value=50_000.0,
            value=float(round(epargne_auto, 0)), step=50.0,
            key=f"proj_epargne_{person_id}",
        )
    with col_c:
        remb_credit = st.number_input(
            "Remboursement crédit / mois (€)", min_value=0.0, max_value=10_000.0,
            value=0.0, step=50.0, key=f"proj_remb_{person_id}",
        )

    # ─── Hypothèses par scénario ─────────────────────────────────
    st.markdown("#### Hypothèses par scénario")
    col_p, col_b2, col_o = st.columns(3)

    with col_p:
        st.markdown("**Pessimiste** 🔴")
        r_bourse_p = st.slider("Bourse (%/an)", 0.0, 20.0, 4.0, 0.5, key=f"proj_bp_{person_id}")
        r_pe_p = st.slider("PE (%/an)", 0.0, 30.0, 5.0, 1.0, key=f"proj_pp_{person_id}")
        infl_p = st.slider("Inflation (%/an)", 0.0, 10.0, 3.0, 0.5, key=f"proj_ip_{person_id}")

    with col_b2:
        st.markdown("**Base** 🔵")
        r_bourse_b = st.slider("Bourse (%/an)", 0.0, 20.0, 7.0, 0.5, key=f"proj_bb_{person_id}")
        r_pe_b = st.slider("PE (%/an)", 0.0, 30.0, 10.0, 1.0, key=f"proj_pb_{person_id}")
        infl_b = st.slider("Inflation (%/an)", 0.0, 10.0, 2.0, 0.5, key=f"proj_ib_{person_id}")

    with col_o:
        st.markdown("**Optimiste** 🟢")
        r_bourse_o = st.slider("Bourse (%/an)", 0.0, 20.0, 10.0, 0.5, key=f"proj_bo_{person_id}")
        r_pe_o = st.slider("PE (%/an)", 0.0, 30.0, 15.0, 1.0, key=f"proj_po_{person_id}")
        infl_o = st.slider("Inflation (%/an)", 0.0, 10.0, 1.0, 0.5, key=f"proj_io_{person_id}")

    # ─── Calcul ──────────────────────────────────────────────────
    scenarios = {
        "Pessimiste": ScenarioParams(
            label="Pessimiste",
            taux_bourse_annuel=r_bourse_p, taux_pe_annuel=r_pe_p,
            epargne_mensuelle=epargne * 0.8, inflation_annuelle=infl_p,
            remboursement_mensuel_credit=remb_credit,
        ),
        "Base": ScenarioParams(
            label="Base",
            taux_bourse_annuel=r_bourse_b, taux_pe_annuel=r_pe_b,
            epargne_mensuelle=epargne, inflation_annuelle=infl_b,
            remboursement_mensuel_credit=remb_credit,
        ),
        "Optimiste": ScenarioParams(
            label="Optimiste",
            taux_bourse_annuel=r_bourse_o, taux_pe_annuel=r_pe_o,
            epargne_mensuelle=epargne * 1.2, inflation_annuelle=infl_o,
            remboursement_mensuel_credit=remb_credit,
        ),
    }

    results = {label: project_patrimoine(pat, sc, horizon) for label, sc in scenarios.items()}

    st.divider()

    # ─── Graphique Plotly ─────────────────────────────────────────
    st.markdown("#### Évolution du patrimoine net")
    colors = {"Pessimiste": "#EF4444", "Base": "#3B82F6", "Optimiste": "#22C55E"}

    fig = go.Figure()

    df_pess = results["Pessimiste"]
    df_opti = results["Optimiste"]

    # Zone ombrée entre pessimiste et optimiste
    fig.add_trace(go.Scatter(
        x=list(df_pess["annee"]) + list(df_opti["annee"][::-1]),
        y=list(df_pess["patrimoine_net"]) + list(df_opti["patrimoine_net"][::-1]),
        fill="toself",
        fillcolor="rgba(59, 130, 246, 0.08)",
        line=dict(color="rgba(0,0,0,0)"),
        showlegend=False,
        hoverinfo="skip",
    ))

    for label, df in results.items():
        fig.add_trace(go.Scatter(
            x=df["annee"],
            y=df["patrimoine_net"],
            name=label,
            mode="lines",
            line=dict(color=colors[label], width=2.5),
            hovertemplate=f"<b>{label}</b><br>Année %{{x:.1f}}<br>%{{y:,.0f}} €<extra></extra>",
        ))

    fig.update_layout(
        height=360,
        xaxis=dict(title="Années", tickformat=".0f"),
        yaxis=dict(title="Patrimoine net (€)", tickformat=",.0f"),
        legend=dict(orientation="h", y=1.05),
        margin=dict(l=0, r=0, t=20, b=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ─── Tableau résumé ───────────────────────────────────────────
    st.markdown("#### Résumé à différents horizons")
    h_available = [h for h in [1, 3, 5, 10, 15, 20] if h <= horizon]
    df_summary = summary_table(results, horizons=h_available)

    # Formatage
    for col in df_summary.columns:
        if col != "Scénario":
            df_summary[col] = df_summary[col].apply(
                lambda x: _fmt(x) if x is not None else "—"
            )

    st.dataframe(df_summary, use_container_width=True, hide_index=True)
