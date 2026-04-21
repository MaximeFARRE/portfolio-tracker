import types

from services import ticker_preview_service as tps


class _FakeHistory:
    empty = True


class _FakeTickerOk:
    def __init__(self, _symbol):
        self.fast_info = {"last_price": 123.45, "currency": "eur"}

    def history(self, period="5d"):
        return _FakeHistory()


class _FakeTickerNoPrice:
    def __init__(self, _symbol):
        self.fast_info = {"last_price": 0, "currency": "usd"}

    def history(self, period="5d"):
        return _FakeHistory()


class _FakeSearch:
    def __init__(self, _symbol, max_results=1, enable_fuzzy_query=False):
        self.quotes = [{"shortname": "Fake Name", "symbol": "FAKE"}]


def test_preview_ticker_live_ok(monkeypatch):
    fake_mod = types.SimpleNamespace(Ticker=_FakeTickerOk, Search=_FakeSearch)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_mod)
    tps._PREVIEW_CACHE.clear()

    out = tps.preview_ticker_live("fake")
    assert out["found"] is True
    assert out["price"] == 123.45
    assert out["currency"] == "EUR"
    assert out["status"] == "ok"


def test_preview_ticker_live_never_returns_zero(monkeypatch):
    fake_mod = types.SimpleNamespace(Ticker=_FakeTickerNoPrice, Search=_FakeSearch)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_mod)
    tps._PREVIEW_CACHE.clear()

    out = tps.preview_ticker_live("fake-zero")
    assert out["price"] is None
    assert out["status"] in {"partial", "not_found"}
