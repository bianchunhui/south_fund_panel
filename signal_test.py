# -*- coding: utf-8 -*-
"""
信号检验：南向增持幅度 -> 未来股价涨幅
========================================
数据：
  - SQLite south_hold_ranks（增持幅度 等全部字段，已回补 1 年）
  - index_hsi_hstech.csv（恒生 / 恒生科技收盘，sina 源）

方法（顺序不可反）：
  1. 同期性检验：增持幅度_t vs 个股当日收益_t（Spearman 逐日 IC）
        —— 若显著正相关，说明南向在"追涨"，该信号无领先 alpha，必须先排伪。
  2. 领先性检验（IC）：增持幅度_t vs 未来 k 日超额收益（个股收益 - 基准指数收益）
  3. 分组回测：按增持幅度五分位，Top 组 - Bottom 组 多空未来 k 日超额收益 + t 检验
  4. 线性回归：未来 k 日超额收益 = β·增持幅度 + 行业/规模控制

基准：本宇宙等权指数（由 panel 全样本等权构建，剔除等权/市值加权结构差，最自洽）；个股收益用收盘价 pct_change 构造。
缺失处理：配对构造时 per-observation dropna（feature 与两端收盘价齐全才保留），
          不整只剔除股票（缺口本就零星）。输出 JSON + 分组累计收益曲线 PNG。
"""
import json
import sqlite3

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DB = "hsgt_hold.db"
IDX = "index_hsi_hstech.csv"
BENCH = "宇宙等权"
HORIZONS = [1, 5, 10, 20]
OUT_JSON = "signal_test_results.json"
OUT_PNG = "group_cumret.png"


def load_panel():
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM south_hold_ranks", con)
    con.close()
    df["日期"] = pd.to_datetime(df["日期"])
    return df.sort_values(["代码", "日期"]).reset_index(drop=True)


def load_index():
    idx = pd.read_csv(IDX, encoding="utf-8-sig", parse_dates=["日期"])
    return idx.pivot(index="日期", columns="指数", values="收盘").sort_index()


def add_universe_ew(idx, df):
    """追加「本宇宙等权」基准：所有标的等权日收益的累计指数(起点100)。

    与 idx 按日期对齐。用本宇宙等权作基准，可剔除「等权 vs 市值加权」结构差，
    使超额收益更纯净地反映选股 alpha（不再混等权/市值加权偏差）。"""
    d = df.copy()
    d["ret"] = d.groupby("代码")["收盘价"].pct_change()
    ew = d.groupby("日期")["ret"].mean()            # 全样本等权日收益
    ew_idx = (1 + ew.fillna(0.0)).cumprod() * 100   # 转价格指数
    ew_idx = ew_idx.reset_index()
    ew_idx.columns = ["日期", "宇宙等权"]
    merged = idx.reset_index().merge(ew_idx, on="日期", how="left").set_index("日期").sort_index()
    merged["宇宙等权"] = merged["宇宙等权"].ffill().bfill()
    return merged


def build(df, idx, bench=None):
    """构造个股日收益、真·未来 k 日收益、未来 k 日超额收益（相对基准指数）。

    真·未来 k 日收益率 = close[T+k]/close[T]-1 = pct_change(k).shift(-k)（结束于 T+k）。
    注意：旧版用 pct_change(k)（过去 k 日，截到当天）当 label，是时序错配，已修正。
    另构造 past{k}_ex（过去 k 日超额）用于解释因子本质（动量/追涨）。
    bench=None 用模块默认 BENCH（宇宙等权）；可显式传 "恒生科技" 做对照。
    """
    df = df.copy()
    df["ret"] = df.groupby("代码")["收盘价"].pct_change()
    bcol = bench or BENCH
    bench = idx[bcol]
    bench_ret = bench.pct_change()  # 基准日收益（date-indexed）
    b = pd.DataFrame({"日期": idx.index})
    for k in HORIZONS:
        b[f"bfwd{k}"] = bench_ret.shift(-k).values          # 基准未来 k 日收益（结束 T+k）
        b[f"pbench{k}"] = bench.pct_change(k).values        # 基准过去 k 日收益（结束 T）
    df = df.merge(b, on="日期", how="left")
    for k in HORIZONS:
        df[f"fwd{k}"] = df.groupby("代码")["收盘价"].pct_change(k).shift(-k)  # 个股未来 k 日
        df[f"fwd{k}_ex"] = df[f"fwd{k}"] - df[f"bfwd{k}"]
        df[f"past{k}"] = df.groupby("代码")["收盘价"].pct_change(k)           # 个股过去 k 日（截到 T）
        df[f"past{k}_ex"] = df[f"past{k}"] - df[f"pbench{k}"]
    return df


