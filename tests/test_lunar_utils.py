"""农历工具测试（农历纪念日提醒的换算基础）"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime

import pytest

from app import lunar_utils


pytestmark = pytest.mark.skipif(
    not lunar_utils.LUNAR_AVAILABLE, reason="未安装 lunar_python，跳过农历换算测试"
)


class TestRepeatSpec:
    def test_build_and_parse_normal_month(self):
        spec = lunar_utils.build_lunar_repeat(8, 15)
        assert spec == "lunar:08-15"
        assert lunar_utils.parse_lunar_repeat(spec) == (8, 15)

    def test_build_and_parse_leap_month(self):
        spec = lunar_utils.build_lunar_repeat(-6, 1)
        assert spec == "lunar:-06-01"
        assert lunar_utils.parse_lunar_repeat(spec) == (-6, 1)

    def test_parse_rejects_invalid_specs(self):
        assert lunar_utils.parse_lunar_repeat("lunar:13-01") is None
        assert lunar_utils.parse_lunar_repeat("lunar:00-01") is None
        assert lunar_utils.parse_lunar_repeat("lunar:08-31") is None
        assert lunar_utils.parse_lunar_repeat("lunar:abc") is None
        assert lunar_utils.parse_lunar_repeat("daily") is None
        assert lunar_utils.parse_lunar_repeat(None) is None

    def test_labels(self):
        assert lunar_utils.lunar_label(8, 15) == "八月十五"
        assert lunar_utils.lunar_label(1, 1) == "正月初一"
        assert lunar_utils.lunar_label(-6, 1) == "闰六月初一"
        assert lunar_utils.lunar_label(13, 1) == "农历日期"


class TestConversion:
    def test_known_spring_festivals(self):
        assert lunar_utils.lunar_to_solar(2024, 1, 1) == datetime.date(2024, 2, 10)
        assert lunar_utils.lunar_to_solar(2025, 1, 1) == datetime.date(2025, 1, 29)
        assert lunar_utils.lunar_to_solar(2026, 1, 1) == datetime.date(2026, 2, 17)

    def test_known_mid_autumn(self):
        assert lunar_utils.solar_to_lunar(datetime.date(2026, 9, 25)) == (8, 15)

    def test_leap_month_detected_with_negative_month(self):
        assert lunar_utils.solar_to_lunar(datetime.date(2025, 7, 26)) == (-6, 2)

    def test_anniversary_matching(self):
        assert lunar_utils.is_lunar_anniversary(datetime.date(2026, 9, 25), 8, 15) is True
        assert lunar_utils.is_lunar_anniversary(datetime.date(2026, 9, 24), 8, 15) is False
        # 非闰月规格不会匹配到闰月当天
        assert lunar_utils.is_lunar_anniversary(datetime.date(2025, 7, 25), 6, 1) is False
        assert lunar_utils.is_lunar_anniversary(datetime.date(2025, 7, 25), -6, 1) is True

    def test_roundtrip_this_year(self):
        today = datetime.date.today()
        month, day = lunar_utils.solar_to_lunar(today)
        assert lunar_utils.is_lunar_anniversary(today, month, day) is True
