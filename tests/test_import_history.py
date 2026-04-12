"""
Tests de rollback des batches d'import.
Couvre : TR/BANKIN, DEPENSES, REVENUS, CREDIT, déjà annulé, introuvable.
"""
import pytest
from services.import_history import create_batch, close_batch, rollback_batch, _count_alive_rows
from services.import_history import list_batches


# ─── helpers ────────────────────────────────────────────────────────────────

def _insert_person(conn, name: str = "Alice") -> int:
    conn.execute("INSERT INTO people(name) VALUES (?)", (name,))
    conn.commit()
    row = conn.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
    return int(row[0])


def _insert_account(conn, person_id: int, name: str = "Compte", account_type: str = "BANQUE") -> int:
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (?, ?, ?, 'EUR')",
        (person_id, name, account_type),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM accounts WHERE person_id = ? AND name = ?", (person_id, name)
    ).fetchone()
    return int(row[0])


# ─── TR / BANKIN ─────────────────────────────────────────────────────────────

def test_rollback_batch_tr_supprime_transactions(conn):
    person_id = _insert_person(conn)
    account_id = _insert_account(conn, person_id)

    batch_id = create_batch(conn, "TR", person_id=person_id, person_name="Alice")

    # Insérer 2 transactions liées au batch
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, category, import_batch_id) "
        "VALUES ('2026-01-15', ?, ?, 'DEPENSE', 100, 'Courses', ?)",
        (person_id, account_id, batch_id),
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, category, import_batch_id) "
        "VALUES ('2026-01-20', ?, ?, 'DEPOT', 2000, 'Salaire', ?)",
        (person_id, account_id, batch_id),
    )
    conn.commit()
    close_batch(conn, batch_id, 2)

    result = rollback_batch(conn, batch_id)

    assert result["deleted"]["transactions"] == 2
    assert result["total_deleted"] == 2

    # Vérifier que les transactions ont disparu
    count = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE import_batch_id = ?", (batch_id,)
    ).fetchone()[0]
    assert count == 0

    # Vérifier que le batch est ROLLED_BACK
    status = conn.execute(
        "SELECT status FROM import_batches WHERE id = ?", (batch_id,)
    ).fetchone()[0]
    assert status == "ROLLED_BACK"


# ─── DEPENSES ────────────────────────────────────────────────────────────────

def test_rollback_batch_depenses_supprime_depenses(conn):
    person_id = _insert_person(conn)
    batch_id = create_batch(conn, "DEPENSES", person_id=person_id, person_name="Alice")

    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant, import_batch_id) "
        "VALUES (?, '2026-01-01', 'Courses', 500, ?)",
        (person_id, batch_id),
    )
    conn.commit()
    close_batch(conn, batch_id, 1)

    result = rollback_batch(conn, batch_id)

    assert result["deleted"]["depenses"] == 1
    count = conn.execute(
        "SELECT COUNT(*) FROM depenses WHERE import_batch_id = ?", (batch_id,)
    ).fetchone()[0]
    assert count == 0

    status = conn.execute(
        "SELECT status FROM import_batches WHERE id = ?", (batch_id,)
    ).fetchone()[0]
    assert status == "ROLLED_BACK"


# ─── REVENUS ─────────────────────────────────────────────────────────────────

def test_rollback_batch_revenus_supprime_revenus(conn):
    person_id = _insert_person(conn)
    batch_id = create_batch(conn, "REVENUS", person_id=person_id, person_name="Alice")

    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant, import_batch_id) "
        "VALUES (?, '2026-02-01', 'Salaire', 3000, ?)",
        (person_id, batch_id),
    )
    conn.commit()
    close_batch(conn, batch_id, 1)

    result = rollback_batch(conn, batch_id)

    assert result["deleted"]["revenus"] == 1
    count = conn.execute(
        "SELECT COUNT(*) FROM revenus WHERE import_batch_id = ?", (batch_id,)
    ).fetchone()[0]
    assert count == 0

    status = conn.execute(
        "SELECT status FROM import_batches WHERE id = ?", (batch_id,)
    ).fetchone()[0]
    assert status == "ROLLED_BACK"


# ─── CREDIT ──────────────────────────────────────────────────────────────────

