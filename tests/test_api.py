"""API endpoint tests"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import tempfile
from unittest.mock import MagicMock, patch
import pytest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["TZ"] = "Asia/Shanghai"
os.environ["API_KEY"] = ""

from flask import Flask
from flask_cors import CORS
from app.api import register_routes


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


class TestAuth:
    @patch('app.auth.API_KEY', 'test-key-123')
    def test_api_key_required(self, client):
        from app.auth import API_KEY as auth_key
        assert auth_key == 'test-key-123'


class TestWxLogin:
    def test_missing_code_fails(self, client):
        resp = client.post('/api/wxlogin', json={})
        assert resp.status_code == 400

    def test_missing_env_config_fails(self, client):
        resp = client.post('/api/wxlogin', json={"code": "test-code"})
        assert resp.status_code == 400
