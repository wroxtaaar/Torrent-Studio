"""Test configuration: set safe environment defaults before the app is imported."""

import os
import sys
from pathlib import Path

# Never reach out to metadata providers from tests.
os.environ.setdefault("CACHE_ONLY_MODE", "true")
os.environ.setdefault("SEEDR_SESSION_SECRET", "test-only-session-secret")

# Make `import main` work when pytest is started from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_runtest_logreport(report):
    """On GitHub Actions, surface the reason a test failed as a file annotation.

    The full job log is not always readable from outside the run, annotations are.
    """
    if not (report.failed and os.environ.get("GITHUB_ACTIONS")):
        return
    lines = [line for line in (report.longreprtext or "").strip().splitlines() if line.strip()]
    message = " | ".join(lines[-8:])[:1200]
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"\n::error title=pytest {report.nodeid} ({report.when})::{message}", flush=True)
