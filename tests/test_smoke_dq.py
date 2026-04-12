import pytest
import pandas as pd
from services.projections import run_projection, ScenarioParams
from services.portfolio import compute_positions_v1

def test_dq09_projection_missing_cashflow_graceful_degradation():
    """
    Vérifie qu'une projection sans données de cashflow n'invente pas un objectif FIRE atteint à 100%.
    """
    base = {
        "net_worth": 100000.0,
        "liquidities": 20000.0,
        "bourse": 80000.0,
        "immobilier": 0.0,
        "private_equity": 0.0,
        "entreprises": 0.0,
        "credits": 0.0,
        "avg_monthly_income": 0.0,
        "avg_monthly_expenses": 0.0,
        "has_cashflow": False,
    }
    params = ScenarioParams(
        horizon_years=1,
        return_liquidites_pct=1.0,
        return_bourse_pct=5.0,
        return_immobilier_pct=0.0,
        return_pe_pct=0.0,
        return_entreprises_pct=0.0,
        inflation_pct=0.0,
        monthly_savings_override=0.0,
    )
    df = run_projection(base, params)
    last_row = df.iloc[-1]
    assert pd.isna(last_row["fire_target"]) or last_row["fire_target"] is None


def test_dq03_bourse_missing_price_graceful_handling():
    """
    Vérifie qu'un actif sans prix connu retourne 'missing_price' et ne plante pas.
    compute_positions_v1 travaille sur asset_id (entier) — pas symbol.
    """
    tx_df = pd.DataFrame([
        {
            "id": 1,
            "account_id": 1,
            "person_id": 1,
            "asset_id": 42,
            "asset_symbol": "AAPL",
            "asset_name": "Apple Inc.",
            "type": "ACHAT",
            "date": "2023-01-01",
            "quantity": 10.0,
            "price": 150.0,
            "amount": 1500.0,
        }
    ])
    # Prix absents → latest_prices vide de l'actif
    latest_prices = pd.DataFrame(columns=["asset_id", "price"])

    positions_df = compute_positions_v1(tx_df, latest_prices)
    assert not positions_df.empty
    assert positions_df.iloc[0]["valuation_status"] == "missing_price"


def test_dq01_liquidites_missing_fx_graceful_handling(conn_with_person):
    """
    Vérifie que les liquidités en devise étrangère manquante sont filtrées/ignorées sans crash.
    """
    from services.liquidites import get_liquidites_summary
    
    conn_with_person.execute(
        "INSERT INTO accounts (person_id, name, account_type, currency) VALUES (1, 'Banque USD', 'BANQUE', 'USD')"
    )
    conn_with_person.execute(
        "INSERT INTO transactions (account_id, person_id, type, date, amount) VALUES (2, 1, 'DEPOT', '2023-01-01', 1000.0)"
    )
    conn_with_person.commit()
    
    summary = get_liquidites_summary(conn_with_person, person_id=1)
    assert isinstance(summary, dict)
    assert "total_eur" in summary or "total" in summary
    assert "missing_fx" in summary
