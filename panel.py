# -*- coding: utf-8 -*-
"""
南向资金监控面板 (Streamlit)
============================
6 个 Tab（已排除 港股通沪/深 两个日频分支，仅保留合计口径）：
  Tab1 分钟级   ak.stock_hsgt_fund_min_em(symbol="南向资金")            —— 当天日内累计，点刷新重拉
  Tab2 日频     ak.stock_hsgt_hist_em(symbol="南向资金")               —— 自带全部历史，一次拉全
  Tab3 机构统计 ak.stock_hsgt_institution_statistics_em(market="南向持股") —— 上卡片(最新日)+下折线(区间)
  Tab4 个股     ak.stock_hsgt_individual_em(symbol=代码)               —— 左列表选股，右侧每日一行明细
  Tab5 持股榜   本地 SQLite(south_hold_ranks)                         —— 选单日，全市场持股排行(可排序)；库滞后则提示下载
  Tab6 反势因子 本地 SQLite(south_hold_ranks)                         —— 全市场某日 + 截面因子(增持幅度 z/分位/反势评分/加速度/未来收益)，自排序选股

运行：
  cd C:\\Users\\chunh\\WorkBuddy\\2026-07-08-22-04-38
  "C:\\Users\\chunh\\.workbuddy\\binaries\\python\\envs\\akshare\\Scripts\\streamlit.exe" run panel.py
"""
import os
import datetime as dt
import sqlite3

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import akshare as ak
import south_hold_stat as shs
from south_hold_stat import DB_PATH, DB_COLS, init_db, save_hold_history

# ------------------------------------------------------------------ 基础配置
CSV_UNIVERSE = r"C:/Users/chunh/ZCodeProject/stock_factor_project/data/hsi_hkgt_universe_20260709.csv"
INST_MIN_DATE = dt.date(2022, 4, 14)          # 机构统计数据起点（更早会崩）
RED = "#c62828"                                # 涨（A股习惯）
GREEN = "#2e7d32"                              # 跌

st.set_page_config(page_title="南向资金监控面板", page_icon="📈", layout="wide")

# ------------------------------------------------------------------ 工具函数
def color_updown(val):
    """涨红跌绿"""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ""
    if v > 0:
        return f"color:{RED}; font-weight:600"
    if v < 0:
        return f"color:{GREEN}; font-weight:600"
    return ""


def fmt_yi(x, unit=1e8, suffix="亿", nd=2):
    """元 -> 亿 / 股 -> 亿股 等，返回字符串"""
    try:
        return f"{float(x) / unit:,.{nd}f}{suffix}"
    except (TypeError, ValueError):
        return "-"


@st.cache_data(ttl=300, show_spinner=False)
def load_universe():
    df = pd.read_csv(CSV_UNIVERSE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.zfill(5)
    return df


# ------------------------------------------------------------------ 取数（带缓存）
@st.cache_data(ttl=120, show_spinner="拉取分钟级数据…")
def fetch_fund_min():
    return ak.stock_hsgt_fund_min_em(symbol="南向资金")


@st.cache_data(ttl=300, show_spinner="拉取日频数据…")
def fetch_hist():
    return ak.stock_hsgt_hist_em(symbol="南向资金")


@st.cache_data(ttl=300, show_spinner="拉取机构统计…")
def fetch_inst(start, end):
    return ak.stock_hsgt_institution_statistics_em(
        market="南向持股", start_date=start, end_date=end
    )


@st.cache_data(ttl=300, show_spinner="拉取个股持股…")
def fetch_individual(symbol):
    return ak.stock_hsgt_individual_em(symbol=symbol)


@st.cache_data(ttl=300, show_spinner="拉取持股排行…")
def fetch_hold_stats(start, end):
    return shs.get_hold_stats("south", start, end)


# ------------------------------------------------------------------ SQLite 持股榜历史库
# 入库逻辑（DB_COLS / init_db / save_hold_history）已下沉到 south_hold_stat 数据层，
# 本模块通过 `from south_hold_stat import ...` 复用，避免重复定义。


def load_stock_history(code, days=None):
    """从库中读某只股票历史（按日期升序），days=最近 N 个记录，None=全部。"""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT * FROM south_hold_ranks WHERE 代码=? ORDER BY 日期",
        conn, params=(str(code),),
    )
    conn.close()
    if days and len(df) > days:
        df = df.tail(days)
    return df


