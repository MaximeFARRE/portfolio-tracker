import math
from pathlib import Path

import pytest

from services.cashflow import compute_savings_metrics, get_person_monthly_savings_series
from services.vue_ensemble_metrics import get_vue_ensemble_metrics


def _insert_snapshot(
    conn,
    person_id: int,
    week_date: str,
    net: float,
    brut: float = 1500.0,
    liq: float = 2400.0,
    bourse: float = 400.0,
    credits: float = 200.0,
    pe: float = 50.0,
    ent: float = 100.0,
    immo: float = 300.0,
):
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, credits_remaining, pe_value, ent_value, immobilier_value
        ) VALUES (?, ?, datetime('now'), 'REBUILD', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (person_id, week_date, net, brut, liq, bourse, credits, pe, ent, immo),
    )


def test_compute_taux_epargne_mensuel_keeps_calendar_month_gaps(conn_with_person):
    conn = conn_with_person
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2025-03-01', 'Salaire', 1000)"
    )
    conn.commit()

    df = get_person_monthly_savings_series(conn, 1, n_mois=3, end_month="2025-03-01")
    assert list(df["mois"]) == ["2025-01-01", "2025-02-01", "2025-03-01"]
    assert list(df["revenus"]) == [0.0, 0.0, 1000.0]
    assert list(df["depenses"]) == [0.0, 0.0, 0.0]
    assert df.iloc[2]["taux_epargne"] == pytest.approx(100.0)


def test_vue_ensemble_metrics_are_anchored_on_last_snapshot_date(conn_with_person):
    conn = conn_with_person

    # Snapshot ancien volontairement (pas ancré sur "today").
    _insert_snapshot(conn, 1, "2024-03-04", net=700.0)
    _insert_snapshot(conn, 1, "2024-06-03", net=1000.0)
    conn.commit()

    m = get_vue_ensemble_metrics(conn, 1)
    assert m["asof_date"] == "2024-06-03"
    assert m["net_13w"] == pytest.approx(700.0)
    assert m["gain_3m"] == pytest.approx(300.0)
    assert m["perf_3m_pct"] == pytest.approx((300.0 / 700.0) * 100.0)


def test_vue_ensemble_metrics_nominal_kpis(conn_with_person):
    conn = conn_with_person

    _insert_snapshot(conn, 1, "2024-01-01", net=400.0)
    _insert_snapshot(conn, 1, "2025-01-06", net=500.0)
    _insert_snapshot(conn, 1, "2025-10-06", net=800.0)
    _insert_snapshot(conn, 1, "2026-01-05", net=1000.0)

    for mois, rev, dep in [
        ("2025-02-01", 1000.0, 700.0),
        ("2025-04-01", 1200.0, 900.0),
        ("2025-12-01", 1100.0, 600.0),
        ("2026-01-01", 900.0, 400.0),
    ]:
        conn.execute(
            "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, ?, 'Salaire', ?)",
            (mois, rev),
        )
        conn.execute(
            "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, ?, 'Vie', ?)",
            (mois, dep),
        )

    conn.commit()
    m = get_vue_ensemble_metrics(conn, 1)

    assert m["asof_date"] == "2026-01-05"
    assert m["gain_3m"] == pytest.approx(200.0)
    assert m["gain_12m"] == pytest.approx(500.0)
    assert m["perf_3m_pct"] == pytest.approx(25.0)
    assert m["perf_12m_pct"] == pytest.approx(100.0)

    assert m["epargne_12m"] == pytest.approx(1600.0)
    assert m["capacite_epargne_avg"] == pytest.approx(1600.0 / 12.0)
    assert m["depenses_moy_12m"] == pytest.approx((700.0 + 900.0 + 600.0 + 400.0) / 12.0)
    assert m["taux_epargne_avg"] == pytest.approx((1600.0 / 4200.0) * 100.0)
    assert m["reserve_securite"] == pytest.approx(2400.0 / ((700.0 + 900.0 + 600.0 + 400.0) / 12.0))
    assert m["effet_valorisation_12m"] == pytest.approx(-1100.0)

    assert m["actifs_illiquides"] == pytest.approx((100.0 + 50.0 + 300.0) / 1500.0 * 100.0)
    assert m["cagr_pct"] is not None
    assert math.isfinite(m["cagr_pct"])


def test_vue_ensemble_metrics_kpis_include_missing_months_as_zero(conn_with_person):
    conn = conn_with_person

    _insert_snapshot(conn, 1, "2026-01-05", net=1000.0)

    for mois, rev, dep in [
        ("2025-03-01", 1000.0, 800.0),  # +200
        ("2025-12-01", 1200.0, 1000.0),  # +200
    ]:
        conn.execute(
            "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, ?, 'Salaire', ?)",
            (mois, rev),
        )
        conn.execute(
            "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, ?, 'Vie', ?)",
            (mois, dep),
        )

    conn.commit()
    m = get_vue_ensemble_metrics(conn, 1)

    # Fenêtre KPI = 12 mois calendaires (2025-02 à 2026-01), dont 10 mois à 0.
    assert m["epargne_12m"] == pytest.approx(400.0)
    assert m["capacite_epargne_avg"] == pytest.approx(400.0 / 12.0)
    assert m["depenses_moy_12m"] == pytest.approx((800.0 + 1000.0) / 12.0)
    assert m["taux_epargne_avg"] == pytest.approx((400.0 / 2200.0) * 100.0)


def test_vue_ensemble_panel_subtitle_matches_formula():
    panel_path = Path(__file__).parent.parent / "qt_ui" / "panels" / "vue_ensemble_panel.py"
    text = panel_path.read_text(encoding="utf-8")
    assert "(Entreprises + PE + Immobilier) / Patrimoine brut" in text


def test_compute_savings_metrics_uses_data_months_for_avg_and_recent_streak(conn_with_person):
    conn = conn_with_person
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2025-01-01', 'Salaire', 1000)"
    )
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2025-01-01', 'Vie', 800)"
    )
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2025-03-01', 'Salaire', 1000)"
    )
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2025-03-01', 'Vie', 1200)"
    )
    conn.commit()

    out = compute_savings_metrics(conn, person_id=1, n_mois=3)

    assert out["avg_monthly_income"] == pytest.approx(1000.0)
    assert out["avg_monthly_expenses"] == pytest.approx(1000.0)
    assert out["avg_monthly_savings"] == pytest.approx(0.0)
    assert out["savings_rate_12m"] == pytest.approx(0.0)
    assert out["positive_savings_streak"] == 0


def test_vue_ensemble_metrics_include_passive_income_in_revenus(conn_with_person):
    conn = conn_with_person

    _insert_snapshot(conn, 1, "2026-01-05", net=1000.0)
    conn.execute(
        "INSERT INTO accounts(id, person_id, name, account_type, currency) VALUES (2, 1, 'CTO', 'CTO', 'EUR')"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-12-10', 1, 2, 'DIVIDENDE', 120, 0)"
    )
    conn.commit()

    m = get_vue_ensemble_metrics(conn, 1)
    assert m["epargne_12m"] == pytest.approx(120.0)
    assert m["capacite_epargne_avg"] == pytest.approx(10.0)
    assert m["taux_epargne_avg"] == pytest.approx(100.0)

