# -*- coding: utf-8 -*-
"""
南向增持幅度 -> 复利滚动组合回测（修正版）
========================================
关键修正：真·未来收益率下，增持幅度是「负向」因子（高增持=未来跑输）。
因此同时回测：
  - 做多 Top-N（顺势/追涨）   —— 预期亏
  - 做多 Bottom-N（反势）     —— 预期赚
  - 多空(反): 多 Bottom-N - 空 Top-N
每 REBAL 个交易日按当日增持幅度截面 z-score 选股，持有其后 HOLD 个交易日、等权、到点轮动。
同时给「超额收益」口径（日收益 - 本宇宙等权日收益），剔除大盘牛熊影响，看纯选股 alpha。
"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from signal_test import load_panel, load_index, BENCH, add_universe_ew

DB = "hsgt_hold.db"
IDX = "index_hsi_hstech.csv"
HOLD = 5
REBAL = 5
N = 30
COST = 0.001
OUT_JSON = "topn_backtest.json"
OUT_PNG = "topn_cumret.png"
FEAT = "增持幅度"


def prep():
    df = load_panel()
    idx = load_index()
    idx = add_universe_ew(idx, df)
    df["ret"] = df.groupby("代码")["收盘价"].pct_change()
    days = list(pd.to_datetime(sorted(df["日期"].unique())))
    bench_ret = idx[BENCH].pct_change()
    return df, idx, days, bench_ret


def zscore(s):
    s = s.astype(float)
    sd = s.std()
    return (s - s.mean()) / sd if (np.isfinite(sd) and sd != 0) else s * 0.0


def backtest(df, days, n, pick, hold=HOLD, rebal=REBAL):
    """pick='top' 选增持最高, 'bottom' 选增持最低。返回组合日收益 Series(索引=持有日)。"""
    d = {}
    for i in range(0, len(days) - hold, rebal):
        rday = days[i]
        nxt = days[i + 1: i + 1 + hold]
        sub = df[df["日期"] == rday].dropna(subset=[FEAT, "ret"]).copy()
        if len(sub) < 50:
            continue
        sub["z"] = zscore(sub[FEAT])
        sub = sub.sort_values("z", ascending=False)
        sel = sub.tail(n) if pick == "bottom" else sub.head(n)
        for j, t in enumerate(nxt):
            tt = df[df["日期"] == t].set_index("代码").reindex(sel["代码"])["ret"].dropna()
            if len(tt):
                r = tt.mean() - (2 * COST if j == 0 else 0)
                d[t] = r
    return pd.Series(d)


def grid_full(s, days):
    return s.reindex(days).fillna(0.0)


def metrics(ret: pd.Series):
    r = ret.dropna()
    if len(r) < 2:
        return {}
    cum = (1 + r).cumprod() - 1
    total = float(cum.iloc[-1])
    ann = float((1 + total) ** (252 / len(r)) - 1)
    sd = r.std()
    sharpe = float(r.mean() / sd * np.sqrt(252)) if (sd and np.isfinite(sd)) else float("nan")
    wealth = (1 + r).cumprod()
    dd = wealth / wealth.cummax() - 1
    return dict(总收益=round(total, 4), 年化=round(ann, 4),
                夏普=round(sharpe, 3), 最大回撤=round(float(dd.min()), 4))


def main():
    df, idx, days, bench_ret = prep()
    bench_full = grid_full(bench_ret, days)                 # 日频再平衡等权宇宙基准
    # 同频(每 REBAL 调仓)等权宇宙基准——与组合同一节奏，是纯选股 alpha 的公平基准
    allw = {}
    for i in range(0, len(days) - HOLD, REBAL):
        rday = days[i]
        nxt = days[i + 1: i + 1 + HOLD]
        sub = df[df["日期"] == rday].dropna(subset=["ret"]).copy()
        if len(sub) < 50:
            continue
        for j, t in enumerate(nxt):
            tt = df[df["日期"] == t].set_index("代码").reindex(sub["代码"])["ret"].dropna()
            if len(tt):
                allw[t] = tt.mean() - (2 * COST if j == 0 else 0)
    allw_s = pd.Series(allw)
    allw_full = grid_full(allw_s, days)

    out = {"参数": dict(HOLD=HOLD, REBAL=REBAL, N=N, 单边成本=COST,
                        股票数=int(df["代码"].nunique()), 交易日数=len(days),
                        日期范围=[str(days[0].date()), str(days[-1].date())])}
    out["基准_宇宙等权_日频_裸"] = metrics(bench_full)
    out["基准_宇宙等权_同频(5日调仓)_裸"] = metrics(allw_full)

    curves = {}
    for name, pick in [("TopN_做多", "top"), ("BotN_做多(反势)", "bottom")]:
        raw = grid_full(backtest(df, days, N, pick), days)
        ex_daily = raw - bench_full            # vs 日频等权宇宙
        ex_same = raw - allw_full              # vs 同频等权宇宙（选股 alpha）
        out[f"{name}_裸"] = metrics(raw)
        out[f"{name}_超额_vs_日频等权"] = metrics(ex_daily)
        out[f"{name}_超额_vs_同频等权"] = metrics(ex_same)
        curves[name] = (1 + ex_same).cumprod()      # 超额净值(选股 alpha 口径)
    # 多空(反): 多 Bottom - 空 Top
    top_raw = grid_full(backtest(df, days, N, "top"), days)
    bot_raw = grid_full(backtest(df, days, N, "bottom"), days)
    ls_raw = bot_raw - top_raw
    ls_ex_daily = ls_raw - bench_full
    ls_ex_same = ls_raw - allw_full
    out["多空反_裸"] = metrics(ls_raw)
    out["多空反_超额_vs_日频等权"] = metrics(ls_ex_daily)
    out["多空反_超额_vs_同频等权"] = metrics(ls_ex_same)
    curves["多空反(Bot-Top)"] = (1 + ls_ex_same).cumprod()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=float))

    plt.figure(figsize=(9, 5))
    labmap = {"TopN_做多": "Long Top-N (momentum)",
              "BotN_做多(反势)": "Long Bottom-N (contrarian)",
              "多空反(Bot-Top)": "LS reversed (long Bot - short Top)"}
    for name, c in curves.items():
        plt.plot(c.index, c.values, label=labmap.get(name, name))
    plt.axhline(1, color="grey", lw=0.8)
    plt.title(f"Compounded SELECTION-ALPHA net value (vs same-rebal Universe-EW, N={N})")
    plt.xlabel("Trading day")
    plt.ylabel("Selection-alpha net value (start=1)")
    plt.legend()
    plt.savefig(OUT_PNG, dpi=120, bbox_inches="tight")
    plt.close()


if __name__ == "__main__":
    main()
