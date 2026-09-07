from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Unit tests monkeypatch all external market-data calls. Keep collection usable
# in minimal/offline test environments where optional provider packages are absent.
try:
    import yfinance  # noqa: F401
except ModuleNotFoundError:
    fake = types.ModuleType("yfinance")
    class _UnavailableTicker:
        def __init__(self, *args, **kwargs):
            pass
        @property
        def info(self):
            raise RuntimeError("yfinance unavailable in minimal test environment")
        def history(self, *args, **kwargs):
            raise RuntimeError("yfinance unavailable in minimal test environment")
    fake.Ticker = _UnavailableTicker
    sys.modules["yfinance"] = fake
