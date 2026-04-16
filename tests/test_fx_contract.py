"""
Tests contrat FX : vérifie que les fonctions de conversion respectent le contrat
"None si taux manquant, jamais de montant brut silencieux".
"""
import pytest
import pandas as pd
from unittest.mock import patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_conn_no_fx():
    """Connexion SQLite en mémoire sans aucun taux FX en base."""
    import sqlite3
    from pathlib import Path

    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text(encoding="utf-8")
    for stmt in schema.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.upper().startswith("PRAGMA"):
            try:
                c.execute(stmt)
            except Exception:
                pass
    c.commit()
    return c


# ── fx.convert ────────────────────────────────────────────────────────────────

class TestFxConvert:
    def test_same_currency_returns_amount(self, conn):
        from services import fx
        result = fx.convert(conn, 100.0, "EUR", "EUR")
        assert result == pytest.approx(100.0)

    def test_blank_currency_defaults_to_eur_contract(self, conn):
        from services import fx
        result = fx.convert(conn, 100.0, "", None)
        assert result == pytest.approx(100.0)

    def test_missing_rate_returns_none(self):
        """Si le taux est absent en DB et que l'API échoue → None, pas le montant brut."""
        conn = _make_conn_no_fx()
        from services import fx

        with patch("services.fx.fetch_fx_rate", return_value=None):
            result = fx.convert(conn, 100.0, "USD", "EUR")

        assert result is None, (
            "fx.convert doit retourner None quand le taux est introuvable, "
            f"mais a retourné {result!r}"
        )

    def test_known_rate_converts_correctly(self, conn):
        from services import fx, repositories as repo, pricing

        repo.insert_fx_rate(conn, "USD", "EUR", pricing.today_str(), 0.92)
        conn.commit()

        result = fx.convert(conn, 100.0, "USD", "EUR")
        assert result == pytest.approx(92.0)


# ── market_history.convert_weekly ────────────────────────────────────────────

class TestConvertWeekly:
    def test_same_currency_returns_amount(self, conn):
        from services import market_history
        result = market_history.convert_weekly(conn, 50.0, "EUR", "EUR", "2024-01-01")
        assert result == pytest.approx(50.0)

    def test_blank_currency_defaults_to_eur_contract(self, conn):
        from services import market_history
        result = market_history.convert_weekly(conn, 50.0, "", None, "2024-01-01")
        assert result == pytest.approx(50.0)

    def test_missing_fx_returns_none(self, conn):
        """Taux hebdo absent → None, pas le montant brut."""
        from services import market_history
        result = market_history.convert_weekly(conn, 100.0, "USD", "EUR", "2024-01-01")
        assert result is None, (
            "convert_weekly doit retourner None quand le taux hebdo est absent, "
            f"mais a retourné {result!r}"
        )

    def test_known_weekly_rate_converts(self, conn):
        from services import market_history
        from services import market_repository as mrepo

        mrepo.upsert_fx_rate_weekly(conn, "USD", "EUR", "2024-01-01", 0.91)
        conn.commit()

        result = market_history.convert_weekly(conn, 200.0, "USD", "EUR", "2024-01-01")
        assert result == pytest.approx(182.0)

    def test_cross_rate_via_usd_when_direct_pair_missing(self, conn):
        from services import market_history, market_repository as mrepo

        mrepo.upsert_fx_rate_weekly(conn, "COP", "USD", "2024-01-01", 0.00025)
        mrepo.upsert_fx_rate_weekly(conn, "USD", "EUR", "2024-01-01", 0.80)
        conn.commit()

        rate = market_history.get_fx_asof(conn, "COP", "EUR", "2024-01-01")
        converted = market_history.convert_weekly(conn, 10_000.0, "COP", "EUR", "2024-01-01")

        assert rate == pytest.approx(0.0002)
        assert converted == pytest.approx(2.0)


# ── liquidites utilise fx.convert (point d'entrée unique) ────────────────────

