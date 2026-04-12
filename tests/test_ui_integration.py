"""
Tests d'intégration UI headless — flux critiques.

Vérifie que les pages s'instancient, câblent les bons services et
gèrent un cas nominal sans lever d'exception.
Les tests Qt tournent en mode offscreen (aucune fenêtre visible).
"""
import os
import sys
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from contextlib import ExitStack

# Plateforme offscreen — doit être positionné avant toute import PyQt6
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-software-rasterizer --disable-dev-shm-usage",
)

# AA_ShareOpenGLContexts doit être positionné AVANT la création du QApplication.
# Il permet d'importer QWebEngineWidgets (utilisé par GoalsProjectionPage) sans erreur.
from PyQt6.QtWidgets import QApplication as _QApp
from PyQt6.QtCore import Qt as _Qt
_QApp.setAttribute(_Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

# Import de GoalsProjectionPage au niveau module (avant QApp) pour que
# QWebEngineWidgets soit chargé avant la création de l'instance QApplication.
try:
    from qt_ui.pages.goals_projection_page import GoalsProjectionPage as _GoalsPage
    _GOALS_PAGE_AVAILABLE = True
except Exception:
    _GoalsPage = None  # type: ignore
    _GOALS_PAGE_AVAILABLE = False


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """QApplication singleton pour la session de test."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def mem_conn():
    """Connexion SQLite en mémoire avec le schéma complet."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text(encoding="utf-8")
    for stmt in schema.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.upper().startswith("PRAGMA"):
            try:
                conn.execute(stmt)
            except Exception:
                pass
    yield conn
    conn.close()


@pytest.fixture
def conn_with_people(mem_conn):
    """Connexion avec deux personnes et un compte chacune."""
    mem_conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    mem_conn.execute("INSERT INTO people(name) VALUES ('Bob')")
    mem_conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) "
        "VALUES (1, 'PEA Alice', 'PEA', 'EUR')"
    )
    mem_conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) "
        "VALUES (2, 'Banque Bob', 'BANQUE', 'EUR')"
    )
    mem_conn.commit()
    return mem_conn


# ── Tests Recherche globale ───────────────────────────────────────────────────

class TestGlobalSearch:
    """Vérifie l'intégration service → main_window (sans instancier la fenêtre entière)."""

    def test_empty_query_returns_empty(self, mem_conn):
        from services.global_search_service import query_global_search
        assert query_global_search(mem_conn, "   ") == []

    def test_person_found_in_results(self, conn_with_people):
        from services.global_search_service import query_global_search
        results = query_global_search(conn_with_people, "alice")
        kinds = {r["kind"] for r in results}
        assert "person" in kinds
        person = next(r for r in results if r["kind"] == "person")
        assert "Alice" in person["label"]

    def test_account_returned_with_person(self, conn_with_people):
        from services.global_search_service import query_global_search
        results = query_global_search(conn_with_people, "alice")
        kinds = {r["kind"] for r in results}
        assert "account" in kinds

    def test_unknown_query_returns_empty(self, conn_with_people):
        from services.global_search_service import query_global_search
        results = query_global_search(conn_with_people, "zzz_inconnu_999")
        assert results == []

    def test_payload_types_are_safe(self, conn_with_people):
        """Vérifie que les payloads ne contiennent pas de types bruts Row sqlite3."""
        from services.global_search_service import query_global_search
        results = query_global_search(conn_with_people, "alice")
        for item in results:
            assert isinstance(item["kind"], str)
            assert isinstance(item["label"], str)
            if item.get("person_id") is not None:
                assert isinstance(item["person_id"], int)
            if item.get("account_id") is not None:
                assert isinstance(item["account_id"], int)


# ── Tests Import Page ─────────────────────────────────────────────────────────

