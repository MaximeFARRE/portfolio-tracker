import io
import pytest
from services.imports import _to_float, _month_key_from_date, import_wide_csv_to_monthly_table


# ─── _to_float ───────────────────────────────────────────

def test_to_float_entier():
    assert _to_float("1234") == pytest.approx(1234.0)


def test_to_float_virgule_francaise():
    assert _to_float("1 234,56") == pytest.approx(1234.56)


def test_to_float_point():
    assert _to_float("1234.56") == pytest.approx(1234.56)


def test_to_float_vide():
    assert _to_float("") == pytest.approx(0.0)


def test_to_float_nan():
    import pandas as pd
    assert _to_float(float("nan")) == pytest.approx(0.0)
    assert _to_float(pd.NA) == pytest.approx(0.0)


def test_to_float_invalide():
    assert _to_float("abc") == pytest.approx(0.0)


# ─── _month_key_from_date ────────────────────────────────

def test_month_key_format_fr():
    assert _month_key_from_date("30/09/2025") == "2025-09-01"


def test_month_key_format_iso():
    assert _month_key_from_date("2025-03-15") == "2025-03-01"


def test_month_key_fin_mois():
    assert _month_key_from_date("28/02/2025") == "2025-02-01"


def test_month_key_date_invalide():
    with pytest.raises(ValueError):
        _month_key_from_date("not-a-date")


def test_month_key_vide():
    with pytest.raises(ValueError):
        _month_key_from_date("")


# ─── import_wide_csv_to_monthly_table ────────────────────────────────────────

def _make_csv(*rows: str) -> io.StringIO:
    """Construit un fichier CSV en mémoire (format wide)."""
    return io.StringIO("\n".join(rows))


def test_import_partiel_preserve_historique(conn):
    """Un réimport de janvier ne doit pas effacer les données de février."""
    # Insérer Alice
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.commit()

    # Données de février déjà présentes
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2026-02-01', 'Courses', 800)"
    )
    conn.commit()

    # Importer seulement janvier
    csv_jan = _make_csv(
        "Date,Courses,Restaurants",
        "31/01/2026,500,100",
    )
    result = import_wide_csv_to_monthly_table(
        conn,
        table="depenses",
        person_name="Alice",
        file=csv_jan,
        delete_existing=True,
    )

    assert result["nb_lignes"] == 2  # Courses + Restaurants

    # Février doit toujours exister
    rows = conn.execute(
        "SELECT COUNT(*) FROM depenses WHERE person_id = 1 AND mois = '2026-02-01'"
    ).fetchone()
    assert rows[0] == 1, "Les données de février ont été supprimées par erreur"

    # Janvier importé correctement
    rows_jan = conn.execute(
        "SELECT SUM(montant) FROM depenses WHERE person_id = 1 AND mois = '2026-01-01'"
    ).fetchone()
    assert rows_jan[0] == pytest.approx(600.0)


def test_double_import_meme_mois_remplace(conn):
    """Le deuxième import du même mois remplace le premier, sans doubler les données."""
    conn.execute("INSERT INTO people(name) VALUES ('Bob')")
    conn.commit()

    csv_v1 = _make_csv(
        "Date,Loyer",
        "28/02/2026,1000",
    )
    import_wide_csv_to_monthly_table(
        conn,
        table="depenses",
        person_name="Bob",
        file=csv_v1,
        delete_existing=True,
    )

    csv_v2 = _make_csv(
        "Date,Loyer",
        "28/02/2026,1200",
    )
    import_wide_csv_to_monthly_table(
        conn,
        table="depenses",
        person_name="Bob",
        file=csv_v2,
        delete_existing=True,
    )

    rows = conn.execute(
        "SELECT COUNT(*), SUM(montant) FROM depenses WHERE person_id = 1 AND mois = '2026-02-01' AND categorie = 'Loyer'"
    ).fetchone()
    assert rows[0] == 1, "Il y a des doublons après double import"
    assert rows[1] == pytest.approx(1200.0), "La valeur n'a pas été remplacée"