class TestLiquiditesFxConvert:
    """
    _fx_to_eur a été supprimé : liquidites.py délègue désormais à fx.convert.
    Ces tests vérifient le contrat via fx.convert directement.
    """

    def test_eur_returns_amount_unchanged(self, conn):
        from services import fx
        assert fx.convert(conn, 42.0, "EUR", "EUR") == pytest.approx(42.0)

    def test_missing_rate_returns_none_not_raw_amount(self):
        """Cas critique : pas de taux → None, jamais le montant brut."""
        conn = _make_conn_no_fx()
        from services import fx

        with patch("services.fx.fetch_fx_rate", return_value=None):
            result = fx.convert(conn, 100.0, "USD", "EUR")

        assert result is None, (
            "fx.convert doit retourner None quand le taux est absent, "
            f"mais a retourné {result!r} (fallback dangereux détecté)"
        )

    def test_direct_rate_used(self, conn):
        from services import fx, repositories as repo, pricing

        repo.insert_fx_rate(conn, "USD", "EUR", pricing.today_str(), 0.93)
        conn.commit()

        result = fx.convert(conn, 100.0, "USD", "EUR")
        assert result == pytest.approx(93.0)


# ── valorisation impossible ───────────────────────────────────────────────────

class TestValuationImpossible:
    def test_convert_weekly_zero_amount_no_rate(self, conn):
        """Même un montant nul avec FX manquant doit retourner None."""
        from services import market_history
        result = market_history.convert_weekly(conn, 0.0, "GBP", "EUR", "2024-01-01")
        # 0.0 * None ne doit pas crasher, mais le taux reste absent
        # GBP→EUR pas en base → None
        assert result is None

    def test_fx_convert_exotic_currency_no_rate(self):
        """Devise exotique sans taux → None, jamais le montant original."""
        conn = _make_conn_no_fx()
        from services import fx

        with patch("services.fx.fetch_fx_rate", return_value=None):
            result = fx.convert(conn, 500.0, "COP", "EUR")

        assert result is None


