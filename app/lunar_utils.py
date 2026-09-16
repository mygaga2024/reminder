"""农历转换工具（农历生日 / 纪念日提醒）

实现说明：
- 使用 lunar_python（与前端 lunar-javascript 同源算法），保证前后端农历口径一致
- 未安装该库时优雅降级：LUNAR_AVAILABLE=False，农历相关接口返回空值
- 闰月约定与库一致：月份为负数表示闰月（如 -6 表示闰六月）

本模块只做纯计算，不涉及 HTTP / 调度 / 持久化。
"""
import datetime
import re

from app.config import logger

try:
    from lunar_python import Lunar, Solar
    LUNAR_AVAILABLE = True
except ImportError:
    Lunar = None
    Solar = None
    LUNAR_AVAILABLE = False

LUNAR_MONTH_NAMES = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
LUNAR_DAY_NAMES = [
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"
]

# lunar:MM-DD（闰月月份为负数，如 lunar:-06-01 表示闰六月初一）
LUNAR_REPEAT_PATTERN = re.compile(r'^lunar:(-?\d{1,2})-(\d{1,2})$')


def build_lunar_repeat(month: int, day: int) -> str:
    """构造 lunar:MM-DD 重复模式字符串（闰月传负数月份）"""
    if month > 0:
        return f"lunar:{month:02d}-{day:02d}"
    return f"lunar:-{abs(month):02d}-{day:02d}"


def parse_lunar_repeat(repeat: str):
    """解析 lunar:MM-DD 形式，返回 (month, day)；格式非法返回 None（闰月月份为负数）"""
    if not isinstance(repeat, str):
        return None
    matched = LUNAR_REPEAT_PATTERN.match(repeat)
    if not matched:
        return None
    try:
        month = int(matched.group(1))
        day = int(matched.group(2))
    except (ValueError, TypeError, OverflowError):
        return None
    if not (1 <= abs(month) <= 12 and 1 <= day <= 30):
        return None
    return month, day


def lunar_label(month: int, day: int) -> str:
    """农历日期中文标签，如 八月十五 / 闰六月初一"""
    if not (1 <= abs(month) <= 12) or not (1 <= day <= 30):
        return "农历日期"
    prefix = "闰" if month < 0 else ""
    return f"{prefix}{LUNAR_MONTH_NAMES[abs(month) - 1]}月{LUNAR_DAY_NAMES[day - 1]}"


def solar_to_lunar(date_obj: datetime.date):
    """公历日期 → 农历 (month, day)，农历月份负数表示闰月；不可用时返回 None"""
    if not LUNAR_AVAILABLE or date_obj is None:
        return None
    try:
        lunar = Solar.fromYmd(date_obj.year, date_obj.month, date_obj.day).getLunar()
        return lunar.getMonth(), lunar.getDay()
    except Exception as e:
        logger.error(f"公历转农历失败 ({date_obj}): {e}")
        return None


def lunar_to_solar(year: int, month: int, day: int):
    """农历 (year, month, day) → 公历 date；不可用或转换失败返回 None"""
    if not LUNAR_AVAILABLE:
        return None
    try:
        solar = Lunar.fromYmd(year, month, day).getSolar()
        return datetime.date(solar.getYear(), solar.getMonth(), solar.getDay())
    except Exception as e:
        logger.error(f"农历转公历失败 ({year}-{month}-{day}): {e}")
        return None


def is_lunar_anniversary(date_obj: datetime.date, month: int, day: int) -> bool:
    """判断指定公历日期是否为农历 month 月 day 日的周年（闰月需月份同为负数）"""
    converted = solar_to_lunar(date_obj)
    if converted is None:
        return False
    return converted == (month, day)