def db_summary():
    """返回库概况：(总行数, 最早日期, 最新日期)。"""
    if not os.path.exists(DB_PATH):
        return 0, None, None
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("SELECT COUNT(*), MIN(日期), MAX(日期) FROM south_hold_ranks").fetchone()
    except sqlite3.OperationalError:
        row = (0, None, None)
    conn.close()
    return row


@st.cache_data(ttl=300)
def available_dates():
    """返回库中所有交易日（date 对象，降序）。"""
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT 日期 FROM south_hold_ranks ORDER BY 日期 DESC"
    ).fetchall()
    conn.close()
    return [pd.to_datetime(r[0]).date() for r in rows]


@st.cache_data(ttl=300)
def load_day(date_str):
    """读某日全市场快照（SQLite）。date_str: 'YYYY-MM-DD'。按代码去重。"""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT * FROM south_hold_ranks WHERE 日期=?", conn, params=(date_str,)
    )
    conn.close()
    if "代码" in df.columns:
        df = df.drop_duplicates(subset=["代码"], keep="first").reset_index(drop=True)
    return df


@st.cache_data(ttl=300)
def load_window(d0, d1):
    """读 [d0,d1] 区间全部行（仅 代码/日期/收盘价/增持幅度），用于算加速度与未来收益。"""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT 代码,日期,收盘价,增持幅度 FROM south_hold_ranks WHERE 日期>=? AND 日期<=?",
        conn, params=(d0, d1),
    )
    conn.close()
    df["日期"] = pd.to_datetime(df["日期"])
    return df


def compute_factor_columns(day_df, pick_date):
    """在 day_df 上加因子列：截面 z/分位、反势评分、增持加速度、未来5/10/20日收益。"""
    out = day_df.copy()
    feat = "增持幅度"
    if feat in out.columns:
        s = pd.to_numeric(out[feat], errors="coerce")
        lo, hi = s.quantile([0.01, 0.99])
        sw = s.clip(lo, hi)
        sd = sw.std()
        out["增持幅度_z"] = ((sw - sw.mean()) / sd) if (sd and sd == sd) else 0.0
        out["增持幅度_分位"] = s.rank(pct=True)
        out["反势评分"] = 1 - out["增持幅度_分位"]
    pd_ = pd.to_datetime(pick_date)
    d0 = (pd_ - pd.Timedelta(days=25)).strftime("%Y-%m-%d")
    d1 = (pd_ + pd.Timedelta(days=25)).strftime("%Y-%m-%d")
    win = load_window(d0, d1)
    if not win.empty and "代码" in win.columns:
        win = win.dropna(subset=["代码"]).copy()
        win["代码"] = win["代码"].astype(str)
        code_key = out["代码"].astype(str)
        close = win.pivot_table(index="日期", columns="代码", values="收盘价").sort_index()
        if pd_ in close.index:
            for k in (5, 10, 20):
                fc = close.shift(-k) / close - 1
                out[f"未来{k}日收益"] = code_key.map(fc.loc[pd_]).astype(float)
        if feat in win.columns:
            add = win.pivot_table(index="日期", columns="代码", values=feat).sort_index()
            if pd_ in add.index:
                past = add.loc[:pd_]
                acc = past.tail(5).mean() - past.tail(20).mean()
                out["增持加速度"] = code_key.map(acc).astype(float)
    return out