class TestBourseAnalyticsMissingFx:
    def test_positions_valued_asof_skips_rows_when_fx_missing(self, conn):
        """
        Si convert_weekly retourne None, la ligne est ignorée (pas de crash, pas de round(None)).
        """
        from services import bourse_analytics

        accounts = pd.DataFrame(
            [{"id": 10, "account_type": "PEA", "name": "PEA Test", "currency": "EUR"}]
        )
        positions_df = pd.DataFrame(
            [{"symbol": "ABC", "quantity": 2.0, "asset_ccy": "USD", "account_id": 10}]
        )

        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.positions.compute_positions_asof", return_value=positions_df), \
             patch("services.bourse_analytics.market_history.get_price_asof", return_value=123.0), \
             patch("services.bourse_analytics.market_history.convert_weekly", return_value=None):
            out = bourse_analytics.compute_positions_valued_asof(conn, person_id=1, asof_week_date="2024-01-01")

        assert isinstance(out, pd.DataFrame)
        assert out.empty

    def test_invested_amount_asof_uses_buys_minus_sells_with_fees(self, conn):
        """
        invested_native = (ACHAT amount+fees) - (VENTE amount-fees)
        Exemple: (100+2 + 50+1) - (80-1) = 74
        """
        from services import bourse_analytics

        accounts = pd.DataFrame(
            [{"id": 10, "account_type": "PEA", "name": "PEA Test", "currency": "USD"}]
        )
        tx = pd.DataFrame(
            [
                {"date": "2024-01-01", "type": "ACHAT", "amount": 100.0, "fees": 2.0},
                {"date": "2024-01-02", "type": "ACHAT", "amount": 50.0, "fees": 1.0},
                {"date": "2024-01-03", "type": "VENTE", "amount": 80.0, "fees": 1.0},
            ]
        )

        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.repo.list_transactions", return_value=tx), \
             patch("services.bourse_analytics.market_history.convert_weekly", return_value=70.0) as mock_fx:
            out = bourse_analytics.compute_invested_amount_eur_asof(conn, person_id=1, asof_week_date="2024-01-03")

        assert out == pytest.approx(70.0)
        mock_fx.assert_called_once_with(conn, 74.0, "USD", "EUR", "2024-01-03")

    def test_positions_valued_asof_computes_values_and_weights(self, conn):
        from services import bourse_analytics

        accounts = pd.DataFrame(
            [{"id": 10, "account_type": "PEA", "name": "PEA Test", "currency": "EUR"}]
        )
        positions_df = pd.DataFrame(
            [
                {"symbol": "AAA", "quantity": 2.0, "asset_ccy": "EUR", "account_id": 10},
                {"symbol": "BBB", "quantity": 1.0, "asset_ccy": "EUR", "account_id": 10},
            ]
        )

        def _px(_conn, symbol, _asof):
            return 10.0 if symbol == "AAA" else 30.0

        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.positions.compute_positions_asof", return_value=positions_df), \
             patch("services.bourse_analytics.market_history.get_price_asof", side_effect=_px), \
             patch("services.bourse_analytics.market_history.convert_weekly", side_effect=lambda _c, a, *_: a):
            out = bourse_analytics.compute_positions_valued_asof(conn, person_id=1, asof_week_date="2024-01-01")

        assert list(out["ticker"]) == ["BBB", "AAA"]
        assert list(out["valeur_eur"]) == [30.0, 20.0]
        assert list(out["poids_%"]) == [60.0, 40.0]

    def test_live_positions_for_account_short_circuits_when_no_assets(self, conn):
        from services import bourse_analytics

        with patch("services.bourse_analytics.repo.get_account", return_value={"id": 10, "currency": "EUR"}), \
             patch("services.bourse_analytics.repo.list_account_asset_ids", return_value=[]), \
             patch("services.bourse_analytics.repo.list_transactions") as mock_tx, \
             patch("services.bourse_analytics.repo.get_latest_prices") as mock_prices, \
             patch("services.portfolio.compute_positions_v2_fx") as mock_compute:
            out = bourse_analytics.get_live_bourse_positions_for_account(conn, account_id=10)

        assert isinstance(out, pd.DataFrame)
        assert out.empty
        mock_tx.assert_not_called()
        mock_prices.assert_not_called()
        mock_compute.assert_not_called()

    def test_live_positions_for_account_keeps_non_cote_and_fallbacks_to_pru(self, conn):
        from services import bourse_analytics

        pos_account = pd.DataFrame(
            [
                {
                    "asset_id": 26,
                    "symbol": "LENDOPOLIS",
                    "name": "Lendopolis",
                    "asset_type": "non_cote",
                    "quantity": 1000.0,
                    "pru": 10.0,
                    "last_price": None,
                    "value": None,
                    "pnl_latent": None,
                    "valuation_status": "missing_price",
                    "asset_ccy": "EUR",
                }
            ]
        )

        with patch("services.bourse_analytics.repo.get_account", return_value={"id": 10, "currency": "EUR"}), \
             patch("services.bourse_analytics.repo.list_account_asset_ids", return_value=[26]), \
             patch("services.bourse_analytics.repo.list_transactions", return_value=pd.DataFrame([{"id": 1}])), \
             patch("services.bourse_analytics.repo.get_latest_prices", return_value=pd.DataFrame()), \
             patch("services.portfolio.compute_positions_v2_fx", return_value=pos_account):
            out = bourse_analytics.get_live_bourse_positions_for_account(conn, account_id=10)

        assert len(out) == 1
        row = out.iloc[0]
        assert row["asset_type"] == "non_cote"
        assert row["last_price"] == pytest.approx(10.0)
        assert row["value"] == pytest.approx(10000.0)
        assert row["valuation_status"] == "fallback_buy_price"

    def test_live_positions_skips_accounts_without_assets(self, conn):
        from services import bourse_analytics

        accounts = pd.DataFrame([
            {"id": 10, "account_type": "PEA", "name": "PEA A", "currency": "EUR"},
            {"id": 11, "account_type": "CTO", "name": "CTO B", "currency": "EUR"},
        ])
        pos_account_11 = pd.DataFrame([
            {"symbol": "ABC", "quantity": 2.0, "last_price": 10.0, "value": 20.0, "pnl_latent": 1.0}
        ])

        def _asset_ids(_conn, account_id):
            return [] if int(account_id) == 10 else [501]

        def _tx(_conn, account_id=None, **_kwargs):
            return pd.DataFrame([{"id": 1, "type": "ACHAT", "amount": 100.0}]) if int(account_id) == 11 else pd.DataFrame()

        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.repo.list_account_asset_ids", side_effect=_asset_ids), \
             patch("services.bourse_analytics.repo.list_transactions", side_effect=_tx), \
             patch("services.bourse_analytics.repo.get_latest_prices", return_value=pd.DataFrame()), \
             patch("services.portfolio.compute_positions_v2_fx", return_value=pos_account_11):
            out = bourse_analytics.get_live_bourse_positions(conn, person_id=1)

        assert isinstance(out, pd.DataFrame)
        assert not out.empty
        assert set(out["compte"].tolist()) == {"CTO B"}


