import pandas as pd
import streamlit as st
import altair as alt
from datetime import datetime
import pytz
from services.credits import get_credit_dates

from services.credits import (
    list_credits_by_person,
    get_amortissements,
    get_crd_a_date,
    cout_reel_mois_credit_via_bankin,
)

def _now_paris_date():
    return datetime.now(pytz.timezone("Europe/Paris")).date()

def _mois_yyyy_mm_01(d):
    return f"{d.year:04d}-{d.month:02d}-01"

def afficher_credit_overview(conn, person_id: int):
    st.subheader("Crédits")

    dfc = list_credits_by_person(conn, person_id=person_id, only_active=True)
    if dfc.empty:
        st.info("Aucun crédit actif. Ajoute un sous-compte CREDIT puis configure-le dans Import → Crédit.")
        return

    today = _now_paris_date()
    mois_courant = _mois_yyyy_mm_01(today)

    # ---------- KPI GLOBAL ----------
    total_crd = 0.0
    total_capital_init = 0.0
    total_capital_rembourse = 0.0
    total_mensualite_theo = 0.0
    total_cout_reel_mois = 0.0

    # mois restants pondérés par CRD
    somme_poids = 0.0
    somme_mois_pond = 0.0

    # ---------- Pour graph + tableau ----------
    lignes_table = []
    all_series = []   # liste de df(date, credit_nom, crd)
    all_total = []    # liste de df(date, crd_total) à agréger

    for _, c in dfc.iterrows():
        credit_id = int(c["id"])
        nom = str(c.get("nom") or f"Crédit {credit_id}")
        banque = str(c.get("banque") or "")
        capital_init = float(c.get("capital_emprunte") or 0.0)

        # CRD à date
        crd_today = float(get_crd_a_date(conn, credit_id=credit_id, date_ref=str(today)))

        # Capital remboursé
        capital_rembourse = max(0.0, capital_init - crd_today)

        # Mensualité théorique totale
        mensu_theo = float(c.get("mensualite_theorique") or 0.0) + float(c.get("assurance_mensuelle_theorique") or 0.0)

        # Coût réel mois courant (Bankin) par crédit
        cout_reel = float(cout_reel_mois_credit_via_bankin(conn, credit_id=credit_id, mois_yyyy_mm_01=mois_courant))

        # Dates crédit (début remboursement + fin) -> gère le différé
        dates = get_credit_dates(conn, credit_id=credit_id)
        date_debut_remb = dates.get("date_debut_remboursement")
        date_fin = dates.get("date_fin")

        # Temps restant (mois) basé sur la date de fin
        if date_fin is not None:
            mois_restants = max(0, (date_fin.year - today.year) * 12 + (date_fin.month - today.month))
        else:
            mois_restants = None

        # Amortissement (on le garde pour le graphe global plus bas)
        amort = get_amortissements(conn, credit_id=credit_id)


        # Aggreg KPI
        total_crd += crd_today
        total_capital_init += capital_init
        total_capital_rembourse += capital_rembourse
        total_mensualite_theo += mensu_theo
        total_cout_reel_mois += cout_reel

        if mois_restants is not None:
            poids = max(crd_today, 0.0)
            somme_poids += poids
            somme_mois_pond += poids * mois_restants

        # Progress %
        prog = (capital_rembourse / capital_init) if capital_init > 0 else 0.0
        prog = max(0.0, min(1.0, prog))

        lignes_table.append({
            "Crédit": nom,
            "Banque": banque,
            "CRD actuel": crd_today,
            "Capital remboursé": capital_rembourse,
            "Mensualité théorique": mensu_theo,
            "Coût réel (mois)": cout_reel,
            "Début remboursement": date_debut_remb.isoformat() if date_debut_remb else "—",
            "Fin": date_fin.isoformat() if date_fin else "—",
            "Temps restant (mois)": mois_restants,
            "% remboursé": prog,
        })

        # Séries CRD (pour graph global)
        if not amort.empty and "crd" in amort.columns:
            s = amort[["date_echeance", "crd"]].copy()
            s["crd"] = pd.to_numeric(s["crd"], errors="coerce").fillna(0.0)
            s["Crédit"] = nom
            all_series.append(s)

            t = s.groupby("date_echeance", as_index=False)["crd"].sum()
            all_total.append(t)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("CRD total", f"{total_crd:,.2f} €".replace(",", " "))
    col2.metric("Capital remboursé", f"{total_capital_rembourse:,.2f} €".replace(",", " "))
    col3.metric("Mensualités théoriques", f"{total_mensualite_theo:,.2f} €".replace(",", " "))
    col4.metric("Coût réel (mois)", f"{total_cout_reel_mois:,.2f} €".replace(",", " "))
    col5.metric("Crédits actifs", f"{len(dfc)}")

    if somme_poids > 0:
        mois_restants_moy = int(round(somme_mois_pond / somme_poids))
        st.caption(f"Temps restant moyen (pondéré par CRD) : **{mois_restants_moy} mois**")
    else:
        st.caption("Temps restant moyen : —")

    st.divider()

    # ---------- GRAPH CRD TOTAL + point rouge aujourd’hui ----------
    st.markdown("### Évolution du capital restant dû (CRD total)")

    # construire une grille mensuelle commune
    # on récupère toutes les bornes dates via les amortissements de chaque crédit
    bornes = []
    amorts_by_credit = {}

    for _, c in dfc.iterrows():
        credit_id = int(c["id"])
        amort = get_amortissements(conn, credit_id=credit_id)
        if amort.empty:
            continue
        amort["date_echeance"] = pd.to_datetime(amort["date_echeance"], errors="coerce")
        amort = amort.dropna(subset=["date_echeance"]).sort_values("date_echeance")
        amort["crd"] = pd.to_numeric(amort["crd"], errors="coerce").fillna(0.0)
        amorts_by_credit[credit_id] = amort
        bornes.append(amort["date_echeance"].min())
        bornes.append(amort["date_echeance"].max())

    if not bornes:
        st.info("Aucun amortissement disponible pour afficher l’évolution. Génère l’amortissement dans Import → Crédit.")
    else:
        start = min(bornes).to_period("M").to_timestamp()   # début mois
        end = max(bornes).to_period("M").to_timestamp()     # début mois fin

        months = pd.date_range(start=start, end=end, freq="MS")  # Month Start (YYYY-MM-01)

        rows = []
        for m in months:
            # fin de mois : dernier jour du mois à 23:59:59
            month_end = (m + pd.offsets.MonthBegin(1)) - pd.Timedelta(seconds=1)

            total = 0.0
            for credit_id, amort in amorts_by_credit.items():
                past = amort[amort["date_echeance"] <= month_end]
                if past.empty:
                    crd_m = float(amort.iloc[0]["crd"])  # avant 1ère échéance
                else:
                    crd_m = float(past.iloc[-1]["crd"])
                total += crd_m

            rows.append({"date": m, "crd_total": total})

        df_total = pd.DataFrame(rows).sort_values("date")

        # point rouge "aujourd'hui" (CRD total actuel déjà calculé plus haut: total_crd)
        df_point = pd.DataFrame({"date": [pd.to_datetime(today)], "crd_total": [total_crd]})

        line = alt.Chart(df_total).mark_line().encode(
            x=alt.X("date:T", title="Mois"),
            y=alt.Y("crd_total:Q", title="CRD total"),
        )

        point = alt.Chart(df_point).mark_point(size=80, color="red").encode(
            x="date:T",
            y="crd_total:Q",
        )

        st.altair_chart((line + point).properties(height=260), use_container_width=True)


    # ---------- TABLEAU SYNTHÈSE ----------
    st.markdown("### Synthèse des crédits")
    df_view = pd.DataFrame(lignes_table)

    # affichage + format
    st.dataframe(
        df_view.assign(**{
            "CRD actuel": df_view["CRD actuel"].map(lambda x: f"{x:,.2f} €".replace(",", " ")),
            "Capital remboursé": df_view["Capital remboursé"].map(lambda x: f"{x:,.2f} €".replace(",", " ")),
            "Mensualité théorique": df_view["Mensualité théorique"].map(lambda x: f"{x:,.2f} €".replace(",", " ")),
            "Coût réel (mois)": df_view["Coût réel (mois)"].map(lambda x: f"{x:,.2f} €".replace(",", " ")),
            "% remboursé": df_view["% remboursé"].map(lambda x: f"{x*100:.1f}%"),
        }),
        use_container_width=True
    )

    st.caption("Astuce : le coût réel du mois vient de Bankin (transactions) et dépend du compte payeur associé au crédit.")
