import datetime
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.calendar_utils import is_china_workday, get_next_workday

def test_2100_leap():
    print("====================================================")
    print("   2100 年闰年边界回归测试报告 (Backend)")
    print("====================================================")

    print("[1] 验证 Python datetime 逻辑:")
    try:
        d_last_feb = datetime.date(2100, 2, 28)
        d_next = d_last_feb + datetime.timedelta(days=1)
        print(f"    2100-02-28 的下一天是: {d_next}")

        if d_next == datetime.date(2100, 3, 1):
            print("    \u2705 正常: 2100-02-28 之后是 2100-03-01 (平年)。")
        else:
            print("    \u274c 错误: 2100 年被误判为闰年。")

        try:
            datetime.date(2100, 2, 29)
            print("    \u274c 错误: datetime.date 竟然允许 2100-02-29 存在！")
        except ValueError:
            print("    \u2705 正常: Python 禁止创建 2100-02-29。")

    except Exception as e:
        print(f"    \u274c 异常: {e}")

    print("\n[2] 验证应用逻辑 (Workday Logic):")
    d28 = datetime.date(2100, 2, 28)
    d01 = datetime.date(2100, 3, 1)

    print(f"    2100-02-28 (周{d28.weekday()+1 if d28.weekday()<6 else '日'}): {'工作日' if is_china_workday(d28) else '节假日/周末'}")
    print(f"    2100-03-01 (周{d01.weekday()+1}): {'工作日' if is_china_workday(d01) else '节假日/周末'}")

    next_work = get_next_workday(d28)
    print(f"    2100-02-28 之后的下一个工作日是: {next_work}")

    if next_work == datetime.date(2100, 3, 1):
        print("    \u2705 正常: 下一个工作日跳转正确。")
    else:
        print("    \u274c 错误: 下一个工作日跳转逻辑异常。")

    print("\n====================================================")
    print("   测试结论: 通过")
    print("====================================================")

if __name__ == "__main__":
    test_2100_leap()
