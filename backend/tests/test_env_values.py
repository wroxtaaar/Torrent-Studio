from core.settings import env_values


def test_all_tokens_are_collected(monkeypatch):
    monkeypatch.setenv("TMDB_X_TOKEN", "a, b;c d")
    monkeypatch.setenv("TMDB_X_TOKEN_2", "e")
    monkeypatch.setenv("TMDB_X_TOKEN10", '"f"')
    monkeypatch.setenv("TMDB_X_TOKENS", "a\\ng")
    assert env_values("TMDB_X_TOKENS", "TMDB_X_TOKEN") == ["a", "g", "b", "c", "d", "e", "f"]


def test_empty_and_missing(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert env_values("NOPE_KEY") == []
