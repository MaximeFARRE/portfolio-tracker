# ui/sankey.py
import streamlit as st
import plotly.graph_objects as go

from services.sankey import build_cashflow_sankey

def afficher_sankey(conn, *, person_id: int, mois_list: list[str], titre: str = "Cashflow (Sankey)"):
    data = build_cashflow_sankey(conn, person_id=person_id, mois_list=mois_list)

    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node=dict(
                label=data["labels"],
                pad=12,
                thickness=16,
                x=data["x"],   # 👈 clé du fix
                ),

                link=dict(
                    source=data["sources"],
                    target=data["targets"],
                    value=data["values"],
                ),
            )
        ]
    )
    fig.update_layout(title=titre, height=650)

    st.plotly_chart(fig, use_container_width=True)
    st.caption(
f"Période: {mois_list[0]} → {mois_list[-1]} | "
        f"Revenus: {data['total_rev']:.2f} € — Dépenses: {data['total_dep']:.2f} €"
    )