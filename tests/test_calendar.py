"""Calendar utilities tests"""
import datetime
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.calendar_utils import is_china_workday, get_next_workday


class TestIsChinaWorkday:
    def test_monday_is_workday(self):
        dt = datetime.date(2024, 1, 15)
        assert dt.weekday() == 0
        result = is_china_workday(dt)
        assert result is True

    def test_saturday_is_not_workday(self):
        dt = datetime.date(2024, 1, 13)
        assert dt.weekday() == 5
        result = is_china_workday(dt)
        assert result is False

    def test_sunday_is_not_workday(self):
        dt = datetime.date(2024, 1, 14)
        assert dt.weekday() == 6
        result = is_china_workday(dt)
        assert result is False

    def test_defaults_to_today(self):
        result = is_china_workday()
        assert isinstance(result, bool)

    def test_year_2100_leap_boundary(self):
        """2100年不是闰年，确保日期可以正常处理"""
        feb28 = datetime.date(2100, 2, 28)
        mar01 = datetime.date(2100, 3, 1)
        assert feb28 + datetime.timedelta(days=1) == mar01
        assert is_china_workday(mar01) is True


class TestGetNextWorkday:
    def test_from_friday_returns_monday(self):
        friday = datetime.date(2024, 1, 12)
        assert friday.weekday() == 4
        next_wd = get_next_workday(friday)
        assert next_wd == datetime.date(2024, 1, 15)

    def test_from_saturday_returns_monday(self):
        saturday = datetime.date(2024, 1, 13)
        next_wd = get_next_workday(saturday)
        assert next_wd == datetime.date(2024, 1, 15)

    def test_from_workday_returns_tomorrow(self):
        monday = datetime.date(2024, 1, 15)
        next_wd = get_next_workday(monday)
        assert next_wd == datetime.date(2024, 1, 16)

    def test_returns_date_type(self):
        result = get_next_workday()
        assert isinstance(result, datetime.date)