class TestLiquiditesSummary:
    def test_summary_aggregates_bank_and_bourse_cash_with_fx(self, conn):
        from services import liquidites, repositories as repo, pricing

        conn.execute("INSERT INTO people(name) VALUES ('Alice')")
        conn.execute(
            "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (1, 'Banque EUR', 'BANQUE', 'EUR')"
        )
        conn.execute(
            "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (1, 'PEA USD', 'PEA', 'USD')"
        )

        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-01', 1, 1, 'DEPOT', 1000, 0)"
        )
        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-02', 1, 1, 'RETRAIT', 100, 0)"
        )
        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-01', 1, 2, 'DEPOT', 500, 0)"
        )
        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-02', 1, 2, 'ACHAT', 100, 2)"
        )
        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-03', 1, 2, 'VENTE', 40, 1)"
        )
        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-04', 1, 2, 'DIVIDENDE', 10, 0)"
        )
        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-05', 1, 2, 'FRAIS', 5, 0)"
        )

        repo.insert_fx_rate(conn, "USD", "EUR", pricing.today_str(), 0.5)
        conn.commit()

        out = liquidites.get_liquidites_summary(conn, person_id=1)
        assert out["bank_cash_eur"] == pytest.approx(900.0)
        assert out["bourse_cash_eur"] == pytest.approx(221.0)
        assert out["pe_cash_eur"] == pytest.approx(0.0)
        assert out["total_eur"] == pytest.approx(1121.0)


