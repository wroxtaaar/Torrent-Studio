"""The NexStream failure report must work without a Seedr session/CSRF token (the browser may not have one)."""
from fastapi.testclient import TestClient

import main
from integrations import nexstream_reports


def test_report_is_accepted_without_a_csrf_token(monkeypatch):
    async def no_forward(report):
        return True

    monkeypatch.setattr(nexstream_reports, "_forward", no_forward)
    nexstream_reports._forwarded.clear()
    response = TestClient(main.app).post(
        "/api/nexstream/report", json={"tmdbId": 424242, "title": "Test", "year": 2026, "reason": "player_not_working"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "stored": True}


def test_other_api_posts_still_need_the_csrf_token():
    response = TestClient(main.app).post("/api/files/delete", json={})
    assert response.status_code == 403