@st.dialog("📊 持股变动明细", width="large")
def show_change_dialog(code, name, days):
    """弹窗：某股票每日持股变动柱状图（正=增持红 / 负=减持绿）。"""
    st.markdown(f"#### {code} {name}")
    hist = load_stock_history(code, days)
    if hist.empty:
        st.warning("库中暂无该股票历史数据，请先在上方点『📥 下载历史』。")
        return
    hist = hist.copy()
    chg = pd.to_numeric(hist["持股变动"], errors="coerce").fillna(0) / 1e4  # 股 -> 万股
    colors = [RED if v >= 0 else GREEN for v in chg]
    fig = go.Figure(go.Bar(x=hist["日期"], y=chg, marker_color=colors, name="持股变动"))
    fig.add_hline(y=0, line_color="#999")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="持股变动(万股)", xaxis_title="日期",
                      hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
    net = chg.sum()
    cA, cB, cC = st.columns(3)
    cA.metric("区间累计变动", f"{net:,.1f} 万股")
    cB.metric("增持天数", f"{int((chg > 0).sum())} 天")
    cC.metric("减持天数", f"{int((chg < 0).sum())} 天")
    with st.expander("查看数据表"):
        t = hist[["日期", "持股变动", "持股数", "持股市值", "持股占比"]].copy()
        t["持股变动(万股)"] = pd.to_numeric(t["持股变动"], errors="coerce") / 1e4
        t["持股数(亿股)"] = pd.to_numeric(t["持股数"], errors="coerce") / 1e8
        t["持股市值(亿)"] = pd.to_numeric(t["持股市值"], errors="coerce") / 1e8
        t = t.drop(columns=["持股变动", "持股数", "持股市值"]).sort_values("日期", ascending=False)
        st.dataframe(
            t.style.map(color_updown, subset=["持股变动(万股)"]).format(
                {"持股变动(万股)": "{:,.1f}", "持股数(亿股)": "{:,.4f}",
                 "持股市值(亿)": "{:,.2f}", "持股占比": "{:,.2f}"}),
            use_container_width=True, height=300, hide_index=True,
        )


def safe_inst(start, end):
    """机构统计空区间会抛异常，这里 guard 住"""
    try:
        df = fetch_inst(start, end)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ================================================================== 页面
st.title("📈 南向资金监控面板")
st.caption("数据源：东方财富 / akshare · 分钟级为当日日内累计，日频/个股 T+1、机构/持股榜 T+1 披露 · 涨红跌绿（A股习惯）")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["① 分钟级", "② 日频净买额", "③ 机构持股统计", "④ 个股持股", "⑤ 持股排行榜(库)", "⑥ 反势选股因子表"]
)