class TestBourseAccountBreakdown:
    def test_breakdown_cash_asof_respects_transaction_formula(self, conn):
        from services import bourse_analytics

        accounts = pd.DataFrame(
            [{"id": 10, "account_type": "PEA", "name": "PEA Test", "currency": "USD"}]
        )
        tx = pd.DataFrame(
            [
                {"date": "2024-01-01", "type": "DEPOT", "amount": 100.0, "fees": 0.0},
                {"date": "2024-01-02", "type": "RETRAIT", "amount": 4.0, "fees": 0.0},
                {"date": "2024-01-03", "type": "ACHAT", "amount": 20.0, "fees": 1.0},
                {"date": "2024-01-04", "type": "VENTE", "amount": 10.0, "fees": 2.0},
                {"date": "2024-01-05", "type": "DIVIDENDE", "amount": 5.0, "fees": 0.0},
                {"date": "2024-01-06", "type": "INTERETS", "amount": 1.0, "fees": 0.0},
                {"date": "2024-01-07", "type": "FRAIS", "amount": 3.0, "fees": 0.0},
            ]
        )

        # cash_native = 100 - 4 - 20 + 10 + 5 + 1 - 3 - (1+2) = 86
        # cash_eur @0.5 = 43
        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.positions.compute_positions_asof", return_value=pd.DataFrame()), \
             patch("services.bourse_analytics.repo.list_transactions", return_value=tx), \
             patch("services.bourse_analytics.market_history.convert_weekly", side_effect=lambda _c, a, *_: a * 0.5):
            out = bourse_analytics.compute_accounts_breakdown_asof(conn, person_id=1, asof_week_date="2024-01-07")

        assert len(out) == 1
        assert float(out.iloc[0]["Cash (EUR)"]) == pytest.approx(43.0)
        assert float(out.iloc[0]["Holdings (EUR)"]) == pytest.approx(0.0)
        assert float(out.iloc[0]["Total (EUR)"]) == pytest.approx(43.0)

    def test_accounts_breakdown_skips_account_when_cash_fx_missing(self, conn):
        """
        Si la conversion FX du cash échoue, le compte est ignoré sans exception.
        """
        from services import bourse_analytics

        accounts = pd.DataFrame(
            [{"id": 10, "account_type": "PEA", "name": "PEA Test", "currency": "USD"}]
        )
        tx = pd.DataFrame(
            [{"id": 1, "date": "2024-01-01", "type": "DEPOT", "amount": 1000.0, "fees": 0.0}]
        )

        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.positions.compute_positions_asof", return_value=pd.DataFrame()), \
             patch("services.bourse_analytics.repo.list_transactions", return_value=tx), \
             patch("services.bourse_analytics.market_history.convert_weekly", return_value=None):
            out = bourse_analytics.compute_accounts_breakdown_asof(conn, person_id=1, asof_week_date="2024-01-01")

        assert isinstance(out, pd.DataFrame)
        assert out.empty


class TestDataQualityFalseZeroRegressions:
    def test_liquidites_missing_fx_marks_partial_without_raw_zero(self, conn):
        from services import liquidites

        conn.execute("INSERT INTO people(name) VALUES ('Alice')")
        conn.execute(
            "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (1, 'Banque USD', 'BANQUE', 'USD')"
        )
        conn.execute(
            "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2024-01-01', 1, 1, 'DEPOT', 1000, 0)"
        )
        conn.commit()

        with patch("services.fx.fetch_fx_rate", return_value=None):
            out = liquidites.get_liquidites_summary(conn, person_id=1)

        assert out["quality_status"] == "partial"
        assert out["bank_cash_eur"] == pytest.approx(0.0)
        assert out["total_eur"] == pytest.approx(0.0)
        assert out["missing_fx"] == [{
            "component": "bank",
            "account_id": 1,
            "currency": "USD",
            "amount_native": 1000.0,
        }]


