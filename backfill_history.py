# -*- coding: utf-8 -*-
"""
回补南向(港股通)持股排行历史数据到 SQLite（1 年起），按月分批、幂等覆盖。

- 入库逻辑见 south_hold_stat.save_hold_history（单列定义/映射单一数据源）
- 接口：eastmoney RPT_MUTUAL_STOCK_HOLDRANKS（datacenter-web 域名，已验证可用）
- 主键 (日期, 代码) INSERT OR REPLACE，重跑安全；缺失日/缺失股票自然跳过

用法：
    python backfill_history.py                 # 默认 2025-07-15 ~ 今天
    python backfill_history.py --start 20250701 --end 20260715
"""
import argparse
import datetime as dt

import south_hold_stat as s


def month_ranges(start: dt.date, end: dt.date):
    """生成按月切分的 [(a,b), ...] 区间，首尾对齐 start/end。"""
    ranges = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        ms = dt.date(y, m, 1)
        me = (dt.date(y + 1, 1, 1) if m == 12 else dt.date(y, m + 1, 1)) - dt.timedelta(days=1)
        ranges.append((max(ms, start), min(me, end)))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return ranges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20250715")
    ap.add_argument("--end", default=dt.date.today().strftime("%Y%m%d"))
    a = ap.parse_args()
    start = dt.datetime.strptime(a.start, "%Y%m%d").date()
    end = dt.datetime.strptime(a.end, "%Y%m%d").date()

    s.init_db()  # 确保表 + 新列(增持幅度/流通占比/总股本占比等)存在
    total_rows = total_days = 0
    print(f"回补区间：{start} ~ {end}，按月分批", flush=True)
    for a, b in month_ranges(start, end):
        sa, sb = a.strftime("%Y%m%d"), b.strftime("%Y%m%d")
        try:
            n, nd = s.save_hold_history(sa, sb)
            total_rows += n
            total_days += nd
            print(f"[OK] {sa}~{sb}  写入 {n:>6,} 行 / {nd:>3} 日  | 累计 {total_rows:>8,} 行 / {total_days} 日",
                  flush=True)
        except Exception as e:
            print(f"[FAIL] {sa}~{sb}  {type(e).__name__}: {str(e)[:140]}", flush=True)
    print(f"完成：累计写入 {total_rows:,} 行 / {total_days} 交易日", flush=True)


if __name__ == "__main__":
    main()