def ic_by_day(df, feat, label):
    """逐日 Spearman(特征, 标签)，返回 (均值IC, t, p, 有效天数)。"""
    ics = []
    for _, g in df.groupby("日期"):
        gg = g.dropna(subset=[feat, label])
        if len(gg) < 30 or gg[feat].nunique() < 5:
            continue
        rho, _ = stats.spearmanr(gg[feat], gg[label])
        if np.isfinite(rho):
            ics.append(rho)
    ics = pd.Series(ics).dropna()
    if len(ics) < 2:
        return float("nan"), float("nan"), float("nan"), 0
    t, p = stats.ttest_1samp(ics, 0)
    return float(ics.mean()), float(t), float(p), int(len(ics))


def group_backtest(df, feat, label, q=5):
    """按特征五分位，返回 (各组平均标签%, 多空差%, t, p)。"""
    rec = []
    for _, g in df.groupby("日期"):
        gg = g.dropna(subset=[feat, label])
        if len(gg) < 50:
            continue
        gg = gg.copy()
        gg["grp"] = pd.qcut(gg[feat], q, labels=False, duplicates="drop")
        rec.append(gg[["grp", label]])
    if not rec:
        return pd.Series(dtype=float), float("nan"), float("nan"), float("nan")
    long = pd.concat(rec)
    by_grp = long.groupby("grp")[label].mean() * 100  # 转百分比
    top = long[long["grp"] == long["grp"].max()][label]
    bot = long[long["grp"] == long["grp"].min()][label]
    t, p = stats.ttest_ind(top, bot, equal_var=False)
    return by_grp, float((top.mean() - bot.mean()) * 100), float(t), float(p)


def ols(df, label, controls=True):
    need = ["增持幅度", label]
    if controls:
        need += ["行业", "持股市值"]
    d = df.dropna(subset=need).copy()
    # winsorize 增持幅度（1%/99%），排除小盘股单日巨额增持的极端 outlier
    lo, hi = d["增持幅度"].quantile([0.01, 0.99])
    d["增持幅度_w"] = d["增持幅度"].clip(lo, hi).astype(float)
    X = pd.DataFrame({"增持幅度": d["增持幅度_w"]})
    if controls:
        ind = pd.get_dummies(d["行业"].astype(str), prefix="ind", drop_first=True).astype(float)
        X = pd.concat([X, ind], axis=1)
        X["logmv"] = np.log(d["持股市值"].clip(lower=1)).astype(float)
    X = sm.add_constant(X, has_constant="add")
    y = d[label].astype(float).values
    return sm.OLS(y, X).fit()


