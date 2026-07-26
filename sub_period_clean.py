# -*- coding: utf-8 -*-
"""
分市场状态（修正对齐版）：
- 组合与基准严格取【同一组交易日】对齐，避免 fillna(0) 污染。
- 超额收益两种口径并列：
  几何超额 = (1+组合总收益)/(1+基准总收益) - 1
  算术超额 = 组合总收益 - 基准总收益
- 信号 IC 复用 signal_test（已验证真·未来口径）。
输出 sub_period_clean.json
"""
import json
import numpy as np
import pandas as pd
from rank_topn import prep, backtest, metrics
from signal_test import load_panel, load_index, build, ic_by_day, HORIZONS
FEAT = "增持幅度"
N = 30
HOLD = 5
REBAL = 5
COST = 0.001
PERIODS = {
    "牛市_24-07~25-12": ("2024-07-16", "2025-12-31"),
    "非牛市_26-01~26-07": ("2026-01-01", "2026-07-15"),
}


def period_total(series_on_days, pdays):
    """series_on_days: dict(day->daily_ret)；pdays: 区间交易日。
    取交集(组合与基准同一组日子)复利，返回净值末端 -1。"""
    s = pd.Series({d: r for d, r in series_on_days.items() if d in set(pdays)})
    return float((1 + s).prod() - 1), s


def main():
    df, idx, days, bench_ret = prep()
    bench_full = bench_ret.reindex(days).fillna(0.0)        # 日频等权宇宙
    # 同频(5日调仓)等权宇宙（与组合同节奏，纯选股 alpha 公平基准）
    allw = {}
    for i in range(0, len(days) - HOLD, REBAL):
        rday = days[i]; nxt = days[i + 1: i + 1 + HOLD]
        sub = df[df["日期"] == rday].dropna(subset=["ret"]).copy()
        if len(sub) < 50:
            continue
        for j, t in enumerate(nxt):
            tt = df[df["日期"] == t].set_index("代码").reindex(sub["代码"])["ret"].dropna()
            if len(tt):
                allw[t] = tt.mean() - (2 * COST if j == 0 else 0)
    allw_s = pd.Series(allw)
    allw_full = allw_s.reindex(days).fillna(0.0)
    out = {"全样本复核": {}, "分段_long-only": {}, "分段_信号IC": {}}

    # 全样本复核（同频基准为主，日频为参考）
    for nm, pick in [("TopN_做多", "top"), ("BotN_做多(反势)", "bottom")]:
        raw = pd.Series(backtest(df, days, N, pick))
        raw_full = raw.reindex(days).fillna(0.0)
        ex_same = raw_full - allw_full
        ex_daily = raw_full - bench_full
        out["全样本复核"][nm] = {"裸": metrics(raw_full),
                                 "超额_vs_同频等权": metrics(ex_same),
                                 "超额_vs_日频等权": metrics(ex_daily)}

    for pname, (lo, hi) in PERIODS.items():
        pdays = [d for d in days if pd.Timestamp(lo) <= d <= pd.Timestamp(hi)]
        res = {}
        # 同频等权宇宙在本区间的对齐持有日收益（与组合同一批持有日）
        bot_d0 = backtest(df, days, N, "bottom")
        _, bot_s0 = period_total(bot_d0, pdays)
        hold_days = list(bot_s0.index)
        uw_same = pd.Series({d: allw_full[d] for d in hold_days})
        uw_total = float((1 + uw_same).prod() - 1)
        res["宇宙等权_同频_裸(对齐持有日)"] = round(uw_total, 4)
        hs_same = pd.Series({d: bench_full[d] for d in hold_days})
        res["宇宙等权_日频_裸(对齐持有日)"] = round(float((1 + hs_same).prod() - 1), 4)
        for nm, pick in [("TopN_做多", "top"), ("BotN_做多(反势)", "bottom")]:
            port_d = backtest(df, days, N, pick)
            port_total, port_s = period_total(port_d, pdays)
            geom = (1 + port_total) / (1 + uw_total) - 1
            arith = port_total - uw_total
            res[f"{nm}_裸"] = round(port_total, 4)
            res[f"{nm}_超额_几何"] = round(geom, 4)
            res[f"{nm}_超额_算术"] = round(arith, 4)
        out["分段_long-only"][pname] = res

    # 信号 IC（复用 signal_test，已验证真·未来口径）
    dfb = build(df, idx)
    for pname, (lo, hi) in PERIODS.items():
        sub = dfb[(dfb["日期"] >= lo) & (dfb["日期"] <= hi)]
        res = {}
        for k in HORIZONS:
            ic, t, p, n = ic_by_day(sub, FEAT, f"fwd{k}_ex")
            res[f"未来{k}日超额IC"] = dict(IC=ic, t=t, p=p, n=n)
        ic, t, p, n = ic_by_day(sub, FEAT, "past5_ex")
        res["过去5日(追涨)IC"] = dict(IC=ic, t=t, p=p, n=n)
        out["分段_信号IC"][pname] = res

    with open("sub_period_clean.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)

    def r(x): return f"{x:+.2%}"
    print("=== 全样本复核（超额=vs 同频等权宇宙）===")
    for nm, v in out["全样本复核"].items():
        print(f"  {nm}: 裸={r(v['裸']['总收益'])} 超额(同频)={r(v['超额_vs_同频等权']['总收益'])}")
    for pname in PERIODS:
        print(f"\n=== {pname} ===")
        for k, v in out["分段_long-only"][pname].items():
            print(f"  {k}: {r(v)}" if isinstance(v, float) else f"  {k}: {v}")
        print("  信号IC(增持幅度 vs 未来超额):")
        for k, v in out["分段_信号IC"][pname].items():
            print(f"    {k}: IC={v['IC']:.4f} t={v['t']} n={v['n']}")
    print("\n(saved -> sub_period_clean.json)")


if __name__ == "__main__":
    main()
