"""Notifier engine tests"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
from unittest.mock import MagicMock, patch, call
from app.notifier import notify_engine, _send_generic_webhook
from app.notifier import _prune_logs, _repeat_label
from app.calendar_utils import is_china_workday
from app.config import TZ_ENV
from app import lunar_utils


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


class TestMultiAccountNotify:
    """多账号：Webhook 与日志按提醒归属账号隔离"""

    def make_db(self):
        return {
            "reminders": [],
            "settings": {"webhooks": {"wecom": "https://legacy.example.com", "dingtalk": "", "lark": ""}},
            "users": {
                "alice": {
                    "username": "alice",
                    "reminders": [],
                    "settings": {"webhooks": {"wecom": "https://alice.example.com", "dingtalk": "", "lark": ""}}
                }
            }
        }

    def make_reminder(self, **overrides):
        defaults = {
            "id": "reminder-alice-1",
            "title": "alice 的提醒",
            "time": "10:00",
            "repeat": "daily",
            "status": "pending",
            "user": "alice"
        }
        defaults.update(overrides)
        return defaults

    @patch('app.notifier.requests.post')
    def test_uses_owner_webhooks(self, mock_post):
        mock_post.return_value.status_code = 200
        db = self.make_db()

        notify_engine(self.make_reminder(), db, [], MagicMock())

        assert mock_post.called
        assert mock_post.call_args[0][0] == "https://alice.example.com"

    @patch('app.notifier.requests.post')
    def test_falls_back_to_top_level_webhooks(self, mock_post):
        mock_post.return_value.status_code = 200
        db = self.make_db()

        notify_engine(self.make_reminder(user=None), db, [], MagicMock())

        assert mock_post.called
        assert mock_post.call_args[0][0] == "https://legacy.example.com"

    def test_log_entry_records_owner(self):
        db = self.make_db()
        logs = []

        notify_engine(self.make_reminder(), db, logs, MagicMock())

        assert logs[0]["user"] == "alice"

    def test_once_reminder_removed_from_owner_scope(self):
        db = self.make_db()
        reminder = self.make_reminder(repeat="once")
        db["users"]["alice"]["reminders"] = [reminder]
        db["reminders"] = [reminder]
        scheduler = MagicMock()

        notify_engine(reminder, db, [], scheduler)

        assert db["users"]["alice"]["reminders"] == []
        assert db["reminders"] == []
        scheduler.remove_job.assert_called_once_with("reminder-alice-1")


class TestRepeatLabel:
    """通知消息里的重复类型文案（历史实现对 weekly 会误显示为每天）"""

    def test_label_mapping(self):
        assert _repeat_label("daily") == "每天"
        assert _repeat_label("workday") == "工作日"
        assert _repeat_label("once") == "一次性"
        assert _repeat_label("yearly") == "每年"
        assert _repeat_label("weekly:mon,wed") == "每周"
        assert _repeat_label("monthly:15") == "每月15日"
        assert _repeat_label("monthly:last") == "每月最后一天"
        assert _repeat_label("lunar:08-15") == "每年（农历八月十五）"

    def make_db(self):
        return {
            "settings": {"webhooks": {"wecom": "https://qyapi.weixin.qq.com/test"}},
            "reminders": [],
            "users": {}
        }

    @patch('app.notifier.requests.post')
    def capture_message(self, mock_post, repeat):
        mock_post.return_value.status_code = 200
        notify_engine(
            {"id": "r1", "title": "文案测试", "time": "10:00", "repeat": repeat},
            self.make_db(), [], MagicMock()
        )
        return mock_post.call_args[1]["json"]["text"]["content"]

    def test_weekly_label(self):
        assert "重复类型：每周" in self.capture_message(repeat="weekly:mon,wed")

    def test_monthly_label(self):
        assert "重复类型：每月15日" in self.capture_message(repeat="monthly:15")
        assert "重复类型：每月最后一天" in self.capture_message(repeat="monthly:last")

    def test_yearly_label(self):
        assert "重复类型：每年" in self.capture_message(repeat="yearly")


class TestLunarNotify:
    """农历纪念日只在当天推送"""

    def make_db(self):
        return {"settings": {"webhooks": {}}, "reminders": [], "users": {}}

    def test_fires_on_lunar_anniversary(self):
        if not lunar_utils.LUNAR_AVAILABLE:
            pytest.skip("未安装 lunar_python")
        month, day = lunar_utils.solar_to_lunar(datetime.date.today())
        reminder = {
            "id": "r1", "title": "农历今天", "time": "10:00",
            "repeat": lunar_utils.build_lunar_repeat(month, day)
        }
        logs = []

        notify_engine(reminder, self.make_db(), logs, MagicMock())

        assert len(logs) == 1

    def test_skipped_on_other_days(self):
        if not lunar_utils.LUNAR_AVAILABLE:
            pytest.skip("未安装 lunar_python")
        month, day = lunar_utils.solar_to_lunar(datetime.date.today())
        other_day = 2 if day == 1 else 1
        reminder = {
            "id": "r1", "title": "农历非今天", "time": "10:00",
            "repeat": lunar_utils.build_lunar_repeat(month, other_day)
        }
        logs = []

        notify_engine(reminder, self.make_db(), logs, MagicMock())

        assert logs == []


class TestLogRetention:
    """通知记录保留期清理（兼容历史无时区数据）"""

    def make_now(self):
        return datetime.datetime(2026, 9, 16, 12, 0, tzinfo=TZ_ENV)

    def test_recent_records_are_kept(self):
        now = self.make_now()
        logs = [
            {"id": "new", "triggered_at": (now - datetime.timedelta(days=3)).isoformat()},
            {"id": "old", "triggered_at": (now - datetime.timedelta(days=40)).isoformat()},
        ]

        kept = _prune_logs(logs, now)

        assert [l["id"] for l in kept] == ["new"]

    def test_legacy_naive_timestamp_is_pruned_correctly(self):
        now = self.make_now()
        logs = [
            {"id": "legacy-old", "triggered_at": "2026-01-05T09:00:00.123456"},
            {"id": "legacy-new", "triggered_at": "2026-09-15T09:00:00.123456"},
        ]

        kept = _prune_logs(logs, now)

        assert [l["id"] for l in kept] == ["legacy-new"]

    def test_unparsable_timestamp_is_kept(self):
        now = self.make_now()
        logs = [{"id": "broken", "triggered_at": "未知时间"}, {"id": "missing"}]

        kept = _prune_logs(logs, now)

        assert [l["id"] for l in kept] == ["broken", "missing"]

    def test_notify_engine_writes_timezone_aware_timestamp(self):
        db = {"settings": {"webhooks": {}}, "reminders": [], "users": {}}
        logs = []

        notify_engine({"id": "r1", "title": "时区测试", "time": "10:00", "repeat": "daily"}, db, logs, MagicMock())

        parsed = datetime.datetime.fromisoformat(logs[0]["triggered_at"])
        assert parsed.tzinfo is not None
