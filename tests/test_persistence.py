"""Persistence layer tests"""
import os
import json
import tempfile
import pytest
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.persistence import load_json, save_json, init_db, run_health_check


class TestLoadJson:
    def test_load_nonexistent_file_returns_default(self):
        result = load_json("/nonexistent/path/test.json", {"default": True})
        assert result == {"default": True}

    def test_load_valid_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"key": "value"}, f)
            f.flush()
            result = load_json(f.name, {})
        os.unlink(f.name)
        assert result == {"key": "value"}

    def test_load_empty_file_returns_default(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.flush()
            result = load_json(f.name, {"default": True})
        os.unlink(f.name)
        assert result == {"default": True}

    def test_load_corrupt_json_raises(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("this is not valid json")
            f.flush()
            with pytest.raises(RuntimeError, match="配置文件损坏"):
                load_json(f.name, {})
        os.unlink(f.name)


class TestSaveJson:
    def test_save_and_load_roundtrip(self):
        data = {
            "reminders": [
                {"id": "test-1", "title": "测试提醒", "time": "10:00", "repeat": "daily", "status": "pending"}
            ],
            "settings": {"language": "zh", "dark_mode": True},
            "users": {}
        }
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            save_json(path, data)
            assert os.path.exists(path)
            loaded = load_json(path, {"reminders": [], "settings": {}})
            assert len(loaded["reminders"]) == 1
            assert loaded["reminders"][0]["id"] == "test-1"
            assert loaded["reminders"][0]["title"] == "测试提醒"
            assert loaded["settings"]["language"] == "zh"
        finally:
            os.unlink(path)

    def test_save_empty_data_to_existing_large_file_is_blocked(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"reminders": [{"id": "x"}] * 50}, f)
            f.flush()
            path = f.name
        try:
            save_json(path, {"reminders": []})
            with open(path) as f:
                content = json.load(f)
            assert len(content["reminders"]) > 0
        finally:
            os.unlink(path)


class TestInitDb:
    def test_init_empty_db(self):
        db = {}
        logs = None
        db, logs = init_db(db, logs)
        assert db["reminders"] == []
        assert db["settings"] != {}
        assert db["users"] == {}
        assert logs == []

    def test_init_partial_db(self):
        db = {"reminders": [{"id": "x"}], "settings": {}}
        logs = [{"id": "log1"}]
        db, logs = init_db(db, logs)
        assert len(db["reminders"]) == 1
        assert db["users"] == {}
        assert len(logs) == 1
