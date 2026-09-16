"""Persistence layer tests"""
import os
import json
import tempfile
import pytest
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.persistence import load_json, save_json, init_db, run_health_check
from app.config import CURRENT_SCHEMA_VERSION


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

    def test_save_empty_reminders_to_existing_large_file_is_allowed(self):
        """删除最后一条提醒是合法操作，必须落盘（此前会被空数据保护拦截）"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"reminders": [{"id": "x"}] * 50}, f)
            f.flush()
            path = f.name
        try:
            save_json(path, {"reminders": []})
            with open(path) as f:
                content = json.load(f)
            assert content["reminders"] == []
        finally:
            os.unlink(path)

    def test_save_none_payload_is_blocked(self):
        """结构损坏的 payload（None / 空 dict）仍然拦截"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"reminders": [{"id": "x"}] * 50}, f)
            f.flush()
            path = f.name
        try:
            save_json(path, None)
            save_json(path, {})
            with open(path) as f:
                content = json.load(f)
            assert len(content["reminders"]) == 50
        finally:
            os.unlink(path)

    def test_empty_reminders_with_account_data_is_written(self):
        """多账号模式下 reminders 是派生视图，账号内有任务时应正常写入"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"reminders": [{"id": "x"}] * 50, "users": {}}, f)
            f.flush()
            path = f.name
        try:
            data = {
                "reminders": [],
                "users": {"alice": {"username": "alice", "reminders": [{"id": "a1"}]}},
                "settings": {}
            }
            save_json(path, data)
            with open(path) as f:
                content = json.load(f)
            assert content["users"]["alice"]["reminders"][0]["id"] == "a1"
        finally:
            os.unlink(path)

    def test_empty_logs_list_is_written(self):
        """用户删光全部通知记录是合法状态，空列表必须落盘"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([{"id": "log-1", "title": "历史记录"}] * 20, f)
            f.flush()
            path = f.name
        try:
            assert os.path.getsize(path) > 100
            save_json(path, [])
            with open(path) as f:
                content = json.load(f)
            assert content == []
        finally:
            os.unlink(path)

    def test_empty_dict_is_still_blocked(self):
        """空 dict 仍视为异常数据，避免内存异常清空配置文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"reminders": [{"id": "x"}] * 50}, f)
            f.flush()
            path = f.name
        try:
            save_json(path, {})
            with open(path) as f:
                content = json.load(f)
            assert content["reminders"]
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
        assert db["schema_version"] == CURRENT_SCHEMA_VERSION
        assert logs == []

    def test_init_partial_db(self):
        db = {"reminders": [{"id": "x"}], "settings": {}}
        logs = [{"id": "log1"}]
        db, logs = init_db(db, logs)
        assert len(db["reminders"]) == 1
        assert db["users"] == {}
        assert len(logs) == 1

    def test_init_db_upgrades_legacy_schema(self):
        db, _ = init_db({"reminders": [], "settings": {}, "users": {}}, [])
        assert db["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_init_db_keeps_newer_schema(self):
        db, _ = init_db({"reminders": [], "settings": {}, "users": {}, "schema_version": 99}, [])
        assert db["schema_version"] == 99

    def test_init_db_tolerates_broken_schema_value(self):
        db, _ = init_db({"reminders": [], "settings": {}, "users": {}, "schema_version": "abc"}, [])
        assert db["schema_version"] == CURRENT_SCHEMA_VERSION