# ------------------------------------------------------------------ Tab1 分钟级
with tab1:
    c1, c2 = st.columns([1, 6])
    with c1:
        if st.button("🔄 刷新", key="btn_min", use_container_width=True):
            fetch_fund_min.clear()
    st.markdown("**当日南向资金日内累计净买入**（单位：亿元；每个交易日 9:00 清零重算）")

    try:
        df = fetch_fund_min().copy()
    except Exception as e:
        st.error(f"拉取失败：{e}")
        df = pd.DataFrame()

    if not df.empty:
        for col in ["港股通(沪)", "港股通(深)", "南向资金"]:
            if col in df.columns:
                df[col + "_亿"] = pd.to_numeric(df[col], errors="coerce") / 1e4  # 万元 -> 亿元
        cur_date = str(df["日期"].iloc[-1]) if "日期" in df.columns else "-"
        last = df.iloc[-1]
        m1, m2, m3 = st.columns(3)
        m1.metric("港股通(沪)", f"{last.get('港股通(沪)_亿', float('nan')):,.2f} 亿")
        m2.metric("港股通(深)", f"{last.get('港股通(深)_亿', float('nan')):,.2f} 亿")
        m3.metric(f"南向合计（{cur_date}）", f"{last.get('南向资金_亿', float('nan')):,.2f} 亿")

        if "时间" in df.columns:
            fig = go.Figure()
            for col, name, color in [
                ("南向资金_亿", "南向合计", "#1f77b4"),
                ("港股通(沪)_亿", "港股通(沪)", "#ff7f0e"),
                ("港股通(深)_亿", "港股通(深)", "#2ca02c"),
            ]:
                if col in df.columns:
                    fig.add_trace(go.Scatter(x=df["时间"], y=df[col], mode="lines", name=name))
            fig.add_hline(y=0, line_dash="dot", line_color="#999")
            fig.update_layout(
                height=380, margin=dict(l=10, r=10, t=30, b=10),
                yaxis_title="累计净买入(亿元)", xaxis_title="时间",
                legend=dict(orientation="h", y=1.12), hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("查看原始分钟级数据"):
            st.dataframe(df, use_container_width=True, height=300)
    else:
        st.info("暂无数据，点『刷新』重试（开盘前或非交易时段可能为空）。")

# ------------------------------------------------------------------ Tab2 日频
with tab2:
    c1, c2 = st.columns([1, 6])
    with c1:
        if st.button("🔄 刷新", key="btn_hist", use_container_width=True):
            fetch_hist.clear()
    st.markdown("**南向资金每日净买额**（接口自带全部历史，一次拉全）")

    try:
        df = fetch_hist().copy()
    except Exception as e:
        st.error(f"拉取失败：{e}")
        df = pd.DataFrame()

    if not df.empty:
        df["日期"] = pd.to_datetime(df["日期"])
        net_col = "当日成交净买额"
        valid = df[df[net_col].notna()] if net_col in df.columns else df
        if len(valid):
            last = valid.iloc[-1]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(f"最新净买额（{last['日期'].date()}）", f"{last.get(net_col, float('nan')):,.2f} 亿")
            if "买入成交额" in df.columns:
                m2.metric("买入成交额", f"{last.get('买入成交额', float('nan')):,.1f} 亿")
            if "卖出成交额" in df.columns:
                m3.metric("卖出成交额", f"{last.get('卖出成交额', float('nan')):,.1f} 亿")
            if "历史累计净买额" in df.columns:
                m4.metric("历史累计净买额", f"{last.get('历史累计净买额', float('nan')):,.4f} 万亿")

        win = st.selectbox("图表窗口", ["近 20 日", "近 60 日", "近 120 日", "近 250 日", "全部"], index=1)
        n_map = {"近 20 日": 20, "近 60 日": 60, "近 120 日": 120, "近 250 日": 250, "全部": len(valid)}
        show = valid.tail(n_map[win])
        if net_col in show.columns:
            colors = [RED if v >= 0 else GREEN for v in show[net_col]]
            fig = go.Figure(go.Bar(x=show["日期"], y=show[net_col], marker_color=colors))
            fig.add_hline(y=0, line_color="#999")
            fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10),
                              yaxis_title="当日净买额(亿元)")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("**明细（最新在上）**")
        table = df.sort_values("日期", ascending=False).copy()
        table["日期"] = table["日期"].dt.strftime("%Y-%m-%d")
        num_cols = [c for c in ["当日成交净买额", "买入成交额", "卖出成交额", "历史累计净买额"] if c in table.columns]
        sty = table.style.map(color_updown, subset=[net_col] if net_col in table.columns else [])
        sty = sty.format({c: "{:,.2f}" for c in num_cols})
        st.dataframe(sty, use_container_width=True, height=360)
    else:
        st.info("暂无数据，点『刷新』重试。")

