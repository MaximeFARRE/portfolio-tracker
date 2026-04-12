import pandas as pd
import pytest
import sqlite3
from utils.validators import sens_flux, sens_flux_safe


# ─── sens_flux (utilisé dans snapshots et calculations) ──

def test_sens_flux_depot():
    assert sens_flux("DEPOT") == 1


def test_sens_flux_depense():
    assert sens_flux("DEPENSE") == -1


def test_sens_flux_achat():
    assert sens_flux("ACHAT") == -1


def test_sens_flux_vente():
    assert sens_flux("VENTE") == 1


def test_sens_flux_dividende():
    assert sens_flux("DIVIDENDE") == 1


def test_sens_flux_frais():
    assert sens_flux("FRAIS") == -1


def test_sens_flux_inconnu_leve_value_error():
    with pytest.raises(ValueError, match="type_operation inconnu"):
        sens_flux("INCONNU")


def test_sens_flux_safe_inconnu_retourne_zero():
    assert sens_flux_safe("INCONNU") == 0


# ─── Test simple de cohérence de solde via calculations ──

def test_solde_avec_ventes_et_achats():
    """Vérifie que ACHAT diminue et VENTE augmente le solde."""
    from services.calculations import solde_compte
    tx = pd.DataFrame([
        {"date": "2025-01-01", "type": "DEPOT", "amount": 1000.0},
        {"date": "2025-01-10", "type": "ACHAT", "amount": 600.0},
        {"date": "2025-01-20", "type": "VENTE", "amount": 700.0},
    ])
    # 1000 - 600 + 700 = 1100
    assert solde_compte(tx) == pytest.approx(1100.0)


def test_solde_negatif():
    from services.calculations import solde_compte
    tx = pd.DataFrame([
        {"date": "2025-01-01", "type": "DEPOT", "amount": 100.0},
        {"date": "2025-01-05", "type": "DEPENSE", "amount": 200.0},
    ])
    # 100 - 200 = -100
    assert solde_compte(tx) == pytest.approx(-100.0)


def _mk_conn_for_watermark_tests():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            person_id INTEGER NOT NULL,
            created_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def test_has_new_transactions_since_person_watermark_false_when_no_tx():
    from services.snapshots_rebuild import has_new_transactions_since_person_watermark
    conn = _mk_conn_for_watermark_tests()
    assert has_new_transactions_since_person_watermark(conn, 1) is False


def test_has_new_transactions_since_person_watermark_true_without_watermark():
    from services.snapshots_rebuild import has_new_transactions_since_person_watermark
    conn = _mk_conn_for_watermark_tests()
    conn.execute("INSERT INTO transactions(id, person_id, created_at) VALUES (1, 1, '2026-01-01T10:00:00+01:00')")
    conn.commit()
    assert has_new_transactions_since_person_watermark(conn, 1) is True


def test_has_new_transactions_since_person_watermark_with_existing_watermark():
    from services.snapshots_rebuild import (
        has_new_transactions_since_person_watermark,
        _set_person_watermark,
    )
    conn = _mk_conn_for_watermark_tests()
    conn.execute("INSERT INTO transactions(id, person_id, created_at) VALUES (10, 1, '2026-01-01T10:00:00+01:00')")
    conn.commit()
    _set_person_watermark(conn, 1, 10, "2026-01-01T10:00:00+01:00")
    assert has_new_transactions_since_person_watermark(conn, 1) is False

    conn.execute("INSERT INTO transactions(id, person_id, created_at) VALUES (11, 1, '2026-01-02T10:00:00+01:00')")
    conn.commit()
    assert has_new_transactions_since_person_watermark(conn, 1) is True
