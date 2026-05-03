"""Notifier engine tests"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
from unittest.mock import MagicMock, patch, call
from app.notifier import notify_engine, _send_generic_webhook
from app.calendar_utils import is_china_workday


class TestNotifyEngine:
    def make_reminder(self, **overrides):
        defaults = {
            "id": "test-reminder-1",
            "title": "测试提醒",
            "time": "10:00",
            "repeat": "daily",
            "status": "pending"
        }
        defaults.update(overrides)
        return defaults

    def make_db(self, webhooks=None):
        if webhooks is None:
            webhooks = {"wecom": "", "dingtalk": "", "lark": ""}
        return {"settings": {"webhooks": webhooks}, "reminders": []}

    @patch('app.notifier.requests.post')
    def test_notify_sends_wecom(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {}
        db = self.make_db({"wecom": "https://qyapi.weixin.qq.com/test", "dingtalk": "", "lark": ""})
        logs = []
        scheduler = MagicMock()

        notify_engine(self.make_reminder(), db, logs, scheduler)

        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://qyapi.weixin.qq.com/test"
        assert call_args[1]["json"]["msgtype"] == "text"

    @patch('app.notifier.requests.post')
    def test_notify_sends_lark_format(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {}
        db = self.make_db({"wecom": "", "dingtalk": "", "lark": "https://open.feishu.cn/test"})
        logs = []

        notify_engine(self.make_reminder(), db, logs, MagicMock())

        assert mock_post.called
        call_args = mock_post.call_args
        assert "msg_type" in call_args[1]["json"]

    @patch('app.notifier.requests.post')
    def test_notify_skips_empty_webhooks(self, mock_post):
        db = self.make_db({"wecom": "", "dingtalk": "", "lark": ""})
        logs = []

        notify_engine(self.make_reminder(), db, logs, MagicMock())

        assert not mock_post.called

    def test_notify_creates_log_entry(self):
        db = self.make_db({"wecom": "", "dingtalk": "", "lark": ""})
        logs = []
        notify_engine(self.make_reminder(), db, logs, MagicMock())
        assert len(logs) == 1
        assert logs[0]["status"] == "triggered"
        assert logs[0]["title"] == "测试提醒"

    @patch('app.notifier.requests.post')
    def test_notify_with_sms_voice_webhooks(self, mock_post):
        mock_post.return_value.status_code = 200
        db = self.make_db({
            "sms_phone": "+8613800138000",
            "sms_api": "https://sms.example.com/api",
            "voice_api": "https://voice.example.com/api"
        })
        logs = []

        notify_engine(self.make_reminder(), db, logs, MagicMock())

        assert mock_post.call_count == 3  # sms_phone, sms_api, voice_api

    @patch('app.notifier.is_china_workday')
    def test_workday_reminder_skipped_on_holiday(self, mock_is_workday):
        mock_is_workday.return_value = False
        db = self.make_db({"wecom": "", "dingtalk": "", "lark": ""})
        logs = []

        notify_engine(self.make_reminder(repeat="workday"), db, logs, MagicMock())

        assert len(logs) == 0

    @patch('app.notifier.is_china_workday')
    def test_workday_reminder_fires_on_workday(self, mock_is_workday):
        mock_is_workday.return_value = True
        db = self.make_db({"wecom": "", "dingtalk": "", "lark": ""})
        logs = []

        notify_engine(self.make_reminder(repeat="workday"), db, logs, MagicMock())

        assert len(logs) == 1

    def test_once_reminder_auto_deletes(self):
        db = self.make_db({"wecom": "", "dingtalk": "", "lark": ""})
        db["reminders"] = [self.make_reminder(repeat="once")]
        logs = []
        scheduler = MagicMock()

        notify_engine(self.make_reminder(repeat="once"), db, logs, scheduler)

        assert len(db["reminders"]) == 0
        scheduler.remove_job.assert_called_once_with("test-reminder-1")


class TestGenericWebhook:
    @patch('app.notifier.requests.post')
    def test_sms_api_webhook(self, mock_post):
        mock_post.return_value.status_code = 200
        _send_generic_webhook("sms_api", "https://sms.example.com/api", "提醒标题", "消息内容")
        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args[1]["json"]["channel"] == "sms_api"

    @patch('app.notifier.requests.post')
    def test_generic_webhook_handles_network_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.ConnectionError("Connection refused")
        _send_generic_webhook("sms_api", "https://invalid.example.com", "title", "msg")