# ------------------------------------------------------------------ Tab3 机构统计
with tab3:
    st.markdown("**南向（港股通）机构持股统计** —— 上：最新一日两家登记机构；下：区间市值趋势")

    # ---- 上半：最新日快照卡片 ----
    top = st.container()
    with top:
        cc1, cc2 = st.columns([2, 5])
        with cc1:
            # 找最近有数据的交易日
            _end = dt.date.today()
            _start = _end - dt.timedelta(days=20)
            probe = safe_inst(_start.strftime("%Y%m%d"), _end.strftime("%Y%m%d"))
            avail_dates = []
            if not probe.empty:
                avail_dates = sorted(pd.to_datetime(probe["持股日期"]).dt.date.unique(), reverse=True)
            if avail_dates:
                sel_date = st.date_input("快照日期", value=avail_dates[0],
                                         min_value=INST_MIN_DATE, max_value=avail_dates[0])
            else:
                sel_date = st.date_input("快照日期", value=dt.date.today(), min_value=INST_MIN_DATE)
            if st.button("🔄 刷新快照", key="btn_inst_snap", use_container_width=True):
                fetch_inst.clear()

        snap = safe_inst(sel_date.strftime("%Y%m%d"), sel_date.strftime("%Y%m%d"))
        if snap.empty and avail_dates:
            snap = probe[pd.to_datetime(probe["持股日期"]).dt.date == avail_dates[0]]

        if snap.empty:
            st.info("该日无机构统计数据（T+1 披露，今日数据需收盘后次日）。")
        else:
            st.markdown(f"##### 📅 {pd.to_datetime(snap['持股日期']).dt.date.iloc[0]} 机构持股快照")
            cards = st.columns(len(snap))
            for i, (_, row) in enumerate(snap.iterrows()):
                with cards[i]:
                    st.markdown(f"**{row['机构名称']}**")
                    st.metric("持股市值", fmt_yi(row.get("持股市值"), 1e12, "万亿"))
                    _cnt = pd.to_numeric(row.get("持股只数"), errors="coerce")
                    st.caption(f"持股只数：{int(_cnt):,} 只" if pd.notna(_cnt) else "持股只数：—")
                    d1 = row.get("持股市值变化-1日")
                    d5 = row.get("持股市值变化-5日")
                    d10 = row.get("持股市值变化-10日")
                    st.metric("较前1日", fmt_yi(d1, 1e8, "亿"),
                              delta=f"{float(d1)/1e8:+.2f}亿" if pd.notna(d1) else None)
                    cA, cB = st.columns(2)
                    cA.caption(f"近5日：{fmt_yi(d5)}")
                    cB.caption(f"近10日：{fmt_yi(d10)}")

    st.divider()

    # ---- 下半：区间市值折线 ----
    st.markdown("##### 📈 持股市值趋势")
    bc1, bc2, bc3 = st.columns([2, 2, 2])
    default_start = max(INST_MIN_DATE, dt.date.today() - dt.timedelta(days=365))
    with bc1:
        r_start = st.date_input("起始日", value=default_start, min_value=INST_MIN_DATE, key="inst_rs")
    with bc2:
        r_end = st.date_input("结束日", value=dt.date.today(), min_value=INST_MIN_DATE, key="inst_re")
    with bc3:
        show_total = st.checkbox("叠加合计线", value=True)

    trend = safe_inst(r_start.strftime("%Y%m%d"), r_end.strftime("%Y%m%d"))
    if trend.empty:
        st.info("该区间无数据（起点约 2022-04-14；单次上限约 1 年，超范围请缩短区间）。")
    else:
        trend = trend.copy()
        trend["持股日期"] = pd.to_datetime(trend["持股日期"])
        trend["市值_万亿"] = pd.to_numeric(trend["持股市值"], errors="coerce") / 1e12
        fig = go.Figure()
        for name, g in trend.groupby("机构名称"):
            g = g.sort_values("持股日期")
            fig.add_trace(go.Scatter(x=g["持股日期"], y=g["市值_万亿"], mode="lines", name=name))
        if show_total:
            tot = trend.groupby("持股日期")["市值_万亿"].sum().reset_index()
            fig.add_trace(go.Scatter(x=tot["持股日期"], y=tot["市值_万亿"], mode="lines",
                                     name="合计", line=dict(dash="dash", color="#555")))
        fig.update_layout(height=400, margin=dict(l=10, r=10, t=30, b=10),
                          yaxis_title="持股市值(万亿元)",
                          legend=dict(orientation="h", y=1.12), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"区间 {r_start} ~ {r_end}，共 {trend['持股日期'].nunique()} 个交易日。")

