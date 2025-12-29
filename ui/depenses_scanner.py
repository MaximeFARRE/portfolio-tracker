import streamlit as st
import pandas as pd
from datetime import date
import matplotlib.pyplot as plt
import html
import numpy as np
import altair as alt

from services.depenses_repository import (
    ajouter_depense,
    depenses_du_mois,
    depenses_par_mois,
    derniere_depense,
    supprimer_depense_par_id,
    maj_depense,
)


# Catégories simples (comme ton Google Sheet)
CATEGORIES_DEPENSES = [
    "Loyer",
    "Remboursement crédit",
    "Nourriture",
    "Éducation",
    "Transports",
    "Autres",
]

MOIS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
]


def onglet_depenses(conn, person_id: int, key_prefix: str = "depenses"):
    st.subheader("Dépenses")

    # ----------------------------
    # Sélection mois (Année + Mois)
    # ----------------------------
    today = date.today()

    col_a, col_m = st.columns(2)

    with col_a:
        annees = list(range(today.year - 5, today.year + 1))
        annee = st.selectbox(
            "Année",
            options=annees,
            index=len(annees) - 1,  # année actuelle
            key=f"{key_prefix}_annee",
        )

    with col_m:
        mois_nom = st.selectbox(
            "Mois",
            options=MOIS_FR,
            index=today.month - 1,
            key=f"{key_prefix}_mois",
        )

    mois_num = MOIS_FR.index(mois_nom) + 1
    mois = f"{annee:04d}-{mois_num:02d}-01"  # format stable pour la DB

    st.caption(f"Mois sélectionné : {mois_nom} {annee}")

    st.divider()

    # ----------------------------
    # Scanner (avec callback => pas d'erreur session_state)
    # ----------------------------
    st.markdown("### Saisie rapide (mode scanner)")

    categorie_active = st.selectbox(
        "Catégorie active",
        CATEGORIES_DEPENSES,
        key=f"{key_prefix}_cat",
    )

    with st.form(key=f"{key_prefix}_form", clear_on_submit=True):
        montant_str = st.text_input(
            "Montant",
            placeholder="Ex : 4, 12.5, 23",
            key=f"{key_prefix}_montant_txt",
        )

        ajouter = st.form_submit_button("Ajouter ➕")

        if ajouter:
            try:
                montant = float(montant_str.replace(",", "."))
            except ValueError:
                st.error("Montant invalide")
                st.stop()

            if montant <= 0:
                st.error("Montant invalide")
                st.stop()

            ajouter_depense(
                conn,
                person_id,
                mois,
                categorie_active,
                montant,
            )

    # Bouton Annuler la dernière saisie
    col_undo1, col_undo2 = st.columns([2, 1])
    with col_undo2:
        if st.button("Annuler la dernière saisie ↩️", use_container_width=True, key=f"{key_prefix}_undo"):
            last = derniere_depense(conn, person_id, mois)
            if last is None:
                st.warning("Rien à annuler pour ce mois.")
            else:
                depense_id, cat, montant = last
                supprimer_depense_par_id(conn, depense_id)
                st.success(f"Annulé : {cat} — {montant:.2f} €")
                st.rerun()

    # ----------------------------
    # Synthèse (catégorie -> somme)
    # ----------------------------
    with st.expander("Modifier / supprimer des saisies (détail)", expanded=False):
        df_detail = depenses_du_mois(conn, person_id, mois)

        if df_detail.empty:
            st.info("Aucune ligne à modifier.")
        else:
            # On récupère aussi l'id pour pouvoir mettre à jour/supprimer proprement
            # ⚠️ Il faut que depenses_du_mois retourne aussi id, categorie, montant
            st.info("Tu peux modifier la catégorie ou le montant, puis cliquer sur Appliquer.")

            edited = st.data_editor(
                df_detail,
                use_container_width=True,
                num_rows="dynamic",
                key=f"{key_prefix}_editor",
            )

            if st.button("Appliquer les modifications ✅", key=f"{key_prefix}_apply"):
                # On va réécrire proprement en base (update + delete)
                # => je te donne juste après les fonctions nécessaires

                # sécurité : on garde uniquement ces colonnes
                edited = edited[["id", "categorie", "montant"]].copy()

                # on applique update ligne par ligne
                for _, row in edited.iterrows():
                    try:
                        depense_id = int(row["id"])
                        categorie = str(row["categorie"])
                        montant = float(str(row["montant"]).replace(",", "."))
                        if montant <= 0:
                            continue
                        if categorie not in CATEGORIES_DEPENSES:
                            continue
                        maj_depense(conn, depense_id, categorie, montant)
                    except Exception:
                        continue

                st.success("Modifications appliquées ✅")
                st.rerun()




    st.markdown("### Synthèse du mois")

    df = depenses_du_mois(conn, person_id, mois)

    if df.empty:
        st.info("Aucune dépense pour ce mois.")
        return

    resume = (
        df.groupby("categorie")["montant"]
        .sum()
        .reindex(CATEGORIES_DEPENSES, fill_value=0.0)
        .reset_index()
    )
    resume.columns = ["Catégorie", "Total (€)"]

    total = float(resume["Total (€)"].sum())

    st.dataframe(resume, use_container_width=True)
    st.markdown(f"### Total du mois : **{total:.2f} €**")

    st.divider()
    st.subheader("Graphiques")

    # --- Data du mois sélectionné
    df_detail = depenses_du_mois(conn, person_id, mois)
    df_detail["montant"] = pd.to_numeric(df_detail["montant"], errors="coerce").fillna(0.0)

    total_mois = float(df_detail["montant"].sum())
    nb_lignes = int(len(df_detail))

    # --- Répartition catégories (mois)
    df_cat = (
        df_detail.groupby("categorie", as_index=False)["montant"]
        .sum()
        .sort_values("montant", ascending=False)
    )

    top_cat = None
    top_cat_pct = 0.0
    if not df_cat.empty and total_mois > 0:
        top_cat = str(df_cat.iloc[0]["categorie"])
        top_cat_pct = float(df_cat.iloc[0]["montant"]) / total_mois * 100.0

    # --- Moyenne mensuelle (sur 12 derniers mois) : on calcule sur depenses_par_mois()
    df_mois_all = depenses_par_mois(conn, person_id)
    df_mois_all["total"] = pd.to_numeric(df_mois_all["total"], errors="coerce").fillna(0.0)
    df_last12 = df_mois_all.tail(12).copy()
    moy_12 = float(df_last12["total"].mean()) if not df_last12.empty else 0.0

    # ─────────────────────────────────────────────
    # KPI V2
    # ─────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns([1.6, 1, 1, 1])
    with c1:
        _kpi_card("Dépenses (mois sélectionné)", f"{total_mois:,.2f} €".replace(",", " "), f"{mois}", "💸", "primary")
    with c2:
        _kpi_card("Moyenne (12 mois)", f"{moy_12:,.2f} €".replace(",", " "), "moyenne mensuelle", "📊", "blue")
    with c3:
        _kpi_card("Nb de lignes", str(nb_lignes), "transactions du mois", "🧾", "green")
    with c4:
        if top_cat:
            _kpi_card("Top catégorie", top_cat, f"{top_cat_pct:.0f}% du mois", "🏷️", "purple")
        else:
            _kpi_card("Top catégorie", "—", "", "🏷️", "purple")

    st.divider()

    # ─────────────────────────────────────────────
    # Évolution mensuelle (12 derniers mois)
    # ─────────────────────────────────────────────
    st.caption("Évolution des dépenses (12 derniers mois)")

    df_plot = df_last12.copy()
    df_plot["mois"] = df_plot["mois"].astype(str)
    df_plot["total"] = pd.to_numeric(df_plot["total"], errors="coerce").fillna(0.0)

    chart_mois = (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X("mois:N", title="", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("total:Q", title="€"),
            tooltip=[
                alt.Tooltip("mois:N", title="Mois"),
                alt.Tooltip("total:Q", title="Dépenses", format=",.2f"),
            ],
        )
        .properties(height=260)
    )

    st.altair_chart(chart_mois, use_container_width=True)

    st.divider()

    # ─────────────────────────────────────────────
    # Répartition par catégories
    # ─────────────────────────────────────────────
    st.caption("Répartition par catégories (mois sélectionné)")

    left, right = st.columns([1.2, 1])

    # Préparation des données
    df_pie = df_cat.copy()
    df_pie["montant"] = pd.to_numeric(df_pie["montant"], errors="coerce").fillna(0.0)
    df_pie = df_pie.sort_values("montant", ascending=False).head(10)

    total_cat = float(df_pie["montant"].sum())
    df_pie["pct"] = (df_pie["montant"] / total_cat * 100.0) if total_cat > 0 else 0.0

    with left:
        st.caption("Top catégories (part %)")
        donut = (
            alt.Chart(df_pie)
            .mark_arc(innerRadius=55)
            .encode(
                theta=alt.Theta("montant:Q"),
                color=alt.Color("categorie:N", legend=None),  # couleurs différentes auto
                tooltip=[
                    alt.Tooltip("categorie:N", title="Catégorie"),
                    alt.Tooltip("montant:Q", title="Montant", format=",.2f"),
                    alt.Tooltip("pct:Q", title="Part", format=".1f"),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(donut, use_container_width=True)

    with right:
        st.caption("Top 8 catégories (€)")
        df_bar = df_cat.copy()
        df_bar["montant"] = pd.to_numeric(df_bar["montant"], errors="coerce").fillna(0.0)
        df_bar = df_bar.sort_values("montant", ascending=False).head(8)

        bar = (
            alt.Chart(df_bar)
            .mark_bar()
            .encode(
                x=alt.X("montant:Q", title="€"),
                y=alt.Y("categorie:N", sort="-x", title=""),
                color=alt.Color("categorie:N", legend=None),
                tooltip=[
                    alt.Tooltip("categorie:N", title="Catégorie"),
                    alt.Tooltip("montant:Q", title="Montant", format=",.2f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(bar, use_container_width=True)

    # Détails cachés
    with st.expander("Voir le détail des catégories", expanded=False):
        st.dataframe(df_cat, use_container_width=True, hide_index=True)

                

def _camembert(df_repartition: pd.DataFrame):

    fig, ax = plt.subplots()
    ax.pie(
        df_repartition["Montant"],
        labels=df_repartition["Catégorie"],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax.axis("equal")
    return fig

import html
import numpy as np

def _kpi_card(title: str, value: str, subtitle: str = "", emoji: str = "", tone: str = "neutral"):
    tones = {
        "primary": ("#111827", "#E5E7EB"),
        "blue": ("#1E3A8A", "#DBEAFE"),
        "green": ("#0B3B2E", "#D1FAE5"),
        "purple": ("#4C1D95", "#EDE9FE"),
        "neutral": ("#111827", "#F3F4F6"),
    }
    bg, fg = tones.get(tone, tones["neutral"])

    title = html.escape(str(title))
    value = html.escape(str(value))
    subtitle = html.escape(str(subtitle))
    emoji = html.escape(str(emoji))

    st.markdown(
        f"""
        <div style="
            background:{bg};
            color:{fg};
            border-radius:16px;
            padding:14px 16px;
            box-shadow:0 6px 18px rgba(0,0,0,0.08);
            min-height:96px;
        ">
            <div style="font-size:14px; opacity:0.9; font-weight:600;">
                {emoji} {title}
            </div>
            <div style="font-size:26px; font-weight:800; margin-top:6px;">
                {value}
            </div>
            <div style="font-size:13px; opacity:0.85; margin-top:4px;">
                {subtitle if subtitle else "&nbsp;"}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def _pie_categories(df_cat: pd.DataFrame, title: str = ""):
    """df_cat: colonnes ['categorie','montant'] triées desc."""
    fig, ax = plt.subplots()
    if df_cat is None or df_cat.empty:
        ax.text(0.5, 0.5, "Aucune donnée", ha="center", va="center")
        ax.axis("off")
        return fig

    labels = df_cat["categorie"].astype(str).tolist()
    values = df_cat["montant"].astype(float).tolist()

    # Couleurs auto (différentes)
    colors = plt.cm.tab20(np.linspace(0, 1, len(values)))

    ax.pie(
        values,
        labels=None,              # on évite le bazar des labels dans le pie
        autopct="%1.0f%%",
        startangle=90,
        colors=colors,
        pctdistance=0.75
    )
    # Donut
    centre = plt.Circle((0, 0), 0.50, fc="white")
    ax.add_artist(centre)
    ax.axis("equal")

    if title:
        ax.set_title(title)

    # Légende à droite (plus clean)
    ax.legend(labels, loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
    return fig


def _barh_top_categories(df_cat: pd.DataFrame, title: str = ""):
    fig, ax = plt.subplots()
    if df_cat is None or df_cat.empty:
        ax.text(0.5, 0.5, "Aucune donnée", ha="center", va="center")
        ax.axis("off")
        return fig

    df = df_cat.copy()
    df = df.sort_values("montant", ascending=True)  # barh: ascending pour joli
    ax.barh(df["categorie"].astype(str), df["montant"].astype(float))
    ax.set_xlabel("€")
    ax.set_ylabel("")
    if title:
        ax.set_title(title)
    return fig


def _bar_mensuel(df_mois: pd.DataFrame, title: str = ""):
    """df_mois: colonnes ['mois','total'] (mois au format YYYY-MM)."""
    fig, ax = plt.subplots()
    if df_mois is None or df_mois.empty:
        ax.text(0.5, 0.5, "Aucune donnée", ha="center", va="center")
        ax.axis("off")
        return fig

    df = df_mois.copy()
    df["mois"] = df["mois"].astype(str)
    df["total"] = pd.to_numeric(df["total"], errors="coerce").fillna(0.0)

    ax.bar(df["mois"], df["total"])
    ax.set_ylabel("€")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=45)
    if title:
        ax.set_title(title)
    return fig