class TestFxImpactDecomposition:
    def test_positions_v2_fx_splits_market_and_currency_effects(self, conn):
        from services import portfolio
        from services import repositories as repo
        from services import market_repository as mrepo

        conn.execute(
            "INSERT INTO assets(id, symbol, name, asset_type, currency) VALUES (1, 'AAA', 'AAA Corp', 'action', 'USD')"
        )
        # FX courant (utilisé pour la valorisation live EUR)
        repo.insert_fx_rate(conn, "USD", "EUR", "2024-02-01", 1.20)
        # FX au moment de l'achat (utilisé pour fx_moyen_achat)
        mrepo.upsert_fx_rate_weekly(conn, "USD", "EUR", "2024-01-01", 1.00)

        tx = pd.DataFrame([
            {
                "id": 1,
                "date": "2024-01-01",
                "type": "ACHAT",
                "asset_id": 1,
                "asset_symbol": "AAA",
                "asset_name": "AAA Corp",
                "quantity": 10.0,
                "price": 100.0,     # devise actif (USD)
                "amount": 1000.0,   # EUR (coût total)
                "fees": 0.0,
            }
        ])
        latest_prices = pd.DataFrame([{"asset_id": 1, "price": 120.0, "currency": "USD"}])

        out = portfolio.compute_positions_v2_fx(conn, tx, latest_prices, account_ccy="EUR")
        row = out.iloc[0]

        # valeur actuelle EUR = 10 * 120 * 1.20 = 1440
        # valeur sans effet change = 10 * 120 * 1.00 = 1200
        # fx_gain = 240 ; market_gain = 1200 - 1000 = 200 ; total = 440
        assert float(row["fx_gain_eur"]) == pytest.approx(240.0)
        assert float(row["market_gain_eur"]) == pytest.approx(200.0)
        assert float(row["total_gain_eur"]) == pytest.approx(440.0)
        # Compat rétro
        assert float(row["pnl_fx"]) == pytest.approx(float(row["fx_gain_eur"]))

    def test_fx_summary_aggregates_by_currency_and_account_with_missing_breakdown(self):
        from services import bourse_analytics

        df_positions = pd.DataFrame(
            [
                {"asset_ccy": "USD", "fx_gain_eur": 120.0, "compte": "CTO 1"},
                {"asset_ccy": "USD", "fx_gain_eur": None, "compte": "CTO 2"},
                {"asset_ccy": "GBP", "fx_gain_eur": -30.0, "compte": "PEA"},
                {"asset_ccy": "EUR", "fx_gain_eur": 0.0, "compte": "PEA"},  # ignoré (EUR)
            ]
        )

        res = bourse_analytics.compute_fx_pnl_summary(df_positions)
        assert res["total_fx_pnl"] == pytest.approx(90.0)
        assert res["by_currency"]["USD"] == pytest.approx(120.0)
        assert res["by_currency"]["GBP"] == pytest.approx(-30.0)
        assert res["by_account"]["CTO 1"] == pytest.approx(120.0)
        assert res["by_account"]["PEA"] == pytest.approx(-30.0)
        assert res["missing_breakdown_count"] == 1

    def test_live_position_missing_price_is_not_valued_as_zero(self):
        from services import portfolio

        tx = pd.DataFrame([{
            "id": 1,
            "date": "2024-01-01",
            "type": "ACHAT",
            "asset_id": 42,
            "asset_symbol": "ABC",
            "asset_name": "ABC Corp",
            "quantity": 2.0,
            "price": 10.0,
        }])

        out = portfolio.compute_positions_v1(tx, pd.DataFrame(columns=["asset_id", "price"]))

        assert out.loc[0, "valuation_status"] == "missing_price"
        assert pd.isna(out.loc[0, "last_price"])
        assert pd.isna(out.loc[0, "value"])
        assert pd.isna(out.loc[0, "pnl_latent"])

    def test_bourse_state_asof_missing_fx_is_partial_without_fallback_rate(self, conn):
        from services import bourse_analytics

        accounts = pd.DataFrame(
            [{"id": 10, "account_type": "PEA", "name": "PEA Test", "currency": "EUR"}]
        )
        positions_df = pd.DataFrame(
            [{"symbol": "ABC", "quantity": 2.0, "asset_ccy": "USD", "account_id": 10}]
        )

        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.positions.compute_positions_asof", return_value=positions_df), \
             patch("services.market_history.get_price_asof", return_value=10.0), \
             patch("services.market_history.get_fx_asof", return_value=None), \
             patch("services.bourse_analytics.compute_invested_amount_eur_asof", return_value=100.0):
            out = bourse_analytics.get_bourse_state_asof(conn, person_id=1, asof_date="2024-01-01")

        row = out["df"].iloc[0]
        assert out["quality_status"] == "partial"
        assert out["total_val"] is None
        assert out["total_pnl"] is None
        assert row["valuation_status"] == "missing_fx"
        assert row["fx_rate"] is None
        assert row["value"] is None
        assert out["missing_fx"] == [{"symbol": "ABC", "currency": "USD", "date": "2024-01-01"}]

    def test_performance_metrics_absent_history_returns_non_calculable_status(self, conn):
        from services import bourse_analytics

        income_df = pd.DataFrame(columns=["date", "month", "year", "type", "amount_eur"])
        income_df.attrs["missing_fx"] = []

        with patch("services.snapshots.get_person_weekly_series", return_value=pd.DataFrame()), \
             patch("services.bourse_analytics.compute_invested_amount_eur_asof", return_value=100.0), \
             patch("services.bourse_analytics.compute_passive_income_history", return_value=income_df):
            out = bourse_analytics.get_bourse_performance_metrics(conn, person_id=1, current_live_value=1000.0)

        assert out["quality_status"] == "partial"
        assert out["global_perf_pct"] is None
        assert out["ytd_perf_pct"] is None
        assert "historique bourse absent" in out["perf_warnings"]

    def test_passive_income_missing_fx_is_recorded_not_summed_as_zero(self, conn):
        from services import bourse_analytics

        accounts = pd.DataFrame(
            [{"id": 10, "account_type": "CTO", "name": "CTO Test", "currency": "USD"}]
        )
        tx = pd.DataFrame(
            [{"date": "2024-01-05", "type": "DIVIDENDE", "amount": 50.0, "fees": 0.0}]
        )

        with patch("services.bourse_analytics.repo.list_accounts", return_value=accounts), \
             patch("services.bourse_analytics.repo.list_transactions", return_value=tx), \
             patch("services.market_history.convert_weekly", return_value=None):
            out = bourse_analytics.compute_passive_income_history(conn, person_id=1)

        assert out.empty
        assert out.attrs["quality_status"] == "partial"
        assert out.attrs["missing_fx"] == [{
            "account_id": 10,
            "currency": "USD",
            "date": "2024-01-05",
            "type": "DIVIDENDE",
            "amount_native": 50.0,
        }]