def plot_group(df, feat, label):
    rows = []
    for _, g in df.groupby("日期"):
        gg = g.dropna(subset=[feat, label])
        if len(gg) < 50:
            continue
        gg = gg.copy()
        gg["grp"] = pd.qcut(gg[feat], 5, labels=False, duplicates="drop")
        rows.append(gg.groupby("grp")[label].mean())
    if not rows:
        return
    panel = pd.DataFrame(rows)      # 行=交易日, 列=Q1-Q5
    cum = panel.cumsum() * 100      # 沿交易日累计
    plt.figure(figsize=(8, 5))
    for i, col in enumerate(panel.columns):
        plt.plot(cum.index, cum[col].values, label=f"Q{i + 1}")
    plt.axhline(0, color="grey", lw=0.8)
    plt.title("Add-rate Quintile: cum. fwd-5d excess return (%)")
    plt.xlabel("Trading day")
    plt.ylabel("Cum. excess return (%)")
    plt.legend(title="Group (Q1 low ~ Q5 high add)", loc="upper left")
    plt.savefig(OUT_PNG, dpi=120, bbox_inches="tight")
    plt.close()


def main():
    df_raw = load_panel()
    idx = load_index()
    idx = add_universe_ew(idx, df_raw)     # 追加本宇宙等权基准列
    df = build(df_raw, idx)                # 默认 BENCH = 宇宙等权
    feat = "增持幅度"
    out = {}
    out["基准"] = BENCH
    out["样本概况"] = dict(
        股票数=int(df["代码"].nunique()),
        交易日数=int(df["日期"].nunique()),
        日期范围=[str(df["日期"].min().date()), str(df["日期"].max().date())],
        增持幅度非空=int(df[feat].notna().sum()),
        增持幅度缺失率=round(float(df[feat].isna().mean()), 4),
    )

    # 1) 同期性（排伪）
    ic_s, t_s, p_s, n_s = ic_by_day(df, feat, "ret")
    out["同期性_IC_增持幅度_vs_当日收益"] = dict(IC=ic_s, t=t_s, p=p_s, n=n_s)

    # 2) 领先性 IC（真·未来收益）
    for k in HORIZONS:
        ic, t, p, n = ic_by_day(df, feat, f"fwd{k}_ex")
        out[f"领先性_IC_{k}日超额(真未来)"] = dict(IC=ic, t=t, p=p, n=n)

    # 2b) 同期性 IC（过去收益，揭示因子本质是动量/追涨）
    for k in HORIZONS:
        ic, t, p, n = ic_by_day(df, feat, f"past{k}_ex")
        out[f"同期性_IC_{k}日超额(过去)"] = dict(IC=ic, t=t, p=p, n=n)

    # 3) 分组回测
    for k in HORIZONS:
        by_grp, ls, t, p = group_backtest(df, feat, f"fwd{k}_ex")
        out[f"分组_{k}日"] = dict(
            各组均值pct={int(kk): round(v, 4) for kk, v in by_grp.to_dict().items()},
            多空pct=ls, t=t, p=p)

    # 4) 回归
    for k in HORIZONS:
        m = ols(df, f"fwd{k}_ex", controls=True)
        out[f"回归_{k}日_含控制"] = dict(
            beta=float(m.params["增持幅度"]), t=float(m.tvalues["增持幅度"]),
            r2=float(m.rsquared), n=int(m.nobs))
        m0 = ols(df, f"fwd{k}_ex", controls=False)
        out[f"回归_{k}日_无控制"] = dict(
            beta=float(m0.params["增持幅度"]), t=float(m0.tvalues["增持幅度"]),
            r2=float(m0.rsquared), n=int(m0.nobs))

    # 稳健性对照：同一 OLS 在 恒生科技 基准下（IC 与基准无关，仅 OLS 的 y 变）
    df_hs = build(df_raw, idx, bench="恒生科技")
    out["基准对照_OLS_恒生科技_5日"] = {}
    for controls in (True, False):
        m = ols(df_hs, "fwd5_ex", controls=controls)
        out["基准对照_OLS_恒生科技_5日"]["含控制" if controls else "无控制"] = dict(
            beta=float(m.params["增持幅度"]), t=float(m.tvalues["增持幅度"]), n=int(m.nobs))

    # 先落盘 JSON（即使绘图异常也不丢结果），再绘图
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=float))
    plot_group(df, feat, "fwd5_ex")


if __name__ == "__main__":
    main()