def test_rollback_batch_credit_leve_value_error(conn):
    """Le rollback d'un crédit doit lever ValueError et laisser le batch ACTIVE."""
    person_id = _insert_person(conn)
    account_id = _insert_account(conn, person_id, "Crédit immo", "CREDIT")
    batch_id = create_batch(conn, "CREDIT", person_id=person_id, account_id=account_id)
    close_batch(conn, batch_id, 1)

    with pytest.raises(ValueError, match="[Cc]rédit"):
        rollback_batch(conn, batch_id)

    # Le statut doit rester ACTIVE (non modifié)
    status = conn.execute(
        "SELECT status FROM import_batches WHERE id = ?", (batch_id,)
    ).fetchone()[0]
    assert status == "ACTIVE"


# ─── Déjà annulé ─────────────────────────────────────────────────────────────

def test_rollback_batch_deja_annule_leve_erreur(conn):
    person_id = _insert_person(conn)
    batch_id = create_batch(conn, "TR", person_id=person_id, person_name="Alice")
    close_batch(conn, batch_id, 0)

    rollback_batch(conn, batch_id)  # premier rollback OK

    with pytest.raises(ValueError, match="déjà"):
        rollback_batch(conn, batch_id)  # second rollback doit échouer


# ─── Introuvable ─────────────────────────────────────────────────────────────

def test_rollback_batch_inexistant_leve_erreur(conn):
    with pytest.raises(ValueError, match="introuvable"):
        rollback_batch(conn, 99999)


# ─── _count_alive_rows CREDIT ────────────────────────────────────────────────

def test_count_alive_rows_credit_utilise_table_credits(conn):
    person_id = _insert_person(conn)
    account_id = _insert_account(conn, person_id, "Crédit immo", "CREDIT")

    batch_id = create_batch(conn, "CREDIT", person_id=person_id, account_id=account_id)
    close_batch(conn, batch_id, 1)

    # Avant insertion dans credits
    assert _count_alive_rows(conn, batch_id, "CREDIT") == 0

    # Insérer une fiche crédit liée au compte
    conn.execute(
        "INSERT INTO credits(person_id, account_id, nom, capital_emprunte, taux_nominal, duree_mois, date_debut, actif) "
        "VALUES (?, ?, 'Test', 200000, 1.5, 240, '2024-01-01', 1)",
        (person_id, account_id),
    )
    conn.commit()

    assert _count_alive_rows(conn, batch_id, "CREDIT") == 1


def test_list_batches_alive_rows_are_computed_for_each_import_type(conn):
    person_id = _insert_person(conn, "PerfTest")
    account_id = _insert_account(conn, person_id, "Compte TR", "CTO")

    batch_tr = create_batch(conn, "TR", person_id=person_id, account_id=account_id, account_name="Compte TR")
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, category, import_batch_id) "
        "VALUES ('2026-01-15', ?, ?, 'DEPOT', 100, 'Test', ?)",
        (person_id, account_id, batch_tr),
    )
    close_batch(conn, batch_tr, 1)

    batch_dep = create_batch(conn, "DEPENSES", person_id=person_id, person_name="PerfTest")
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant, import_batch_id) "
        "VALUES (?, '2026-01-01', 'Courses', 10, ?)",
        (person_id, batch_dep),
    )
    close_batch(conn, batch_dep, 1)

    batch_rev = create_batch(conn, "REVENUS", person_id=person_id, person_name="PerfTest")
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant, import_batch_id) "
        "VALUES (?, '2026-01-01', 'Salaire', 20, ?)",
        (person_id, batch_rev),
    )
    close_batch(conn, batch_rev, 1)

    batch_credit = create_batch(conn, "CREDIT", person_id=person_id, account_id=account_id, account_name="Compte TR")
    conn.execute(
        "INSERT INTO credits(person_id, account_id, nom, capital_emprunte, taux_nominal, duree_mois, date_debut, actif) "
        "VALUES (?, ?, 'Crédit Test', 1000, 1.0, 12, '2026-01-01', 1)",
        (person_id, account_id),
    )
    close_batch(conn, batch_credit, 1)
    conn.commit()

    batches = list_batches(conn, limit=20)
    by_type = {b["import_type"]: b for b in batches}
    assert by_type["TR"]["alive_rows"] == 1
    assert by_type["DEPENSES"]["alive_rows"] == 1
    assert by_type["REVENUS"]["alive_rows"] == 1
    assert by_type["CREDIT"]["alive_rows"] == 1
