import pytest

from services import family_snapshots as fs
from services.projections import ScenarioParams, load_initial_patrimoine_from_family, project_patrimoine


def _insert_person(conn, person_id: int = 1, name: str = "Test") -> None:
    conn.execute("INSERT INTO people(id, name) VALUES (?, ?)", (int(person_id), str(name)))


def test_get_family_weekly_series_prefers_family_table(conn):
    _insert_person(conn, 1, "Alice")
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (1, "2026-01-05", "2026-01-06T10:00:00+01:00", "REBUILD", 1000, 1100, 100, 200, 300, 100, 400, 100, "person"),
    )
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_family_weekly(
            family_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (1, "2026-01-05", "2026-01-06T10:00:00+01:00", "REBUILD", 2222, 2400, 120, 220, 320, 140, 500, 178, "family"),
    )
    conn.commit()

    df = fs.get_family_weekly_series(conn, family_id=1, fallback_person_ids=[1])

    assert len(df) == 1
    assert float(df.iloc[0]["patrimoine_net"]) == pytest.approx(2222.0)
    assert float(df.iloc[0]["immobilier_value"]) == pytest.approx(500.0)


def test_get_family_weekly_series_fallback_people_includes_immobilier(conn):
    _insert_person(conn, 1, "Alice")
    _insert_person(conn, 2, "Bob")
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (1, "2026-01-05", "2026-01-06T10:00:00+01:00", "REBUILD", 1000, 1200, 100, 200, 300, 100, 500, 200, "p1"),
    )
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (2, "2026-01-05", "2026-01-06T10:00:00+01:00", "REBUILD", 700, 900, 50, 150, 250, 50, 400, 200, "p2"),
    )
    conn.commit()

    df = fs.get_family_weekly_series(conn, family_id=1, fallback_person_ids=[1, 2])

    assert len(df) == 1
    assert float(df.iloc[0]["immobilier_value"]) == pytest.approx(900.0)
    assert float(df.iloc[0]["patrimoine_net"]) == pytest.approx(1700.0)


def test_project_patrimoine_includes_immobilier_in_brut_and_net():
    scenario = ScenarioParams(
        label="Test",
        taux_bourse_annuel=0.0,
        taux_pe_annuel=0.0,
        epargne_mensuelle=0.0,
        inflation_annuelle=0.0,
        remboursement_mensuel_credit=0.0,
    )

    df = project_patrimoine(
        {
            "bank": 100.0,
            "bourse": 200.0,
            "pe": 300.0,
            "ent": 400.0,
            "immobilier": 500.0,
            "credits": 250.0,
        },
        scenario=scenario,
        horizon_ans=1,
    )

    assert float(df.iloc[0]["patrimoine_brut"]) == pytest.approx(1500.0)
    assert float(df.iloc[0]["patrimoine_net"]) == pytest.approx(1250.0)
    assert float(df.iloc[0]["immobilier"]) == pytest.approx(500.0)


def test_load_initial_patrimoine_from_family_reads_immobilier(conn):
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_family_weekly(
            family_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (1, "2026-01-05", "2026-01-06T10:00:00+01:00", "REBUILD", 1000, 1400, 100, 200, 300, 400, 500, 400, "family"),
    )
    conn.commit()

    payload = load_initial_patrimoine_from_family(conn, family_id=1)
    assert payload["immobilier"] == pytest.approx(500.0)
    assert payload["credits"] == pytest.approx(400.0)