class TestPrivateEquityAccountBasedValuation:
    def test_account_based_assets_use_manual_price_then_buy_price_fallback(self, conn):
        from services import private_equity as pe

        conn.execute("INSERT INTO people(id, name) VALUES (1, 'Alice')")
        conn.execute(
            "INSERT INTO accounts(id, person_id, name, account_type, currency) VALUES (10, 1, 'PEA-PME', 'PEA_PME', 'EUR')"
        )
        conn.execute(
            "INSERT INTO assets(id, symbol, name, asset_type, currency) VALUES (26, 'LENDOPOLIS', 'Lendopolis', 'non_cote', 'EUR')"
        )
        conn.execute(
            """
            INSERT INTO transactions(
                id, date, person_id, account_id, type, asset_id, quantity, price, fees, amount
            ) VALUES (1, '2025-11-05', 1, 10, 'ACHAT', 26, 100.0, 10.0, 0.0, 1000.0)
            """
        )
        conn.execute(
            "INSERT INTO prices(asset_id, date, price, currency, source) VALUES (26, '2026-04-14', 12.0, 'EUR', 'MANUEL')"
        )
        conn.commit()

        df_manual = pe.get_account_based_pe_assets_asof(conn, person_id=1, asof_date="2026-04-14")
        assert len(df_manual) == 1
        row_manual = df_manual.iloc[0]
        assert row_manual["last_price"] == pytest.approx(12.0)
        assert row_manual["value_eur"] == pytest.approx(1200.0)
        assert row_manual["cost_eur"] == pytest.approx(1000.0)
        assert row_manual["pnl_eur"] == pytest.approx(200.0)
        assert row_manual["valuation_status"] == "ok"

        conn.execute("DELETE FROM prices WHERE asset_id = 26")
        conn.commit()

        df_fallback = pe.get_account_based_pe_assets_asof(conn, person_id=1, asof_date="2026-04-14")
        assert len(df_fallback) == 1
        row_fallback = df_fallback.iloc[0]
        assert row_fallback["last_price"] == pytest.approx(10.0)
        assert row_fallback["value_eur"] == pytest.approx(1000.0)
        assert row_fallback["cost_eur"] == pytest.approx(1000.0)
        assert row_fallback["pnl_eur"] == pytest.approx(0.0)
        assert row_fallback["valuation_status"] == "fallback_buy_price"