# ------------------------------------------------------------------ Tab4 个股
with tab4:
    st.markdown("**个股南向持股明细** —— 左侧选股，右侧显示该股每日持股（约近 2 年，最新在上）")
    uni = load_universe()
    left, right = st.columns([1, 4])

    with left:
        st.caption(f"港股通标的（{len(uni)} 只）")
        list_df = uni[["ticker", "name"]].rename(columns={"ticker": "代码", "name": "名称"})
        event = st.dataframe(
            list_df, use_container_width=True, height=560, hide_index=True,
            on_select="rerun", selection_mode="single-row",
        )

    with right:
        sel_rows = event.selection.rows if event and event.selection else []
        if not sel_rows:
            st.info("← 从左侧点选一只股票查看明细")
        else:
            idx = sel_rows[0]
            code = uni.iloc[idx]["ticker"]
            name = uni.iloc[idx]["name"]
            cA, cB = st.columns([5, 1])
            cA.markdown(f"#### {code} {name}")
            with cB:
                if st.button("🔄 刷新", key="btn_indiv", use_container_width=True):
                    fetch_individual.clear()
            try:
                d = fetch_individual(code).copy()
            except Exception as e:
                st.error(f"拉取失败：{e}")
                d = pd.DataFrame()

            if d.empty:
                st.info("该标的无南向持股数据。")
            else:
                d["持股日期"] = pd.to_datetime(d["持股日期"])
                d = d.sort_values("持股日期", ascending=False)
                # 顶部快照
                last = d.iloc[0]
                mm = st.columns(4)
                mm[0].metric("最新日", f"{last['持股日期'].date()}")
                if "持股数量" in d.columns:
                    mm[1].metric("持股数量", fmt_yi(last.get("持股数量"), 1e8, "亿股"))
                if "持股市值" in d.columns:
                    mm[2].metric("持股市值", fmt_yi(last.get("持股市值"), 1e8, "亿"))
                占比列 = next((c for c in d.columns if "占" in c and "百分比" in c), None) or \
                        next((c for c in d.columns if "占" in c), None)
                if 占比列:
                    mm[3].metric("持股占比", f"{float(last.get(占比列, 0)):.2f}%")

                # 持股占比柱状图（时间序列，默认近 60 日，窗口可选）
                if 占比列:
                    st.markdown("**持股占比走势**")
                    win4 = st.selectbox(
                        "图表窗口", ["近 20 日", "近 60 日", "近 120 日", "近 250 日", "全部"],
                        index=1, key="win_indiv",
                    )
                    n_map4 = {"近 20 日": 20, "近 60 日": 60, "近 120 日": 120,
                              "近 250 日": 250, "全部": len(d)}
                    chart_df = d.sort_values("持股日期").tail(n_map4[win4]).copy()
                    chart_df[占比列] = pd.to_numeric(chart_df[占比列], errors="coerce")
                    fig = go.Figure(go.Bar(x=chart_df["持股日期"], y=chart_df[占比列],
                                           marker_color=RED, name="持股占比%"))
                    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                                      yaxis_title="持股占比(%)", xaxis_title="日期")
                    st.plotly_chart(fig, use_container_width=True)

                # 明细表：数值可读化 + 涨红跌绿
                show = d.copy()
                show["持股日期"] = show["持股日期"].dt.strftime("%Y-%m-%d")
                if 占比列 and 占比列 != "持股占比%":
                    show = show.rename(columns={占比列: "持股占比%"})
                pct_col = "当日涨跌幅" if "当日涨跌幅" in show.columns else None
                fmt = {}
                for c in ["持股数量"]:
                    if c in show.columns:
                        show[c] = pd.to_numeric(show[c], errors="coerce") / 1e8
                        fmt[c] = "{:,.4f}"  # 亿股
                        show = show.rename(columns={c: "持股数量(亿股)"})
                        fmt["持股数量(亿股)"] = "{:,.4f}"
                for c in ["持股市值", "持股市值变化-1日", "持股市值变化-5日", "持股市值变化-10日"]:
                    if c in show.columns:
                        show[c] = pd.to_numeric(show[c], errors="coerce") / 1e8
                        fmt[c] = "{:,.2f}"
                        show = show.rename(columns={c: c + "(亿)"})
                        fmt[c + "(亿)"] = "{:,.2f}"
                for c in ["当日收盘价", "持股占比%"]:
                    if c in show.columns:
                        fmt[c] = "{:,.2f}"
                if pct_col:
                    fmt[pct_col] = "{:+.2f}%"
                color_cols = [c for c in [pct_col, "持股市值变化-1日(亿)", "持股市值变化-5日(亿)",
                                          "持股市值变化-10日(亿)"] if c and c in show.columns]
                sty = show.style.map(color_updown, subset=color_cols).format(fmt, na_rep="-")
                st.dataframe(sty, use_container_width=True, height=460, hide_index=True)

