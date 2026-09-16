"""调度器测试（_build_trigger 触发器构建 + update_scheduler 任务注册）"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.config import TZ_ENV
from app.scheduler import _build_trigger, update_scheduler


class FakeScheduler:
    """轻量调度器替身：记录注册的 job，避免在测试中启动真实后台线程"""

    def __init__(self):
        self.jobs = {}
        self.running = False

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_all_jobs(self):
        self.jobs.clear()

    def add_job(self, func, trigger, args=None, id=None):
        self.jobs[id] = {"func": func, "trigger": trigger, "args": args}

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.jobs.pop(job_id)

    def start(self):
        self.running = True


def next_run_time(trigger):
    """取触发器最近一次执行时间（基于固定参考时间，结果稳定）"""
    reference = datetime.datetime(2026, 9, 16, 12, 0, tzinfo=TZ_ENV)
    return trigger.get_next_fire_time(None, reference)


class TestBuildTrigger:
    def test_daily_uses_cron(self):
        trigger = _build_trigger("07:30", "daily")
        assert isinstance(trigger, CronTrigger)
        assert str(trigger) == "cron[hour='7', minute='30']"

    def test_workday_uses_weekday_filter(self):
        trigger = _build_trigger("09:45", "workday")
        assert isinstance(trigger, CronTrigger)
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields["day_of_week"] == "mon-fri"

    def test_weekly_uses_selected_days(self):
        trigger = _build_trigger("20:00", "weekly:sat,sun")
        assert isinstance(trigger, CronTrigger)
        fields = {f.name: str(f) for f in trigger.fields}
        assert "sat" in fields["day_of_week"] and "sun" in fields["day_of_week"]

    def test_once_with_future_datetime(self):
        trigger = _build_trigger("2099-01-02 08:15", "once")
        assert isinstance(trigger, DateTrigger)
        assert trigger.run_date.strftime("%Y-%m-%d %H:%M") == "2099-01-02 08:15"

    def test_once_with_past_datetime_shifts_one_day(self):
        trigger = _build_trigger("2020-01-02 08:15", "once")
        assert isinstance(trigger, DateTrigger)
        expected = datetime.datetime(2020, 1, 3, 8, 15, tzinfo=TZ_ENV)
        assert trigger.run_date == expected

    def test_time_only_without_repeat_fires_once(self):
        trigger = _build_trigger("23:59", "none")
        assert isinstance(trigger, DateTrigger)
        assert trigger.run_date.tzinfo is not None

    def test_invalid_time_returns_none(self):
        assert _build_trigger("", "daily") is None
        assert _build_trigger("不是时间", "daily") is None
        assert _build_trigger("25:00", "daily") is None

    def test_trigger_is_timezone_aware(self):
        trigger = _build_trigger("2099-01-02 08:15", "once")
        assert trigger.run_date.utcoffset() == datetime.timedelta(hours=8)


class TestUpdateScheduler:
    def make_db(self):
        return {
            "reminders": [
                {"id": "r1", "title": "每日任务", "time": "07:30", "repeat": "daily", "status": "pending"},
                {"id": "r2", "title": "已完成任务", "time": "08:00", "repeat": "daily", "status": "completed"},
                {"id": "r3", "title": "一次性任务", "time": "2099-01-02 08:15", "repeat": "once", "status": "pending"},
                {"id": "r4", "title": "缺少时间", "time": "", "repeat": "daily", "status": "pending"},
                {"id": "r5", "title": "非法时间", "time": "不是时间", "repeat": "daily", "status": "pending"}
            ],
            "settings": {"webhooks": {}},
            "users": {}
        }

    def test_only_valid_pending_reminders_are_scheduled(self):
        scheduler = FakeScheduler()
        update_scheduler(scheduler, self.make_db(), lambda r: None)

        assert set(scheduler.jobs.keys()) == {"r1", "r3"}
        assert scheduler.running is True

    def test_rebuild_clears_previous_jobs(self):
        scheduler = FakeScheduler()
        db = self.make_db()
        update_scheduler(scheduler, db, lambda r: None)

        db["reminders"] = [{"id": "r9", "title": "新任务", "time": "10:00", "repeat": "daily", "status": "pending"}]
        update_scheduler(scheduler, db, lambda r: None)

        assert set(scheduler.jobs.keys()) == {"r9"}

    def test_single_broken_reminder_does_not_stop_others(self):
        scheduler = FakeScheduler()
        db = self.make_db()
        db["reminders"].append({"id": "r6", "title": "异常任务", "time": "07:00", "status": "pending"})

        update_scheduler(scheduler, db, lambda r: None)

        assert "r1" in scheduler.jobs
