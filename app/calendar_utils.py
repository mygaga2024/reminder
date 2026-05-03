import datetime
from app.config import CHINESE_CALENDAR_AVAILABLE, chinese_calendar


def is_china_workday(check_date: datetime.date = None) -> bool:
    """检查指定日期是否为工作日（考虑中国法定节假日）"""
    if check_date is None:
        check_date = datetime.date.today()

    if not CHINESE_CALENDAR_AVAILABLE:
        return check_date.weekday() < 5

    try:
        return chinese_calendar.is_workday(check_date)
    except Exception:
        return check_date.weekday() < 5


def get_next_workday(from_date: datetime.date = None) -> datetime.date:
    """获取下一个工作日"""
    if from_date is None:
        from_date = datetime.date.today()

    if not CHINESE_CALENDAR_AVAILABLE:
        current = from_date
        while current.weekday() >= 5:
            current += datetime.timedelta(days=1)
        return current

    try:
        return chinese_calendar.get_next_workday(from_date)
    except Exception:
        current = from_date
        while True:
            current += datetime.timedelta(days=1)
            if current.weekday() < 5:
                return current
