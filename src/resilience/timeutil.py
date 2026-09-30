"""日期工具：图谱内统一使用 ISO 日期（YYYY-MM-DD），按天计算。"""

from datetime import date, timedelta

ONE_DAY = timedelta(days=1)


def as_date(value) -> date:
    """把字符串或 date 统一为 date。"""
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def daterange(start: date, end: date):
    """闭区间 [start, end] 上逐天迭代；start 晚于 end 时为空。"""
    day = start
    while day <= end:
        yield day
        day += ONE_DAY


def within(day: date, start: date, end: date | None) -> bool:
    """是否落在 [start, end) 窗口内；end 为空表示开放窗口。"""
    if day < start:
        return False
    return end is None or day < end
