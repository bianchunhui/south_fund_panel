# -*- coding: utf-8 -*-
"""子区间检验：把 2024-07-16~2026-07-15 拆成 牛市段(24-07~25-12) 与 其余段(26-01~26-07)，
对比 增持幅度 的 真·未来超额 IC 与 分组多空(Q高增持 - Q低增持)。
复用 signal_test 的 build/ic_by_day/group_backtest（已验证对齐逻辑）。"""
import signal_test as st

df = st.load_panel()
idx = st.load_index()
full = st.build(df, idx)

periods = {
    "全样本 24-07~26-07": ("2024-07-16", "2026-07-15"),
    "牛市段 24-07~25-12": ("2024-07-16", "2025-12-31"),
    "其余段 26-01~26-07": ("2026-01-01", "2026-07-15"),
}

print("=== 增持幅度 真·未来超额 IC（按子区间）===")
for name, (a, b) in periods.items():
    f = full[(full["日期"] >= a) & (full["日期"] <= b)]
    print(f"\n[{name}]  交易日={f['日期'].nunique()}")
    for k in st.HORIZONS:
        ic, t, p, n = st.ic_by_day(f, "增持幅度", f"fwd{k}_ex")
        print(f"  未来{k}日超额IC = {ic:+.4f}  t={t:+.2f}  p={p:.2e}  n={n}")
    ic, t, p, n = st.ic_by_day(f, "增持幅度", "past5_ex")
    print(f"  过去5日超额IC(南向追涨) = {ic:+.4f}  t={t:+.2f}")
    bygrp, ls, lt, lp = st.group_backtest(f, "增持幅度", "fwd5_ex")
    print(f"  分组多空(高-低增持) 未来5日超额 = {ls:+.3f}%  t={lt:+.2f}  p={lp:.2e}")
