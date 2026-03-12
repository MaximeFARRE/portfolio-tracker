import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date

from utils.cache import cached_conn
from services import repositories as repo
from utils.format_monnaie import money

# Initialise DB + seed au démarrage
cached_conn()

st.set_page_config(page_title="Patrimoine Famille", layout="wide", page_icon="🏦")


def _fmt(x) -> str:
    try:
        return money(float(x))
    except Exception:
        return "—"


def _delta_str(val: float, ref: float) -> str:
    d = val - ref
    sign = "+" if d >= 0 else ""
    return f"{sign}{_fmt(d)}"


@st.cache_data(ttl=300, show_spinner=False)
def _load_family_snapshots(_conn) -> pd.DataFrame:
    try:
        df = pd.read_sql_query(
            "SELECT week_date, patrimoine_net, patrimoine_brut, credits_remaining "
            "FROM patrimoine_snapshots_family_weekly ORDER BY week_date ASC",
            _conn,
        )
        df["week_date"] = pd.to_datetime(df["week_date"], errors="coerce")
        return df.dropna(subset=["week_date"])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _load_person_last_snapshot(_conn, person_id: int) -> dict:
    try:
        row = conn.execute(
            "SELECT patrimoine_net, patrimoine_brut, week_date "
            "FROM patrimoine_snapshots_weekly WHERE person_id=? ORDER BY week_date DESC LIMIT 1",
            (int(person_id),),
        ).fetchone()
        if row is None:
            return {}
        try:
            return {
                "patrimoine_net": float(row["patrimoine_net"] or 0),
                "patrimoine_brut": float(row["patrimoine_brut"] or 0),
                "week_date": row["week_date"],
            }
        except Exception:
            return {
                "patrimoine_net": float(row[0] or 0),
                "patrimoine_brut": float(row[1] or 0),
                "week_date": row[2],
            }
    except Exception:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def _load_person_patrimoine_history(_conn, person_id: int) -> pd.DataFrame:
    try:
        df = pd.read_sql_query(
            "SELECT week_date, patrimoine_net FROM patrimoine_snapshots_weekly "
            "WHERE person_id=? ORDER BY week_date ASC",
            _conn, params=(person_id,),
        )
        df["week_date"] = pd.to_datetime(df["week_date"], errors="coerce")
        return df.dropna(subset=["week_date"])
    except Exception:
        return pd.DataFrame()


# ─────────────────────────────────────────────
# Page header
# ─────────────────────────────────────────────
st.title("🏦 Tableau de bord famille")
st.caption(f"Mis à jour le {date.today().strftime('%d/%m/%Y')}")

conn = cached_conn()
people = repo.list_people(conn)

# ─────────────────────────────────────────────
# Données famille
# ─────────────────────────────────────────────
df_fam = _load_family_snapshots(conn)  # conn ignoré dans le cache key (préfixe _)

if df_fam.empty:
    pat_net_fam = 0.0
    pat_net_prev = 0.0
    credits_fam = 0.0
else:
    last_row = df_fam.iloc[-1]
    pat_net_fam = float(last_row.get("patrimoine_net") or 0)
    credits_fam = float(last_row.get("credits_remaining") or 0)

    # variation vs 4 semaines avant
    cutoff = last_row["week_date"] - pd.Timedelta(days=28)
    prev = df_fam[df_fam["week_date"] <= cutoff]
    pat_net_prev = float(prev.iloc[-1]["patrimoine_net"]) if not prev.empty else 0.0

delta_net = pat_net_fam - pat_net_prev

# Épargne mensuelle approx (delta / 4 semaines)
epargne_mois = delta_net  # on affiche delta brut comme proxy

# ─────────────────────────────────────────────
# KPI Famille
# ─────────────────────────────────────────────
st.markdown("### KPIs Famille")
k1, k2, k3, k4 = st.columns(4)

with k1:
    st.metric("Patrimoine net famille", _fmt(pat_net_fam),
              delta=f"{_fmt(delta_net)} (4 sem.)" if not df_fam.empty else None)
with k2:
    st.metric("Variation 4 semaines", _fmt(delta_net),
              delta=f"{(delta_net/pat_net_prev*100):+.1f}%" if pat_net_prev else None)
with k3:
    st.metric("Crédits restants", _fmt(credits_fam))
with k4:
    n_personnes = len(people) if people is not None and not people.empty else 0
    st.metric("Membres de la famille", str(n_personnes))

st.divider()

# ─────────────────────────────────────────────
# Graphique Plotly — Patrimoine net famille
# ─────────────────────────────────────────────
if not df_fam.empty and len(df_fam) >= 2:
    st.markdown("### Évolution du patrimoine famille (90 derniers jours)")
    cutoff_90 = df_fam["week_date"].max() - pd.Timedelta(days=90)
    df_plot = df_fam[df_fam["week_date"] >= cutoff_90].copy()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_plot["week_date"],
        y=df_plot["patrimoine_net"],
        mode="lines+markers",
        name="Patrimoine net",
        line=dict(color="#1E3A8A", width=2),
        hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} €<extra></extra>",
    ))
    if "patrimoine_brut" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot["week_date"],
            y=df_plot["patrimoine_brut"],
            mode="lines",
            name="Patrimoine brut",
            line=dict(color="#6B7280", width=1, dash="dot"),
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} €<extra></extra>",
        ))
    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", y=1.05),
        yaxis=dict(tickformat=",.0f"),
    )
    st.plotly_chart(fig, use_container_width=True)
elif df_fam.empty:
    st.info("Aucune snapshot famille disponible. Calcule les snapshots depuis la page Famille.")

st.divider()

# ─────────────────────────────────────────────
# Tableau par personne
# ─────────────────────────────────────────────
if people is not None and not people.empty:
    st.markdown("### État par personne")

    rows_table = []
    for _, p in people.iterrows():
        pid = int(p["id"])
        name = str(p["name"])
        snap = _load_person_last_snapshot(conn, pid)
        if snap:
            net = snap["patrimoine_net"]
            # variation : chercher snapshot 4 semaines avant (résultat mis en cache)
            try:
                df_p = _load_person_patrimoine_history(conn, pid)
                last_date = df_p["week_date"].max()
                cutoff_p = last_date - pd.Timedelta(days=28)
                prev_p = df_p[df_p["week_date"] <= cutoff_p]
                prev_net = float(prev_p.iloc[-1]["patrimoine_net"]) if not prev_p.empty else net
                delta_p = net - prev_net
            except Exception:
                delta_p = 0.0
            rows_table.append({
                "Personne": name,
                "Patrimoine net": _fmt(net),
                "Variation (4 sem.)": _delta_str(net, net - delta_p),
                "Dernière MàJ": snap.get("week_date", "—"),
            })
        else:
            rows_table.append({
                "Personne": name,
                "Patrimoine net": "—",
                "Variation (4 sem.)": "—",
                "Dernière MàJ": "—",
            })

    st.dataframe(pd.DataFrame(rows_table), use_container_width=True, hide_index=True)

st.divider()

# ─────────────────────────────────────────────
# Liens rapides
# ─────────────────────────────────────────────
st.markdown("### Navigation rapide")
c1, c2, c3 = st.columns(3)
with c1:
    st.page_link("pages/1_Famille.py", label="Vue famille", icon="👨‍👩‍👧‍👦")
with c2:
    st.page_link("pages/2_Personnes.py", label="Personnes", icon="👤")
with c3:
    st.page_link("pages/3_Import.py", label="Import données", icon="📥")
