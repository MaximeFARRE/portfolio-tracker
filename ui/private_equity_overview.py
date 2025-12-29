# ui/private_equity_overview.py
import streamlit as st
import matplotlib.pyplot as plt
import altair as alt

from services import private_equity_repository as pe_repo
from services import private_equity as pe
from services import pe_cash_repository as cash_repo

def afficher_private_equity_overview(conn, person_id: int):
    st.subheader("Private Equity")
    st.caption("Suivi simple : projets, plateforme, investi, cash-out, valorisations, sorties, durées, taux de réussite.")

    # --- Data
    projects = pe_repo.list_pe_projects(conn, person_id)
    tx = pe_repo.list_pe_transactions(conn, person_id)
    cash_tx = cash_repo.list_pe_cash_transactions(conn, person_id)

    # --- Filtres (plateforme + statut)
    colf1, colf2 = st.columns(2)
    with colf1:
        plateformes = sorted([p for p in projects["platform"].dropna().unique().tolist()]) if not projects.empty else []
        plateforme_sel = st.selectbox("Plateforme", ["Toutes"] + plateformes, index=0)
    with colf2:
        statut_sel = st.selectbox("Statut", ["Tous", "EN_COURS", "SORTI", "FAILLITE"], index=0)

    projects_f = projects.copy()
    if plateforme_sel != "Toutes":
        projects_f = projects_f[projects_f["platform"] == plateforme_sel]
    if statut_sel != "Tous":
        projects_f = projects_f[projects_f["status"] == statut_sel]

    tx_f = tx.copy()
    if not projects_f.empty:
        tx_f = tx_f[tx_f["project_id"].isin(projects_f["id"].tolist())]
    else:
        tx_f = tx_f.iloc[0:0]

    cash_by_platform = pe.compute_platform_cash(pe_tx=tx_f, cash_tx=cash_tx)
    cash_total = float(cash_by_platform["cash"].sum()) if not cash_by_platform.empty else 0.0

    # --- Positions + KPI
    positions = pe.build_pe_positions(projects_f, tx_f)
    k = pe.compute_pe_kpis(positions)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valeur actuelle", f"{k['value']:,.2f} €".replace(",", " "))
    c2.metric("Investi total", f"{k['invested']:,.2f} €".replace(",", " "))
    c3.metric("Cash-out total", f"{k['cash_out']:,.2f} €".replace(",", " "))
    pnl_txt = f"{k['pnl']:,.2f} €".replace(",", " ")
    c4.metric("PNL (global)", pnl_txt)

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Projets (total)", str(k["n_total"]))
    c6.metric("En cours", str(k["n_en_cours"]))
    c7.metric("Sortis", str(k["n_sortis"]))
    c8.metric("Faillite", str(k["n_faillite"]))

    c9, c10, c11, c12 = st.columns(4)
    c9.metric("En gain", str(k["n_en_gain"]))
    c10.metric("En perte", str(k["n_en_perte"]))
    c11.metric("MOIC global", "-" if k["moic"] is None else f"{k['moic']:.2f}x")
    c12.metric("Taux réussite", "-" if k["success_rate"] is None else f"{k['success_rate']*100:.0f}%")

    c13, c14 = st.columns(2)
    c13.metric("Durée moyenne détention", "-" if k["avg_holding_days"] is None else f"{k['avg_holding_days']:.0f} jours")
    c14.metric("Durée moyenne avant sortie", "-" if k["avg_exit_days"] is None else f"{k['avg_exit_days']:.0f} jours")

    st.divider()

    st.subheader("Liquidités")

    cash_by_platform = pe.compute_platform_cash(pe_tx=tx_f, cash_tx=cash_tx)
    cash_total = float(cash_by_platform["cash"].sum()) if not cash_by_platform.empty else 0.0

    # --- KPIs (total + plateformes)
    if cash_by_platform.empty:
        st.metric("Liquidités totales", f"{cash_total:,.2f} €".replace(",", " "))
    else:
        # On affiche Total + les 3 plus grosses plateformes
        top_n = min(3, len(cash_by_platform))
        cols = st.columns(1 + top_n)

        cols[0].metric("Liquidités totales", f"{cash_total:,.2f} €".replace(",", " "))

        for i in range(top_n):
            row = cash_by_platform.iloc[i]
            plat = str(row["platform"])
            val = float(row["cash"])
            cols[i + 1].metric(f"{plat}", f"{val:,.2f} €".replace(",", " "))
        
    
    # Optionnel : format cash + colonne lisible
    df_cash_view = cash_by_platform.copy()
    df_cash_view["cash"] = df_cash_view["cash"].map(lambda x: f"{float(x):,.2f} €".replace(",", " "))
    st.dataframe(df_cash_view, use_container_width=True, hide_index=True)


    # --- Création projet
    with st.expander("➕ Créer un projet / ligne", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Nom du projet", key="pe_proj_name")
            platform = st.text_input("Plateforme (Blast, …)", key="pe_proj_platform")
        with col2:
            project_type = st.text_input("Type (Startup, Fonds, …) (optionnel)", key="pe_proj_type")
            note = st.text_input("Note (optionnel)", key="pe_proj_note")
        if st.button("Créer le projet", use_container_width=True):
            if not name.strip():
                st.warning("Nom projet obligatoire.")
            else:
                pe_repo.create_pe_project(conn, person_id, name=name, platform=platform, project_type=project_type, note=note)
                st.success("Projet créé.")
                st.rerun()

    # --- Ajout transaction
    with st.expander("➕ Ajouter une transaction", expanded=True):
        if projects.empty:
            st.info("Crée d’abord un projet.")
        else:
            project_map = {f"{r['name']} — {r.get('platform','') or ''}": int(r["id"]) for _, r in projects.iterrows()}
            projet_label = st.selectbox("Projet", list(project_map.keys()), key="pe_tx_project")
            project_id = project_map[projet_label]

            col1, col2 = st.columns(2)
            with col1:
                date = st.date_input("Date", key="pe_tx_date")
                tx_type = st.selectbox("Type", ["INVEST", "DISTRIB", "FEES", "VALO", "VENTE"], key="pe_tx_type")
            with col2:
                amount = st.number_input("Montant (€)", min_value=0.0, step=10.0, key="pe_tx_amount")
                note_tx = st.text_input(
                    "Note (optionnel)",
                    key="pe_tx_note"
                )


            # Champs vente
            quantity = None
            unit_price = None
            mark_exited = False
            if tx_type == "VENTE":
                cA, cB, cC = st.columns(3)
                with cA:
                    quantity = st.number_input("Quantité vendue (optionnel)", min_value=0.0, step=1.0, key="pe_tx_quantity")
                with cB:
                    unit_price = st.number_input("Prix / action (optionnel)", min_value=0.0, step=0.1, key="pe_tx_unit_price")
                with cC:
                    mark_exited = st.checkbox("Marquer le projet comme SORTI", value=True, key="pe_tx_mark_exited")

            if st.button("Ajouter la transaction", use_container_width=True):
                if amount <= 0:
                    st.warning("Le montant doit être > 0.")
                else:
                    pe_repo.add_pe_transaction(
                        conn,
                        project_id=project_id,
                        date=str(date),
                        tx_type=tx_type,
                        amount=float(amount),
                        quantity=(float(quantity) if tx_type == "VENTE" and quantity and quantity > 0 else None),
                        unit_price=(float(unit_price) if tx_type == "VENTE" and unit_price and unit_price > 0 else None),
                        note=note_tx,
                    )
                    # Si vente + sortie : set status SORTI
                    if tx_type == "VENTE" and mark_exited:
                        pe_repo.set_project_status(conn, project_id, status="SORTI", exit_date=str(date))
                    st.success("Transaction ajoutée.")
                    st.rerun()

    st.divider()
    # ----------------------------
    # --- Ajout opération liquidité
    # ----------------------------
    with st.expander("➕ Ajouter une opération de liquidité (plateforme)", expanded=False):

        # 1️⃣ Récupération des plateformes déjà connues
        platforms_from_projects = []
        if not projects.empty and "platform" in projects.columns:
            platforms_from_projects = [
                p for p in projects["platform"].dropna().unique().tolist()
                if str(p).strip()
            ]

        platforms_from_cash = []
        if not cash_tx.empty and "platform" in cash_tx.columns:
            platforms_from_cash = [
                p for p in cash_tx["platform"].dropna().unique().tolist()
                if str(p).strip()
            ]

        # Liste unique + tri
        platforms = sorted(set(platforms_from_projects + platforms_from_cash))

        # Options du menu déroulant
        platform_options = platforms + ["➕ Nouvelle plateforme..."]

        col1, col2 = st.columns(2)

        # 2️⃣ Colonne gauche : plateforme + type + date
        with col1:
            selected_platform = st.selectbox(
                "Plateforme",
                platform_options,
                key="pe_cash_platform_select"
            )

            # Si l’utilisateur choisit "Nouvelle plateforme"
            if selected_platform == "➕ Nouvelle plateforme...":
                cash_platform = st.text_input(
                    "Nom de la nouvelle plateforme",
                    key="pe_cash_platform_new"
                )
            else:
                cash_platform = selected_platform

            cash_date = st.date_input("Date", key="pe_cash_date")

            cash_type = st.selectbox(
                "Type d'opération",
                ["ADJUST", "DEPOSIT", "WITHDRAW"],
                key="pe_cash_type"
            )

        # 3️⃣ Colonne droite : montant + note
        with col2:
            cash_amount = st.number_input(
                "Montant (€)",
                min_value=0.0,
                step=10.0,
                key="pe_cash_amount"
            )

            cash_note = st.text_input(
                "Note (optionnel)",
                key="pe_cash_note"
            )

        # 4️⃣ Bouton de validation
        if st.button(
            "Ajouter l'opération de liquidité",
            use_container_width=True,
            key="pe_cash_add_btn"
        ):
            if not str(cash_platform).strip():
                st.warning("Plateforme obligatoire (ex: Blast).")

            elif cash_amount <= 0:
                st.warning("Le montant doit être strictement positif.")

            else:
                cash_repo.add_pe_cash_transaction(
                    conn,
                    person_id=person_id,
                    platform=str(cash_platform).strip(),
                    date=str(cash_date),
                    tx_type=cash_type,
                    amount=float(cash_amount),
                    note=cash_note,
                )

                st.success("Opération de liquidité ajoutée.")
                st.rerun()


    #-----------------------------
    # --- Graphes ---
    #-----------------------------
    st.subheader("Graphes")



    series = pe.build_pe_monthly_series(tx_f)
    value_series = pe.build_pe_portfolio_value_series(projects_f, tx_f)

    if series.empty:
        st.info("Pas assez de données pour tracer.")
    else:
        df = series.copy().sort_values("month")

        if not value_series.empty:
            df = df.merge(value_series, on="month", how="left")
        else:
            df["portfolio_value"] = None

        # IMPORTANT : c’est ça qui fixe ton problème
        st.line_chart(df.set_index("month")[["invest_cum", "portfolio_value"]])



    st.markdown("**Répartition de la valeur par plateforme**")
    
    col_value = "value_used" if "value_used" in positions.columns else ("value" if "value" in positions.columns else None)
    by_plat = positions.groupby("platform")[col_value].sum().sort_values(ascending=False) if col_value else positions.groupby("platform").size().sort_values(ascending=False)

    if by_plat.empty:
        st.info("Aucune donnée plateforme.")
    else:
        st.bar_chart(by_plat)




    st.markdown("### Projets (positions)")
    st.dataframe(positions, use_container_width=True, hide_index=True)

    st.markdown("### Transactions")
    st.dataframe(tx_f, use_container_width=True, hide_index=True)
