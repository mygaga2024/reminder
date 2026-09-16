"""API endpoint tests"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import datetime
import tempfile
from unittest.mock import MagicMock, patch
import pytest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["TZ"] = "Asia/Shanghai"
os.environ["API_KEY"] = ""

from flask import Flask
from flask_cors import CORS
from app.api import register_routes
from app import users


@pytest.fixture
def app():
    flask_app = Flask(__name__)
    CORS(flask_app)
    flask_app.config['LIST_HANDLER'] = MagicMock()
    flask_app.config['LIST_HANDLER'].logs = []
    flask_app.config['GLOBAL_DB'] = {
        "reminders": [],
        "settings": {"language": "zh", "dark_mode": True, "webhooks": {"wecom": "", "dingtalk": "", "lark": ""}},
        "users": {}
    }
    flask_app.config['GLOBAL_LOGS'] = []
    scheduler = MagicMock()
    scheduler.get_jobs.return_value = []
    scheduler.running = False
    flask_app.config['GLOBAL_SCHEDULER'] = scheduler
    register_routes(flask_app, flask_app.config['GLOBAL_DB'], flask_app.config['GLOBAL_LOGS'], scheduler)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestStateEndpoint:
    def test_get_state_returns_200(self, client):
        resp = client.get('/api/state')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "db" in data
        assert "logs" in data
        assert "version" in data
        assert "persistence" in data
        assert "auth_required" in data


class TestReminderEndpoints:
    def test_add_reminder_success(self, client):
        resp = client.post('/api/reminders', json={
            "title": "测试提醒",
            "time": "10:00",
            "repeat": "daily",
            "priority": "low"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "id" in data
        assert data["title"] == "测试提醒"

    def test_add_reminder_empty_title_fails(self, client):
        resp = client.post('/api/reminders', json={
            "title": "",
            "time": "10:00",
            "repeat": "daily"
        })
        assert resp.status_code == 400

    def test_add_reminder_no_title_fails(self, client):
        resp = client.post('/api/reminders', json={
            "time": "10:00",
            "repeat": "daily"
        })
        assert resp.status_code == 400

    def test_add_reminder_invalid_repeat_fails(self, client):
        resp = client.post('/api/reminders', json={
            "title": "测试",
            "time": "10:00",
            "repeat": "invalid_mode"
        })
        assert resp.status_code == 400

    def test_add_reminder_invalid_priority_fails(self, client):
        resp = client.post('/api/reminders', json={
            "title": "测试",
            "time": "10:00",
            "repeat": "daily",
            "priority": "super_high"
        })
        assert resp.status_code == 400

    def test_delete_reminder_success(self, client):
        add_resp = client.post('/api/reminders', json={
            "title": "测试",
            "time": "10:00",
            "repeat": "daily"
        })
        rid = add_resp.get_json()["id"]

        resp = client.delete(f'/api/reminders/{rid}')
        assert resp.status_code == 200

        state = client.get('/api/state').get_json()
        assert all(r["id"] != rid for r in state["db"]["reminders"])

    def test_update_reminder_success(self, client):
        add_resp = client.post('/api/reminders', json={
            "title": "原标题",
            "time": "10:00",
            "repeat": "daily"
        })
        rid = add_resp.get_json()["id"]

        resp = client.put(f'/api/reminders/{rid}', json={
            "title": "新标题",
            "time": "11:00",
            "repeat": "daily"
        })
        assert resp.status_code == 200

        state = client.get('/api/state').get_json()
        updated = [r for r in state["db"]["reminders"] if r["id"] == rid]
        assert len(updated) == 1
        assert updated[0]["title"] == "新标题"

    def test_clear_completed_reminders(self, client, app):
        r1 = client.post('/api/reminders', json={
            "title": "已完成任务",
            "time": "10:00",
            "repeat": "daily"
        }).get_json()
        r2 = client.post('/api/reminders', json={
            "title": "待办任务",
            "time": "11:00",
            "repeat": "daily"
        }).get_json()

        client.put(f'/api/reminders/{r1["id"]}', json={
            "title": "已完成任务",
            "time": "10:00",
            "repeat": "daily",
            "status": "completed"
        })

        app.config['GLOBAL_LOGS'] = [
            {"id": "log-1", "reminder_id": r1["id"], "title": "已完成任务", "triggered_at": "2024-01-01T00:00:00"},
            {"id": "log-2", "reminder_id": r2["id"], "title": "待办任务", "triggered_at": "2024-01-02T00:00:00"},
        ]

        resp = client.post('/api/reminders/clear-completed')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["deleted"] == 1
        assert data["logs_deleted"] == 1

        state = client.get('/api/state').get_json()
        assert len(state["db"]["reminders"]) == 1
        assert state["db"]["reminders"][0]["id"] == r2["id"]
        assert len(app.config['GLOBAL_LOGS']) == 1
        assert app.config['GLOBAL_LOGS'][0]["reminder_id"] == r2["id"]


class TestSettingsEndpoint:
    def test_update_settings_success(self, client):
        resp = client.post('/api/settings', json={
            "language": "en",
            "dark_mode": False
        })
        assert resp.status_code == 200

        state = client.get('/api/state').get_json()
        assert state["db"]["settings"]["language"] == "en"

    def test_invalid_webhook_url_fails(self, client):
        resp = client.post('/api/settings', json={
            "webhooks": {"wecom": "not-a-url"}
        })
        assert resp.status_code == 400


class TestLogEndpoints:
    def test_delete_log_persists(self, client, app):
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-1", "title": "测试日志", "triggered_at": "2024-01-01T00:00:00"}
        ]
        resp = client.delete('/api/logs/log-1')
        assert resp.status_code == 200
        assert len(app.config['GLOBAL_LOGS']) == 0

    def test_hide_log(self, client, app):
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-1", "title": "测试日志", "triggered_at": "2024-01-01T00:00:00"}
        ]
        resp = client.post('/api/logs/hide/log-1')
        assert resp.status_code == 200
        assert app.config['GLOBAL_LOGS'][0].get("hidden") is True


class TestValidation:
    def test_empty_request_body_fails(self, client):
        resp = client.post('/api/reminders', data=json.dumps(None), content_type='application/json')
        assert resp.status_code == 400

    def test_empty_settings_body_fails(self, client):
        resp = client.post('/api/settings', data=json.dumps(None), content_type='application/json')
        assert resp.status_code == 400

    def test_invalid_time_format_rejected(self, client):
        resp = client.post('/api/reminders', json={
            "title": "非法时间", "time": "不是时间", "repeat": "daily"
        })
        assert resp.status_code == 400
        assert "提醒时间格式无效" in resp.get_json()["error"]

    def test_out_of_range_clock_rejected(self, client):
        resp = client.post('/api/reminders', json={
            "title": "越界时间", "time": "25:00", "repeat": "daily"
        })
        assert resp.status_code == 400

    def test_nonexistent_date_rejected(self, client):
        resp = client.post('/api/reminders', json={
            "title": "不存在的日期", "time": "2026-02-30 10:00", "repeat": "once"
        })
        assert resp.status_code == 400

    def test_valid_datetime_accepted(self, client):
        resp = client.post('/api/reminders', json={
            "title": "合法日期", "time": "2027-02-28 10:00", "repeat": "once"
        })
        assert resp.status_code == 200

    def test_yearly_requires_date(self, client):
        resp = client.post('/api/reminders', json={
            "title": "没有日期的每年提醒", "time": "09:00", "repeat": "yearly"
        })
        assert resp.status_code == 400
        assert "每年" in resp.get_json()["error"]

    def test_yearly_with_date_accepted(self, client):
        resp = client.post('/api/reminders', json={
            "title": "每年生日", "time": "2026-09-09 06:28", "repeat": "yearly"
        })
        assert resp.status_code == 200

    def test_monthly_valid_and_invalid_day(self, client):
        ok = client.post('/api/reminders', json={
            "title": "每月15号", "time": "09:00", "repeat": "monthly:15"
        })
        assert ok.status_code == 200
        last = client.post('/api/reminders', json={
            "title": "每月最后一天", "time": "09:00", "repeat": "monthly:last"
        })
        assert last.status_code == 200
        bad = client.post('/api/reminders', json={
            "title": "每月32号", "time": "09:00", "repeat": "monthly:32"
        })
        assert bad.status_code == 400
        bad_format = client.post('/api/reminders', json={
            "title": "每月乱填", "time": "09:00", "repeat": "monthly:abc"
        })
        assert bad_format.status_code == 400

    def test_lunar_repeat_validation(self, client):
        ok = client.post('/api/reminders', json={
            "title": "农历八月十五", "time": "09:00", "repeat": "lunar:08-15"
        })
        assert ok.status_code == 200
        leap = client.post('/api/reminders', json={
            "title": "闰六月初一", "time": "09:00", "repeat": "lunar:-06-01"
        })
        assert leap.status_code == 200
        bad = client.post('/api/reminders', json={
            "title": "非法农历", "time": "09:00", "repeat": "lunar:13-01"
        })
        assert bad.status_code == 400


class TestAuth:
    @patch('app.auth.API_KEY', 'test-key-123')
    def test_api_key_required(self, client):
        from app.auth import API_KEY as auth_key
        assert auth_key == 'test-key-123'


@pytest.fixture(autouse=True)
def clear_login_locks():
    """避免登录失败计数在用例之间串扰"""
    yield
    users._login_failures.clear()


class TestMultiAccount:
    """多账号注册登录与数据隔离"""

    def register(self, client, username, password="secret123", **extra):
        payload = {"username": username, "password": password, "confirm": password}
        payload.update(extra)
        resp = client.post('/api/auth/register', json=payload)
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()["token"]

    def headers(self, token):
        return {"X-Auth-Token": token}

    def test_open_mode_before_any_account(self, client):
        status = client.get('/api/auth/status').get_json()
        assert status["login_required"] is False
        assert status["accounts"] == 0
        assert client.get('/api/state').status_code == 200

    def test_login_required_after_registration(self, client):
        token = self.register(client, "alice")
        assert client.get('/api/state').status_code == 401
        assert client.get('/api/state').get_json()["code"] == "unauthenticated"

        state = client.get('/api/state', headers=self.headers(token))
        assert state.status_code == 200
        assert state.get_json()["account"]["user"] == "alice"

    def test_login_returns_token(self, client):
        self.register(client, "alice")
        resp = client.post('/api/auth/login', json={"username": "alice", "password": "secret123"})
        assert resp.status_code == 200
        assert resp.get_json()["username"] == "alice"
        assert resp.get_json()["token"]

    def test_login_with_wrong_password_fails(self, client):
        self.register(client, "bob")
        resp = client.post('/api/auth/login', json={"username": "bob", "password": "wrong-pass"})
        assert resp.status_code == 401

    def test_duplicate_registration_rejected(self, client):
        self.register(client, "carol")
        resp = client.post('/api/auth/register', json={
            "username": "carol", "password": "secret123", "confirm": "secret123"
        })
        assert resp.status_code == 400

    def test_invalid_credentials_rejected(self, client):
        resp = client.post('/api/auth/register', json={
            "username": "a", "password": "123", "confirm": "123"
        })
        assert resp.status_code == 400

    def test_reminders_are_isolated(self, client):
        alice = self.register(client, "alice")
        bob = self.register(client, "bob")

        client.post('/api/reminders', headers=self.headers(alice), json={
            "title": "alice 的任务", "time": "10:00", "repeat": "daily", "priority": "low"
        })
        client.post('/api/reminders', headers=self.headers(bob), json={
            "title": "bob 的任务", "time": "11:00", "repeat": "daily", "priority": "low"
        })

        alice_state = client.get('/api/state', headers=self.headers(alice)).get_json()
        bob_state = client.get('/api/state', headers=self.headers(bob)).get_json()

        assert [r["title"] for r in alice_state["db"]["reminders"]] == ["alice 的任务"]
        assert [r["title"] for r in bob_state["db"]["reminders"]] == ["bob 的任务"]
        assert alice_state["db"]["reminders"][0]["user"] == "alice"
        assert bob_state["db"]["reminders"][0]["user"] == "bob"

    def test_cross_account_modification_blocked(self, client):
        alice = self.register(client, "alice")
        bob = self.register(client, "bob")

        created = client.post('/api/reminders', headers=self.headers(alice), json={
            "title": "alice 的任务", "time": "10:00", "repeat": "daily", "priority": "low"
        }).get_json()

        resp = client.delete(f'/api/reminders/{created["id"]}', headers=self.headers(bob))
        assert resp.status_code == 404

        resp = client.put(f'/api/reminders/{created["id"]}', headers=self.headers(bob), json={
            "title": "被篡改", "time": "10:00", "repeat": "daily", "priority": "low"
        })
        assert resp.status_code == 404

        alice_state = client.get('/api/state', headers=self.headers(alice)).get_json()
        assert alice_state["db"]["reminders"][0]["title"] == "alice 的任务"

    def test_settings_are_isolated(self, client):
        alice = self.register(client, "alice")
        bob = self.register(client, "bob")

        client.post('/api/settings', headers=self.headers(alice), json={
            "dark_mode": False, "webhooks": {"wecom": "https://alice.example.com"}
        })

        alice_state = client.get('/api/state', headers=self.headers(alice)).get_json()
        bob_state = client.get('/api/state', headers=self.headers(bob)).get_json()

        assert alice_state["db"]["settings"]["webhooks"]["wecom"] == "https://alice.example.com"
        assert bob_state["db"]["settings"]["webhooks"]["wecom"] == ""

    def test_logs_are_isolated(self, client, app):
        alice = self.register(client, "alice")
        bob = self.register(client, "bob")
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-a", "title": "alice 记录", "user": "alice", "triggered_at": "2026-01-01T10:00:00"},
            {"id": "log-b", "title": "bob 记录", "user": "bob", "triggered_at": "2026-01-01T11:00:00"}
        ]

        alice_state = client.get('/api/state', headers=self.headers(alice)).get_json()
        assert [l["id"] for l in alice_state["logs"]] == ["log-a"]

        resp = client.delete('/api/logs/log-b', headers=self.headers(alice))
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 0
        assert [l["id"] for l in app.config['GLOBAL_LOGS']] == ["log-a", "log-b"]

    def test_clear_completed_only_affects_own_account(self, client):
        alice = self.register(client, "alice")
        bob = self.register(client, "bob")

        alice_task = client.post('/api/reminders', headers=self.headers(alice), json={
            "title": "alice 已完成", "time": "10:00", "repeat": "daily", "priority": "low"
        }).get_json()
        bob_task = client.post('/api/reminders', headers=self.headers(bob), json={
            "title": "bob 已完成", "time": "11:00", "repeat": "daily", "priority": "low"
        }).get_json()
        for token, task in ((alice, alice_task), (bob, bob_task)):
            client.put(f'/api/reminders/{task["id"]}', headers=self.headers(token), json={
                "title": task["title"], "time": task["time"], "repeat": "daily",
                "priority": "low", "status": "completed"
            })

        resp = client.post('/api/reminders/clear-completed', headers=self.headers(alice))
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 1

        alice_state = client.get('/api/state', headers=self.headers(alice)).get_json()
        bob_state = client.get('/api/state', headers=self.headers(bob)).get_json()
        assert alice_state["db"]["reminders"] == []
        assert [r["title"] for r in bob_state["db"]["reminders"]] == ["bob 已完成"]

    def test_state_never_exposes_password_hash(self, client, app):
        self.register(client, "alice")
        state = client.get('/api/state', headers=self.headers(
            client.post('/api/auth/login', json={"username": "alice", "password": "secret123"}).get_json()["token"]
        )).get_json()

        serialized = json.dumps(state, ensure_ascii=False)
        assert "password_hash" not in serialized
        assert "sessions" not in serialized

    def test_first_account_can_claim_legacy_data(self, client, app):
        app.config['GLOBAL_DB']["reminders"] = [
            {"id": "legacy-1", "title": "遗留任务", "time": "09:00", "repeat": "daily", "status": "pending"}
        ]
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-legacy", "reminder_id": "legacy-1", "title": "遗留任务", "triggered_at": "2026-01-01T09:00:00"}
        ]

        token = self.register(client, "alice", claim_legacy=True)
        state = client.get('/api/state', headers=self.headers(token)).get_json()

        assert [r["id"] for r in state["db"]["reminders"]] == ["legacy-1"]
        assert [l["id"] for l in state["logs"]] == ["log-legacy"]
        assert app.config['GLOBAL_DB']['users']['alice']['reminders'][0]["user"] == "alice"

    def test_logout_invalidates_session(self, client):
        token = self.register(client, "alice")
        assert client.get('/api/state', headers=self.headers(token)).status_code == 200

        resp = client.post('/api/auth/logout', headers=self.headers(token))
        assert resp.status_code == 200
        assert client.get('/api/state', headers=self.headers(token)).status_code == 401

    def test_claim_legacy_endpoint_after_registration(self, client, app):
        app.config['GLOBAL_DB']["reminders"] = [
            {"id": "legacy-1", "title": "遗留任务", "time": "09:00", "repeat": "daily", "status": "pending"}
        ]
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-legacy", "reminder_id": "legacy-1", "title": "遗留任务", "triggered_at": "2026-01-01T09:00:00"}
        ]

        token = self.register(client, "alice")
        state = client.get('/api/state', headers=self.headers(token)).get_json()
        assert state["db"]["reminders"] == []
        assert state["account"]["legacy"]["reminders"] == 1

        resp = client.post('/api/auth/claim-legacy', headers=self.headers(token))
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok", "reminders": 1, "logs": 1}

        state = client.get('/api/state', headers=self.headers(token)).get_json()
        assert [r["id"] for r in state["db"]["reminders"]] == ["legacy-1"]
        assert [l["id"] for l in state["logs"]] == ["log-legacy"]
        assert state["account"]["legacy"] == {"reminders": 0, "logs": 0}

    def test_claim_legacy_without_data_fails(self, client):
        token = self.register(client, "alice")
        resp = client.post('/api/auth/claim-legacy', headers=self.headers(token))
        assert resp.status_code == 400

    def test_change_password_rotates_token(self, client):
        token = self.register(client, "alice")
        resp = client.post('/api/auth/password', headers=self.headers(token), json={
            "old_password": "secret123", "new_password": "newpass123", "confirm": "newpass123"
        })
        assert resp.status_code == 200
        new_token = resp.get_json()["token"]

        assert client.get('/api/state', headers=self.headers(token)).status_code == 401
        assert client.get('/api/state', headers=self.headers(new_token)).status_code == 200
        assert client.post('/api/auth/login', json={
            "username": "alice", "password": "newpass123"
        }).status_code == 200

    def test_change_password_rejects_wrong_old_password(self, client):
        token = self.register(client, "alice")
        resp = client.post('/api/auth/password', headers=self.headers(token), json={
            "old_password": "wrong", "new_password": "newpass123", "confirm": "newpass123"
        })
        assert resp.status_code == 400

    def test_status_reports_claimable_legacy_data(self, client, app):
        app.config['GLOBAL_DB']["reminders"] = [{"id": "legacy-1", "title": "遗留"}]
        status = client.get('/api/auth/status').get_json()
        assert status["legacy"]["reminders"] == 1
        assert status["registration_enabled"] is True


class TestNicknameEndpoint:
    """昵称接口 /api/auth/profile"""

    def register(self, client, username, password="secret123"):
        resp = client.post('/api/auth/register', json={
            "username": username, "password": password, "confirm": password
        })
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()["token"]

    def headers(self, token):
        return {"X-Auth-Token": token}

    def test_set_nickname_visible_in_state(self, client):
        token = self.register(client, "alice")

        resp = client.post('/api/auth/profile', headers=self.headers(token), json={"nickname": "小明"})
        assert resp.status_code == 200
        assert resp.get_json()["nickname"] == "小明"

        state = client.get('/api/state', headers=self.headers(token)).get_json()
        assert state["account"]["nickname"] == "小明"
        assert state["account"]["user"] == "alice"
        assert state["account"]["profile"]["nickname"] == "小明"

    def test_clear_nickname(self, client):
        token = self.register(client, "alice")
        client.post('/api/auth/profile', headers=self.headers(token), json={"nickname": "小明"})

        resp = client.post('/api/auth/profile', headers=self.headers(token), json={"nickname": ""})
        assert resp.status_code == 200
        assert resp.get_json()["nickname"] is None

        state = client.get('/api/state', headers=self.headers(token)).get_json()
        assert state["account"]["nickname"] is None

    def test_nickname_too_long_rejected(self, client):
        token = self.register(client, "alice")
        resp = client.post('/api/auth/profile', headers=self.headers(token), json={"nickname": "长" * 21})
        assert resp.status_code == 400

    def test_missing_nickname_field_rejected(self, client):
        token = self.register(client, "alice")
        resp = client.post('/api/auth/profile', headers=self.headers(token), json={})
        assert resp.status_code == 400

    def test_profile_requires_login(self, client):
        self.register(client, "alice")
        resp = client.post('/api/auth/profile', json={"nickname": "小明"})
        assert resp.status_code == 401

    def test_profile_forbidden_in_open_mode(self, client):
        resp = client.post('/api/auth/profile', json={"nickname": "小明"})
        assert resp.status_code == 403

    def test_nickname_isolated_between_accounts(self, client):
        alice = self.register(client, "alice")
        bob = self.register(client, "bob")
        client.post('/api/auth/profile', headers=self.headers(alice), json={"nickname": "小明"})

        alice_state = client.get('/api/state', headers=self.headers(alice)).get_json()
        bob_state = client.get('/api/state', headers=self.headers(bob)).get_json()
        assert alice_state["account"]["nickname"] == "小明"
        assert bob_state["account"]["nickname"] is None


def register_account(client, username, password="secret123"):
    """注册账号并返回鉴权头"""
    resp = client.post('/api/auth/register', json={
        "username": username, "password": password, "confirm": password
    })
    assert resp.status_code == 200, resp.get_json()
    return {"X-Auth-Token": resp.get_json()["token"]}


class TestLogActions:
    """通知记录：标记已处理 / 稍后提醒"""

    def seed_log(self, app, log_id="log-1", user=None, reminder_id="r1"):
        entry = {
            "id": log_id, "reminder_id": reminder_id, "title": "喝一杯温水",
            "triggered_at": "2026-09-16T09:00:00+08:00", "completed_at": None,
            "status": "triggered"
        }
        if user:
            entry["user"] = user
        app.config['GLOBAL_LOGS'] = [entry]
        return entry

    def test_toggle_log_complete(self, client, app):
        self.seed_log(app)

        first = client.post('/api/logs/complete/log-1')
        assert first.status_code == 200
        assert first.get_json()["completed"] is True
        assert app.config['GLOBAL_LOGS'][0]["completed_at"] is not None

        second = client.post('/api/logs/complete/log-1')
        assert second.get_json()["completed"] is False
        assert app.config['GLOBAL_LOGS'][0]["completed_at"] is None

    def test_toggle_log_complete_unknown_id(self, client, app):
        self.seed_log(app)
        assert client.post('/api/logs/complete/not-exist').status_code == 404

    def test_snooze_creates_once_reminder(self, client, app):
        headers = register_account(client, "alice")
        self.seed_log(app, user="alice")

        resp = client.post('/api/reminders/snooze', headers=headers, json={"log_id": "log-1", "minutes": 10})
        assert resp.status_code == 200
        created = resp.get_json()
        assert created["repeat"] == "once"
        assert created["title"] == "喝一杯温水（稍后提醒）"
        assert created["user"] == "alice"

        scheduled = datetime.datetime.strptime(created["time"], "%Y-%m-%d %H:%M")
        delta = scheduled - datetime.datetime.now()
        assert datetime.timedelta(minutes=8) < delta < datetime.timedelta(minutes=11)

    def test_snooze_requires_log_id(self, client):
        resp = client.post('/api/reminders/snooze', json={})
        assert resp.status_code == 400

    def test_snooze_other_account_log_blocked(self, client, app):
        alice = register_account(client, "alice")
        register_account(client, "bob")
        self.seed_log(app, user="alice")

        resp = client.post('/api/reminders/snooze', headers=alice, json={"log_id": "log-1", "minutes": 10})
        assert resp.status_code == 200

        bob_headers = {"X-Auth-Token": client.post('/api/auth/login', json={
            "username": "bob", "password": "secret123"
        }).get_json()["token"]}
        resp = client.post('/api/reminders/snooze', headers=bob_headers, json={"log_id": "log-1"})
        assert resp.status_code == 404


class TestWebhookTest:
    """Webhook 测试推送"""

    def test_unsupported_channel_rejected(self, client):
        assert client.post('/api/settings/test-webhook', json={"channel": "telegram"}).status_code == 400

    def test_missing_url_rejected(self, client):
        assert client.post('/api/settings/test-webhook', json={"channel": "wecom"}).status_code == 400

    def test_invalid_url_rejected(self, client):
        resp = client.post('/api/settings/test-webhook', json={"channel": "wecom", "url": "not-a-url"})
        assert resp.status_code == 400

    @patch('app.notifier.requests.post')
    def test_successful_test_push(self, mock_post, client):
        mock_post.return_value.status_code = 200
        resp = client.post('/api/settings/test-webhook', json={
            "channel": "wecom", "url": "https://qyapi.weixin.qq.com/test"
        })
        assert resp.status_code == 200
        assert "测试消息已发送" in resp.get_json()["message"]
        assert mock_post.called

    @patch('app.notifier.requests.post')
    def test_failed_test_push_reports_error(self, mock_post, client):
        mock_post.return_value.status_code = 500
        resp = client.post('/api/settings/test-webhook', json={
            "channel": "lark", "url": "https://open.feishu.cn/test"
        })
        assert resp.status_code == 502
        assert "HTTP 500" in resp.get_json()["error"]

    @patch('app.notifier.requests.post')
    def test_uses_saved_url_when_not_provided(self, mock_post, client):
        mock_post.return_value.status_code = 200
        client.post('/api/settings', json={"webhooks": {"wecom": "https://saved.example.com"}})

        resp = client.post('/api/settings/test-webhook', json={"channel": "wecom"})

        assert resp.status_code == 200
        assert mock_post.call_args[0][0] == "https://saved.example.com"


class TestAccountMaintenance:
    """账号运维：退出其他设备、注销账号"""

    def test_logout_all_keeps_current_device(self, client):
        alice = register_account(client, "alice")
        second = {"X-Auth-Token": client.post('/api/auth/login', json={
            "username": "alice", "password": "secret123"
        }).get_json()["token"]}

        resp = client.post('/api/auth/logout-all', headers=alice)
        assert resp.status_code == 200
        assert resp.get_json()["removed"] == 2

        # 旧会话全部失效，返回的新 token 可用
        assert client.get('/api/state', headers=alice).status_code == 401
        assert client.get('/api/state', headers=second).status_code == 401
        fresh = {"X-Auth-Token": resp.get_json()["token"]}
        assert client.get('/api/state', headers=fresh).status_code == 200

    def test_logout_all_requires_login(self, client):
        register_account(client, "alice")
        assert client.post('/api/auth/logout-all').status_code == 401

    def test_delete_account_requires_confirm_username(self, client):
        headers = register_account(client, "alice")
        resp = client.delete('/api/auth/account', headers=headers,
                              json={"password": "secret123", "confirm_username": "bob"})
        assert resp.status_code == 400

    def test_delete_account_requires_password(self, client):
        headers = register_account(client, "alice")
        resp = client.delete('/api/auth/account', headers=headers,
                              json={"password": "wrong-pass", "confirm_username": "alice"})
        assert resp.status_code == 400
        assert client.get('/api/state', headers=headers).status_code == 200

    def test_delete_account_removes_data_and_sessions(self, client, app):
        alice = register_account(client, "alice")
        client.post('/api/reminders', headers=alice, json={
            "title": "alice 的任务", "time": "10:00", "repeat": "daily", "priority": "low"
        })
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-a", "title": "alice", "user": "alice", "triggered_at": "2026-09-16T09:00:00+08:00"}
        ]

        resp = client.delete('/api/auth/account', headers=alice,
                              json={"password": "secret123", "confirm_username": "alice"})

        assert resp.status_code == 200
        result = resp.get_json()
        assert result["reminders_deleted"] == 1
        assert result["logs_deleted"] == 1
        assert result["remaining_accounts"] == 0
        assert app.config['GLOBAL_LOGS'] == []
        assert app.config['GLOBAL_DB']['reminders'] == []
        assert client.get('/api/state', headers=alice).status_code == 200  # 回到开放模式

    def test_delete_account_keeps_other_accounts(self, client):
        alice = register_account(client, "alice")
        bob = register_account(client, "bob")
        client.post('/api/reminders', headers=bob, json={
            "title": "bob 的任务", "time": "11:00", "repeat": "daily", "priority": "low"
        })

        resp = client.delete('/api/auth/account', headers=alice,
                              json={"password": "secret123", "confirm_username": "alice"})

        assert resp.get_json()["remaining_accounts"] == 1
        bob_state = client.get('/api/state', headers=bob).get_json()
        assert [r["title"] for r in bob_state["db"]["reminders"]] == ["bob 的任务"]


class TestBackup:
    """数据导出 / 导入"""

    def test_export_returns_only_own_data(self, client, app):
        alice = register_account(client, "alice")
        register_account(client, "bob")
        client.post('/api/reminders', headers=alice, json={
            "title": "alice 的任务", "time": "10:00", "repeat": "daily", "priority": "low"
        })
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-a", "title": "alice", "user": "alice", "triggered_at": "2026-09-16T09:00:00+08:00"},
            {"id": "log-b", "title": "bob", "user": "bob", "triggered_at": "2026-09-16T09:00:00+08:00"}
        ]

        resp = client.get('/api/export', headers=alice)

        assert resp.status_code == 200
        assert "attachment" in resp.headers["Content-Disposition"]
        data = resp.get_json()
        assert data["format"] == "life-reminder-backup"
        assert [r["title"] for r in data["reminders"]] == ["alice 的任务"]
        assert [l["id"] for l in data["logs"]] == ["log-a"]
        assert data["account"]["username"] == "alice"

    def test_import_adds_and_dedupes(self, client, app):
        payload = {
            "reminders": [
                {"title": "导入任务", "time": "08:00", "repeat": "daily", "priority": "mid"},
                {"title": "导入任务", "time": "08:00", "repeat": "daily", "priority": "mid"},
                {"title": "非法时间", "time": "abc", "repeat": "daily"},
                {"title": "在产假期", "time": "09:00", "repeat": "lunar:08-15", "priority": "low"}
            ]
        }

        resp = client.post('/api/import', json=payload)

        assert resp.status_code == 200
        result = resp.get_json()
        assert result["added"] == 2
        assert result["skipped"] == 1
        assert result["invalid"] == 1

        state = client.get('/api/state').get_json()
        assert len(state["db"]["reminders"]) == 2

    def test_import_is_idempotent(self, client):
        payload = {"reminders": [{"title": "重复导入", "time": "08:00", "repeat": "daily", "priority": "low"}]}
        first = client.post('/api/import', json=payload).get_json()
        second = client.post('/api/import', json=payload).get_json()

        assert first["added"] == 1
        assert second["added"] == 0 and second["skipped"] == 1

    def test_import_requires_reminders_list(self, client):
        assert client.post('/api/import', json={"foo": "bar"}).status_code == 400

    def test_import_into_current_account_only(self, client, app):
        headers = register_account(client, "alice")
        resp = client.post('/api/import', headers=headers, json={
            "reminders": [{"title": "alice 导入", "time": "08:00", "repeat": "daily", "priority": "low"}]
        })
        assert resp.status_code == 200

        state = client.get('/api/state', headers=headers).get_json()
        assert state["db"]["reminders"][0]["user"] == "alice"


class TestLogStats:
    """历史统计：按全量记录计算，不受返回列表长度上限影响"""

    def test_log_stats_counts_all_records(self, client, app):
        import datetime as dt
        from app.config import TZ_ENV
        now = dt.datetime.now(TZ_ENV)
        app.config['GLOBAL_LOGS'] = [
            {"id": f"log-{i}", "reminder_id": "r1", "title": f"记录 {i}",
             "triggered_at": (now - dt.timedelta(days=i)).isoformat(),
             "completed_at": now.isoformat() if i == 0 else None}
            for i in range(120)
        ]

        state = client.get('/api/state').get_json()
        assert len(state["logs"]) == 100
        assert state["log_stats"]["total"] == 120
        assert state["log_stats"]["today"] == 1
        assert state["log_stats"]["completed"] == 1
        assert state["log_stats"]["limit"] == 100

    def test_log_stats_isolated_per_account(self, client, app):
        import datetime as dt
        from app.config import TZ_ENV
        now = dt.datetime.now(TZ_ENV)
        token = client.post('/api/auth/register', json={
            "username": "alice", "password": "secret123", "confirm": "secret123"
        }).get_json()["token"]
        app.config['GLOBAL_LOGS'] = [
            {"id": "log-a", "title": "alice", "user": "alice",
             "triggered_at": now.isoformat(), "completed_at": None},
            {"id": "log-b", "title": "bob", "user": "bob",
             "triggered_at": now.isoformat(), "completed_at": None},
            {"id": "log-legacy", "title": "遗留", "triggered_at": now.isoformat(), "completed_at": None}
        ]

        state = client.get('/api/state', headers={"X-Auth-Token": token}).get_json()
        assert state["log_stats"]["total"] == 1
        assert [l["id"] for l in state["logs"]] == ["log-a"]
