# -*- coding: utf-8 -*-
"""
一次性调用 7 个「可用且能取到最新数据」的南向(港股通)接口，展示数据。
运行环境: akshare venv (akshare 1.18.64)
"""
import akshare as ak
import pandas as pd
from south_hold_stat import get_hold_stats  # 第7个: 直连底层

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 260)
pd.set_option("display.unicode.east_asian_width", True)

SEP = "=" * 90


def show(title, df, tail=8):
    print(SEP)
    print(title)
    print("-" * 90)
    if df is None or len(df) == 0:
        print("  (无数据)")
        return
    print(f"  形状: {df.shape[0]} 行 x {df.shape[1]} 列")
    print(f"  列名: {list(df.columns)}")
    print(f"  最后 {tail} 行:")
    print(df.tail(tail).to_string())


# 1. 南向资金 分钟级（当日累计）
try:
    df1 = ak.stock_hsgt_fund_min_em(symbol="南向资金")
    show("【1】港股通实时净买入额(分钟级)  ak.stock_hsgt_fund_min_em(symbol='南向资金')", df1, 6)
except Exception as e:
    print(SEP); print("【1】ERROR:", type(e).__name__, str(e)[:200])

# 2. 南向资金 日频整体
try:
    df2 = ak.stock_hsgt_hist_em(symbol="南向资金")
    show("【2】港股通整体每日净买额(日频)  ak.stock_hsgt_hist_em(symbol='南向资金')", df2, 6)
except Exception as e:
    print(SEP); print("【2】ERROR:", type(e).__name__, str(e)[:200])

# 3. 港股通沪 日频
try:
    df3 = ak.stock_hsgt_hist_em(symbol="港股通沪")
    show("【3】沪港通下港股通每日净买额  ak.stock_hsgt_hist_em(symbol='港股通沪')", df3, 6)
except Exception as e:
    print(SEP); print("【3】ERROR:", type(e).__name__, str(e)[:200])

# 4. 港股通深 日频
try:
    df4 = ak.stock_hsgt_hist_em(symbol="港股通深")
    show("【4】深港通下港股通每日净买额  ak.stock_hsgt_hist_em(symbol='港股通深')", df4, 6)
except Exception as e:
    print(SEP); print("【4】ERROR:", type(e).__name__, str(e)[:200])

# 5. 南向持股 机构统计
try:
    df5 = ak.stock_hsgt_institution_statistics_em(
        market="南向持股", start_date="20260701", end_date="20260709")
    show("【5】港股通机构持股统计  ak.stock_hsgt_institution_statistics_em(market='南向持股')", df5, 8)
except Exception as e:
    print(SEP); print("【5】ERROR:", type(e).__name__, str(e)[:200])

# 6. 单只港股通标的 南向持股（腾讯 00700）
try:
    df6 = ak.stock_hsgt_individual_em(symbol="00700")
    show("【6】单只港股通标的南向持股(00700腾讯)  ak.stock_hsgt_individual_em(symbol='00700')", df6, 6)
except Exception as e:
    print(SEP); print("【6】ERROR:", type(e).__name__, str(e)[:200])

# 7. 港股通个股持股统计（直连底层）
try:
    df7 = get_hold_stats("south", "20260708", "20260708")
    show("【7】港股通个股持股统计(直连 RPT_MUTUAL_STOCK_HOLDRANKS)  south_hold_stat.get_hold_stats", df7, 8)
except Exception as e:
    print(SEP); print("【7】ERROR:", type(e).__name__, str(e)[:200])

print(SEP)
print("全部 7 个接口调用完毕。")
