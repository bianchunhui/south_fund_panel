# -*- coding: utf-8 -*-
"""
分市场状态回测（自洽版）：
先算出全样本每日收益序列（Top/Bot/LS），再按日期切片成牛市/非牛市两段，
保证各段必然链回全样本，杜绝"子集重跑"的边界 bug。
"""
import json
import numpy as np
import pandas as pd
from rank_topn import prep, backtest, grid_full, metrics

N = 30
PERIODS = {
    "牛市_24-07~25-12": ("2024-07-16", "2025-12-31"),
    "非牛市_26-01~26-07": ("2026-01-01", "2026-07-15"),
}


def daily_series(df, days, pick):
    """返回 {日期: 当日组合收益} 的 dict（仅持有日有值）。"""
    return backtest(df, days, N, pick)


def main():
    df, idx, days, bench_ret = prep()
    bench_full = grid_full(bench_ret, days)

    # 1) 全样本每日收益序列
    top_d = daily_series(df, days, "top")
    bot_d = daily_series(df, days, "bottom")
    ls_d = {d: bot_d.get(d, 0) - top_d.get(d, 0) for d in set(top_d) | set(bot_d)}

    def period_metrics(daily_d, pdays, label):
        s = pd.Series({d: r for d, r in daily_d.items() if d in pdays})
        raw = grid_full(s, pdays)
        ex = raw - bench_full.reindex(pdays).fillna(0.0)
        return label, raw, ex

    out = {"全样本复核": {}}
    for nm, dct in [("TopN_做多", top_d), ("BotN_做多(反势)", bot_d), ("多空反", ls_d)]:
        raw = grid_full(pd.Series(dct), days)
        ex = raw - bench_full
        out["全样本复核"][nm] = {"裸": metrics(raw), "超额": metrics(ex)}

    out["分段"] = {}
    for pname, (lo, hi) in PERIODS.items():
        lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
        pdays = [d for d in days if lo <= d <= hi]
        bench_p = bench_full.reindex(pdays).fillna(0.0)
        res = {"恒生科技_裸": metrics(bench_p)}
        for nm, dct in [("TopN_做多", top_d), ("BotN_做多(反势)", bot_d), ("多空反", ls_d)]:
            _, raw, ex = period_metrics(dct, set(pdays), nm)
            res[f"{nm}_裸"] = metrics(raw)
            res[f"{nm}_超额"] = metrics(ex)
        out["分段"][pname] = res

    with open("sub_period_return.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)

    print("=== 全样本复核（应≈之前：TopN -34.2% / BotN +26.7% / 多空 +83.5%）===")
    for nm, v in out["全样本复核"].items():
        print(f"  {nm}: 裸={v['裸']['总收益']:.1%}  超额={v['超额']['总收益']:.1%}")

    for pname, res in out["分段"].items():
        print(f"\n=== {pname} ===")
        for k, v in res.items():
            if isinstance(v, dict):
                print(f"  {k}: 裸={v['总收益']:.1%} 年化={v['年化']:.1%} 夏普={v['夏普']} 回撤={v['最大回撤']:.1%}")
    print("\n(saved -> sub_period_return.json)")


if __name__ == "__main__":
    main()