# ------------------------------------------------------------------ Tab5 持股排行榜（本地库历史）
with tab5:
    st.markdown("**南向持股排行榜（本地库）** —— 选单日看全市场持股；点表头排序；点某行看该股持股变动柱状图。若库最新非当日，点右侧『📥 下载』刷新。")
    dates = available_dates()
    if not dates:
        st.warning("本地库暂无数据，请点右侧『📥 下载 / 更新』拉取历史。")
    else:
        win5_map = {"近20日": 20, "近60日": 60, "近120日": 120, "近250日": 250, "全部": None}
        tc1, tc2, tc3 = st.columns([2, 2, 4])

        with tc1:
            pick = st.date_input("查询日期", value=dates[0], min_value=dates[-1],
                                 max_value=dates[0], key="hold_date")
            today = dt.date.today()
            gap = (today - dates[0]).days
            if gap > 0:
                st.warning(f"⚠️ 库最新 {dates[0]}，落后 {gap} 天 — 点下载更新")
            else:
                st.success(f"✅ 库已更新至 {dates[0]}")
            if st.button("🔄 刷新缓存", key="btn_hold", use_container_width=True):
                available_dates.clear(); load_day.clear(); load_window.clear()

        with tc2:
            st.markdown(
                '<div style="font-size:0.875rem;color:rgb(49,51,63);margin-bottom:0.25rem;'
                'line-height:1.6;">历史数据</div>',
                unsafe_allow_html=True,
            )
            with st.popover("📥 下载 / 更新", use_container_width=True):
                st.caption("拉取南向持股榜区间数据，存入本地 SQLite（可重复下载，自动去重覆盖）")
                dflt_end = dates[0]
                dflt_start = dflt_end - dt.timedelta(days=60)
                dl_start = st.date_input("起始日", value=dflt_start, key="dl_start")
                dl_end = st.date_input("结束日", value=dflt_end, key="dl_end")
                if st.button("开始下载", key="btn_download", type="primary", use_container_width=True):
                    with st.spinner("下载中（区间越大越慢，请稍候）…"):
                        n, nd = save_hold_history(dl_start.strftime("%Y%m%d"),
                                                  dl_end.strftime("%Y%m%d"))
                    if n:
                        st.success(f"已写入 {n:,} 行 / {nd} 个交易日")
                        available_dates.clear(); load_day.clear()
                    else:
                        st.warning("该区间无数据")
                cnt, dmin, dmax = db_summary()
                if cnt:
                    st.caption(f"📦 本地库：{cnt:,} 行 · {dmin} ~ {dmax}")
                else:
                    st.caption("📦 本地库暂无数据，请先下载")
            btn_slot = st.empty()

        with tc3:
            win5 = st.selectbox("变动图窗口", ["近20日", "近60日", "近120日", "近250日", "全部"],
                                index=1, key="win_hold")

        day = load_day(pick.strftime("%Y-%m-%d"))
        if day.empty:
            st.info("该日无持股排行数据。")
        else:
            show = day.copy()
            d0 = pd.to_datetime(show["日期"]).dt.date.iloc[0]
            st.caption(f"📅 {d0} · 共 {len(show)} 只标的 · 点选任意一行查看其持股变动走势")
            codes = show["代码"].astype(str).tolist()
            names = show["名称"].astype(str).tolist()
            fmt = {}
            for c in ["持股市值", "增持市值"]:
                if c in show.columns:
                    show[c] = pd.to_numeric(show[c], errors="coerce") / 1e8
                    show = show.rename(columns={c: c + "(亿)"})
                    fmt[c + "(亿)"] = "{:,.2f}"
            for c in ["持股占比", "增持占比", "增持幅度", "涨跌幅", "总股本占比",
                      "流通占比", "市值变动1日", "市值变动5日", "市值变动10日"]:
                if c in show.columns:
                    fmt[c] = "{:,.2f}"
            color_cols = [c for c in ["增持市值(亿)", "增持占比", "增持幅度", "涨跌幅", "持股变动"]
                          if c in show.columns]
            sty = show.style.map(color_updown, subset=color_cols).format(fmt, na_rep="-")
            event = st.dataframe(sty, use_container_width=True, height=560, hide_index=True,
                                 on_select="rerun", selection_mode="single-row", key="hold_table")

            sel = event.selection.rows if event and event.selection else []
            if sel and codes:
                i = sel[0]
                code_sel, name_sel = codes[i], (names[i] if i < len(names) else "")
                st.session_state.hold_sel_code = code_sel
                st.session_state.hold_sel_name = name_sel
                st.caption(f"✅ 已选 {code_sel} {name_sel} —— 点上方『📊 查看…持股变动』按钮看柱状图")
            else:
                st.session_state.hold_sel_code = None
                st.session_state.hold_sel_name = None

        sel_code = st.session_state.get("hold_sel_code")
        sel_name = st.session_state.get("hold_sel_name")
        if sel_code:
            if btn_slot.button(f"📊 查看 {sel_code} {sel_name} 持股变动", key="btn_dlg",
                               type="primary", use_container_width=True):
                show_change_dialog(sel_code, sel_name,
                                   win5_map.get(st.session_state.get("win_hold", "近60日"), 60))


