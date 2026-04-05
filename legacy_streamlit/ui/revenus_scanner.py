import streamlit as st
import pandas as pd
from datetime import date
import matplotlib.pyplot as plt
import altair as alt
import html

from services.revenus_repository import (
    ajouter_revenu,
    revenus_du_mois,
    revenus_par_mois,
    dernier_revenu,
    supprimer_revenu_par_id,
    maj_revenu,
)

# Catégories simples (tu peux les modifier)
CATEGORIES_REVENUS = [
    "Salaire",
    "Prime",
    "Remboursement",
    "Dividendes",
    "Intérêts",
    "Autres",
]

MOIS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
]

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


def onglet_revenus(conn, person_id: int, key_prefix: str = "revenus"):
    st.subheader("Revenus")

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
            index=len(annees) - 1,
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
    mois = f"{annee:04d}-{mois_num:02d}-01"  # format stable DB

    st.caption(f"Mois sélectionné : {mois_nom} {annee}")

    st.divider()

    # ----------------------------
    # Scanner (saisie rapide)
    # ----------------------------
    st.markdown("### Saisie rapide (mode scanner)")

    categorie_active = st.selectbox(
        "Catégorie active",
        CATEGORIES_REVENUS,
        key=f"{key_prefix}_cat",
    )

    with st.form(key=f"{key_prefix}_form", clear_on_submit=True):
        montant_str = st.text_input(
            "Montant",
            placeholder="Ex : 1200, 300.5, 50",
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

            ajouter_revenu(conn, person_id, mois, categorie_active, montant)

    # Annuler dernière saisie
    col_undo1, col_undo2 = st.columns([2, 1])
    with col_undo2:
        if st.button("Annuler la dernière saisie ↩️", use_container_width=True, key=f"{key_prefix}_undo"):
            last = dernier_revenu(conn, person_id, mois)
            if last is None:
                st.warning("Rien à annuler pour ce mois.")
            else:
                revenu_id, cat, montant = last
                supprimer_revenu_par_id(conn, revenu_id)
                st.success(f"Annulé : {cat} — {montant:.2f} €")
                st.rerun()

    # ----------------------------
    # Modifier / supprimer (data_editor)
    # ----------------------------
    with st.expander("Modifier / supprimer des saisies (détail)", expanded=False):
        df_detail = revenus_du_mois(conn, person_id, mois)

        if df_detail.empty:
            st.info("Aucune ligne à modifier.")
        else:
            st.info("Tu peux modifier la catégorie ou le montant, puis cliquer sur Appliquer.")

            edited = st.data_editor(
                df_detail,
                use_container_width=True,
                num_rows="dynamic",
                key=f"{key_prefix}_editor",
            )

            if st.button("Appliquer les modifications ✅", key=f"{key_prefix}_apply"):
                edited = edited[["id", "categorie", "montant"]].copy()

                for _, row in edited.iterrows():
                    try:
                        revenu_id = int(row["id"])
                        categorie = str(row["categorie"])
                        montant = float(str(row["montant"]).replace(",", "."))
                        if montant <= 0:
                            continue
                        if categorie not in CATEGORIES_REVENUS:
                            continue
                        maj_revenu(conn, revenu_id, categorie, montant)
                    except Exception:
                        continue

                st.success("Modifications appliquées ✅")
                st.rerun()

    # ----------------------------
    # Synthèse
    # ----------------------------
    st.markdown("### Synthèse du mois")

    df = revenus_du_mois(conn, person_id, mois)

    if df.empty:
        st.info("Aucun revenu pour ce mois.")
        return

    resume = (
        df.groupby("categorie")["montant"]
        .sum()
        .reindex(CATEGORIES_REVENUS, fill_value=0.0)
        .reset_index()
    )
    resume.columns = ["Catégorie", "Total (€)"]

    total = float(resume["Total (€)"].sum())

    st.dataframe(resume, use_container_width=True)
    st.markdown(f"### Total du mois : **{total:.2f} €**")

    st.divider()
    st.subheader("Graphiques")

    # Choix période (on garde comme tu as)
    periode = st.radio(
        "Période",
        ["Total", "12 derniers mois", "Dernier mois"],
        horizontal=True,
        key=f"{key_prefix}_periode",
    )

    # ─────────────────────────────────────────────
    # Data période (courbe)
    # ─────────────────────────────────────────────
    df_mois = revenus_par_mois(conn, person_id).copy()
    if df_mois.empty:
        st.info("Pas assez de données pour afficher une courbe.")
        return

    df_mois["mois"] = pd.to_datetime(df_mois["mois"])
    df_mois = df_mois.sort_values("mois")

    if periode == "12 derniers mois":
        df_mois = df_mois.tail(12)
    elif periode == "Dernier mois":
        df_mois = df_mois.tail(1)

    # Pour Altair : mois en string "YYYY-MM"
    df_plot = df_mois.copy()
    df_plot["mois"] = df_plot["mois"].dt.strftime("%Y-%m")
    df_plot["total"] = pd.to_numeric(df_plot["total"], errors="coerce").fillna(0.0)

    total_periode = float(df_plot["total"].sum())
    moy_periode = float(df_plot["total"].mean()) if len(df_plot) > 0 else 0.0

    # ─────────────────────────────────────────────
    # Data mois sélectionné (répartition catégories)
    # ─────────────────────────────────────────────
    df_mois_detail = revenus_du_mois(conn, person_id, mois).copy()
    df_mois_detail["montant"] = pd.to_numeric(df_mois_detail["montant"], errors="coerce").fillna(0.0)

    df_cat = (
        df_mois_detail.groupby("categorie", as_index=False)["montant"]
        .sum()
        .sort_values("montant", ascending=False)
    )
    total_mois_sel = float(df_cat["montant"].sum()) if not df_cat.empty else 0.0
    nb_lignes = int(len(df_mois_detail))

    top_cat = None
    top_pct = 0.0
    if not df_cat.empty and total_mois_sel > 0:
        top_cat = str(df_cat.iloc[0]["categorie"])
        top_pct = float(df_cat.iloc[0]["montant"]) / total_mois_sel * 100.0

    # ─────────────────────────────────────────────
    # KPI V2 (même style que Dépenses)
    # ─────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns([1.6, 1, 1, 1])
    with c1:
        _kpi_card(
            f"Revenus ({periode})",
            f"{total_periode:,.2f} €".replace(",", " "),
            "total sur la période",
            "💰",
            "primary",
        )
    with c2:
        _kpi_card(
            "Moyenne",
            f"{moy_periode:,.2f} €".replace(",", " "),
            "moyenne mensuelle",
            "📊",
            "blue",
        )
    with c3:
        _kpi_card(
            "Nb lignes (mois)",
            str(nb_lignes),
            "mois sélectionné",
            "🧾",
            "green",
        )
    with c4:
        if top_cat:
            _kpi_card("Top catégorie", top_cat, f"{top_pct:.0f}% du mois", "🏷️", "purple")
        else:
            _kpi_card("Top catégorie", "—", "", "🏷️", "purple")

    st.divider()

    # ─────────────────────────────────────────────
    # Évolution mensuelle (Altair)
    # ─────────────────────────────────────────────
    st.caption("Évolution des revenus (période sélectionnée)")

    chart_mois = (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X("mois:N", title="", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("total:Q", title="€"),
            tooltip=[
                alt.Tooltip("mois:N", title="Mois"),
                alt.Tooltip("total:Q", title="Revenus", format=",.2f"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart_mois, use_container_width=True)

    st.divider()

    # ─────────────────────────────────────────────
    # Répartition du mois sélectionné (Altair)
    # ─────────────────────────────────────────────
    st.markdown("### Répartition du mois sélectionné")

    if df_cat.empty:
        st.info("Aucun revenu ce mois-ci.")
    else:
        # Top 10 pour le donut
        df_pie = df_cat.head(10).copy()
        total_cat = float(df_pie["montant"].sum())
        df_pie["pct"] = (df_pie["montant"] / total_cat * 100.0) if total_cat > 0 else 0.0

        left, right = st.columns([1.2, 1])

        with left:
            st.caption("Top catégories (part %)")
            donut = (
                alt.Chart(df_pie)
                .mark_arc(innerRadius=55)
                .encode(
                    theta=alt.Theta("montant:Q"),
                    color=alt.Color("categorie:N", legend=None),
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
            df_bar = df_cat.head(8).copy()
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
