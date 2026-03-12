import pytest
from services.imports import _to_float, _month_key_from_date


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
