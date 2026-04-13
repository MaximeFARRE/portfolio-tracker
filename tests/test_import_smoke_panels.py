import importlib
import math


def test_smoke_import_secondary_panels_modules():
    modules = [
        "qt_ui.panels.vue_ensemble_panel",
        "qt_ui.panels.revenus_panel",
        "qt_ui.panels.private_equity_panel",
    ]
    for module_name in modules:
        mod = importlib.import_module(module_name)
        assert mod is not None


def test_vue_ensemble_finite_float_contract():
    from qt_ui.panels.vue_ensemble_panel import _finite_float

    assert _finite_float(None) is None
    assert _finite_float(float("nan")) is None
    assert _finite_float("abc") is None
    assert _finite_float(0) == 0.0
    assert _finite_float(12.5) == 12.5
    assert _finite_float("3.14") == 3.14
    assert _finite_float(-2) == -2.0


def test_tr_panel_exposes_ticker_preview_thread():
    from qt_ui.pages._tr_panel import _TickerPreviewThread

    t = _TickerPreviewThread("AAPL")
    assert t is not None


def test_saisie_panel_has_ticker_preview_hooks():
    from qt_ui.panels.saisie_panel import SaisiePanel

    assert hasattr(SaisiePanel, "_schedule_ticker_preview")
    assert hasattr(SaisiePanel, "_run_pending_ticker_preview")

