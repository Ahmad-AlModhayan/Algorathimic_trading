from pathlib import Path

from core.config import Settings


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:5432/tradelab")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings(_env_file=None)
    assert str(s.database_url).startswith("postgresql://u:p@db.example.com")
    assert s.candles_dir == Path(tmp_path) / "candles"
    assert s.binance_api_key is None


def test_schema_files_are_idempotent_sql():
    for p in sorted(Path("sql").glob("*.sql")):
        text = p.read_text().upper()
        assert "CREATE TABLE IF NOT EXISTS" in text, p
        assert "DROP " not in text, p