class TestImportPage:
    """Vérifie que la page s'instancie et câble les services correctement."""

    def test_page_instantiates(self, qapp, mem_conn):
        from qt_ui.pages.import_page import ImportPage
        page = ImportPage(mem_conn)
        assert page is not None

    def test_person_combo_populated(self, qapp, conn_with_people):
        from qt_ui.pages.import_page import ImportPage
        page = ImportPage(conn_with_people)
        page.refresh()
        items = [page._person_combo.itemText(i) for i in range(page._person_combo.count())]
        assert "Alice" in items
        assert "Bob" in items

    def test_mode_switch_does_not_crash(self, qapp, conn_with_people):
        from qt_ui.pages.import_page import ImportPage
        page = ImportPage(conn_with_people)
        page.refresh()
        for i in range(page._mode_combo.count()):
            page._mode_combo.setCurrentIndex(i)  # doit être silencieux

    def test_import_lookup_service_used(self, conn_with_people):
        """get_person_id_by_name doit retrouver Alice par nom."""
        from services import import_lookup_service as lookup
        pid = lookup.get_person_id_by_name(conn_with_people, "Alice")
        assert pid == 1

    def test_list_accounts_by_types(self, conn_with_people):
        from services import import_lookup_service as lookup
        accounts = lookup.list_accounts_by_types(conn_with_people, 1, ["PEA"])
        assert len(accounts) == 1
        assert accounts[0]["name"] == "PEA Alice"


# ── Tests Goals Projection Page ───────────────────────────────────────────────

class TestGoalsProjectionPage:
    """Vérifie que la page se charge et délègue correctement aux services."""

    @staticmethod
    def _mk_dummy_plotly_view():
        from PyQt6.QtWidgets import QWidget

        class _DummyPlotlyView(QWidget):
            def __init__(self, *args, **kwargs):
                super().__init__(*args[:1] if args else ())
                min_h = kwargs.get("min_height")
                if isinstance(min_h, int):
                    self.setMinimumHeight(min_h)

            def set_figure(self, _fig):
                return None

            def set_loading(self, _loading: bool):
                return None

            def clear_figure(self):
                return None

        return _DummyPlotlyView

    @staticmethod
    def _patch_heavy_plotly_views(dummy_plotly):
        stack = ExitStack()
        stack.enter_context(patch("qt_ui.pages.goals_projection_page.PlotlyView", dummy_plotly))
        stack.enter_context(patch("qt_ui.panels.prevision_avancee_panel.PlotlyView", dummy_plotly))
        return stack

    @pytest.mark.skipif(not _GOALS_PAGE_AVAILABLE, reason="GoalsProjectionPage non importable (WebEngine manquant)")
    def test_page_instantiates(self, qapp, mem_conn):
        dummy_plotly = self._mk_dummy_plotly_view()
        with self._patch_heavy_plotly_views(dummy_plotly):
            page = _GoalsPage(mem_conn)
            assert page is not None

    @pytest.mark.skipif(not _GOALS_PAGE_AVAILABLE, reason="GoalsProjectionPage non importable (WebEngine manquant)")
    def test_page_with_people_does_not_crash(self, qapp, conn_with_people):
        dummy_plotly = self._mk_dummy_plotly_view()
        with self._patch_heavy_plotly_views(dummy_plotly):
            page = _GoalsPage(conn_with_people)
            assert page is not None

    def test_service_get_projection_base_no_data(self, mem_conn):
        """Sans snapshot, get_projection_base_for_scope renvoie une structure valide."""
        from services.projections import get_projection_base_for_scope
        base = get_projection_base_for_scope(mem_conn, "family")
        assert base["scope_type"] == "family"
        assert "net_worth" in base
        assert "avg_monthly_savings" in base

    def test_service_list_goals_empty(self, mem_conn):
        import pandas as pd
        from services.goals_projection_repository import list_goals
        goals = list_goals(mem_conn, "family", None)
        assert isinstance(goals, pd.DataFrame)
        assert goals.empty

    def test_service_list_scenarios_empty(self, mem_conn):
        import pandas as pd
        from services.goals_projection_repository import list_scenarios
        scenarios = list_scenarios(mem_conn, "family", None)
        assert isinstance(scenarios, pd.DataFrame)
        assert scenarios.empty

    def test_projection_service_builds_dataframe(self, mem_conn):
        """run_legacy_projection doit renvoyer un DataFrame valide avec les colonnes attendues."""
        from services.projection_service import ProjectionService
        from services.projections import ScenarioParams
        # ScenarioParams est un dataclass sans args obligatoires — on utilise les valeurs par défaut
        params = ScenarioParams()
        params.label = "Test"
        params.horizon_years = 10
        params.monthly_savings_override = 1_000.0
        df = ProjectionService.run_legacy_projection(
            conn=mem_conn,
            scope_type="family",
            scope_id=None,
            params=params,
        )
        assert not df.empty
        assert "month_index" in df.columns
        assert df["month_index"].iloc[-1] == 10 * 12