# ------------------------------------------------------------------ Tab6 反势选股 / 因子表（本地库历史）
with tab6:
    st.markdown("**反势选股因子表（本地库）** —— 全市场某日快照 + 截面因子：增持幅度 z / 分位 / 反势评分 / 增持加速度 / 未来收益。默认按反势评分降序（增持越少越靠前＝越该买）。")
    dates = available_dates()
    if not dates:
        st.warning("本地库暂无数据，请先在 Tab5 点『📥 下载 / 更新』。")
    else:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
        with c1:
            pick = st.date_input("查询日期", value=dates[0], min_value=dates[-1],
                                 max_value=dates[0], key="fac_date")
            today = dt.date.today()
            gap = (today - dates[0]).days
            if gap > 0:
                st.warning(f"⚠️ 库最新 {dates[0]}，落后 {gap} 天")
            else:
                st.success(f"✅ 库已更新至 {dates[0]}")
        with c2:
            day_tmp = load_day(pick.strftime("%Y-%m-%d"))
            industries = (sorted([x for x in day_tmp["行业"].dropna().astype(str).unique()])
                          if "行业" in day_tmp.columns else [])
            ind_sel = st.multiselect("行业过滤", industries, default=[], key="fac_ind")
        with c3:
            min_score = st.slider("反势评分下限", 0.0, 1.0, 0.0, 0.05, key="fac_min")
        with c4:
            topn = st.number_input("导出 Top-N", 5, 200, 30, 5, key="fac_n")

        day = compute_factor_columns(day_tmp, pick.strftime("%Y-%m-%d"))
        view = day.copy()
        if ind_sel and "行业" in view.columns:
            view = view[view["行业"].astype(str).isin(ind_sel)]
        if "反势评分" in view.columns:
            view = view[view["反势评分"] >= min_score].sort_values("反势评分", ascending=False)

        disp_cols = [c for c in ["代码", "名称", "行业", "增持幅度", "增持幅度_z", "增持幅度_分位",
                                 "反势评分", "增持加速度", "参与者数", "持股数", "持股市值",
                                 "涨跌幅", "未来5日收益", "未来10日收益", "未来20日收益"]
                     if c in view.columns]
        show = view[disp_cols].copy()
        fmt = {}
        for c in ["持股市值"]:
            if c in show.columns:
                show[c] = pd.to_numeric(show[c], errors="coerce") / 1e8
                show = show.rename(columns={c: c + "(亿)"})
                fmt[c + "(亿)"] = "{:,.2f}"
        for c in ["增持幅度", "涨跌幅", "增持加速度"]:
            if c in show.columns:
                fmt[c] = "{:,.2f}"
        if "增持幅度_z" in show.columns:
            fmt["增持幅度_z"] = "{:,.3f}"
        for c in ["增持幅度_分位", "反势评分", "未来5日收益", "未来10日收益", "未来20日收益"]:
            if c in show.columns:
                fmt[c] = "{:,.2%}"
        color_cols = [c for c in ["增持幅度", "涨跌幅", "增持加速度", "未来5日收益",
                                  "未来10日收益", "未来20日收益"] if c in show.columns]
        sty = show.style.map(color_updown, subset=color_cols).format(fmt, na_rep="-")
        st.caption(f"📅 {pick} · 反势候选 {len(show)} 只（已按反势评分降序）· 红=涨/增持/正收益，绿=跌/减持/负收益")
        st.dataframe(sty, use_container_width=True, height=600, hide_index=True)

        if len(show):
            exp = show.head(int(topn))
            csv = exp.to_csv(index=False).encode("utf-8-sig")
            st.download_button(f"⬇️ 导出当前视图 CSV（Top {int(topn)}）", csv,
                               file_name=f"contrarian_{pick}.csv", mime="text/csv",
                               use_container_width=True)
