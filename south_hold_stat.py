"""
沪深港通持股统计 直连工具（绕过 akshare 解析 bug）

- 北向持股统计：底层 reportName=RPT_MUTUAL_STOCK_NORTHSTA，已于 2024-05-13 北向披露取消后
  被东方财富下线，调用会返回「服务器繁忙」，本工具会明确提示，无数据。
- 南向（港股通）持股统计：底层 reportName=RPT_MUTUAL_STOCK_HOLDRANKS，仍可用，返回真实数据。
  akshare 官方 stock_hsgt_stock_statistics_em(symbol="南向持股") 因 filter 误用 MUTUAL_TYPE("001","003")
  而查不到数据，本工具修正为正确的港股通类型(002/004)或全量。

用法：
    python south_hold_stat.py                      # 默认拉南向最近一个交易日
    python south_hold_stat.py --start 20260701 --end 20260708
    python south_hold_stat.py --source north       # 演示北向(已下线)
"""
import argparse
import os
import sqlite3
import datetime as dt
import requests
import pandas as pd

API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/hsgtcg/StockStatistics.aspx",
    "Accept": "application/json, text/plain, */*",
}


def _norm(d: str) -> str:
    d = str(d).replace("-", "").replace("/", "")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def get_hold_stats(source: str, start_date: str, end_date: str, mutual_type: str = None) -> pd.DataFrame:
    sd, ed = _norm(start_date), _norm(end_date)
    if sd > ed:
        sd, ed = ed, sd  # 自动纠正反写日期

    if source == "north":
        report = "RPT_MUTUAL_STOCK_NORTHSTA"
        mt = '(MUTUAL_TYPE in ("001","003"))' if mutual_type is None else f'(MUTUAL_TYPE="{mutual_type}")'
    else:  # south
        report = "RPT_MUTUAL_STOCK_HOLDRANKS"
        mt = "" if mutual_type is None else f'(MUTUAL_TYPE="{mutual_type}")'

    filt = f'(INTERVAL_TYPE="1"){mt}(TRADE_DATE>=\'{sd}\')(TRADE_DATE<=\'{ed}\')'
    params = {
        "sortColumns": "TRADE_DATE", "sortTypes": "-1",
        "pageSize": "1000", "pageNumber": "1",
        "columns": "ALL", "source": "WEB", "client": "WEB",
        "filter": filt, "reportName": report,
    }

    r = requests.get(API, params=params, headers=HEADERS, timeout=30)
    j = r.json()
    res = j.get("result")
    if res is None:
        print(f"[{source}] 底层接口返回: {j.get('message')} —— 该维度数据已下线/不可用")
        return pd.DataFrame()

    total = int(res.get("pages", 1))
    # 第一页数据已在探测请求中拿到，直接复用，避免重复请求（P1#4）
    frames = []
    first_rows = res.get("data")
    if first_rows:
        frames.append(pd.DataFrame(first_rows))
    for p in range(2, total + 1):
        params["pageNumber"] = p
        r = requests.get(API, params=params, headers=HEADERS, timeout=30)
        # dict.get(k, default) 的 default 仅在 key 缺失时生效；
        # 东财偶发繁忙时 result 键存在但值为 None，故用 (... or {}) 兜底（P0#1）
        rows = (r.json().get("result") or {}).get("data")
        if rows:
            frames.append(pd.DataFrame(rows))

    # 所有页均无数据时 frames 为空，pd.concat([]) 会抛 ValueError（P0#2）
    if not frames:
        return pd.DataFrame()
    big = pd.concat(frames, ignore_index=True)
    rename = {
        "SECURITY_CODE": "代码", "SECUCODE": "证券代码", "SECURITY_NAME": "名称",
        "SECURITY_NAME_ABBR": "名称", "TRADE_DATE": "持股日期", "HOLD_DATE": "持仓日期",
        "MUTUAL_TYPE": "类型", "INTERVAL_TYPE": "区间类型",
        "ADD_MARKET_CAP": "增持市值", "ADD_RATIO": "增持占比%",
        "HOLD_MARKET_CAP": "持股市值", "HOLD_SHARES": "持股数",
        "HOLD_SHARES_RATIO": "持股占比%", "HOLD_SHARES_CHANGE": "持股变动",
        "ADD_SHARES_AMP": "增持幅度%", "ADD_SHARES_REPAIR": "增持股数",
        "CLOSE_PRICE": "收盘价", "CHANGE_RATE": "涨跌幅%", "INDUSTRY": "行业",
        "TOTAL_SHARES_RATIO": "总股本占比%", "FREE_SHARES_RATIO": "流通占比%",
        "PARTICIPANT_NUM": "参与者数",
        "HOLD_MARKETCAP_CHG1": "市值变动1日", "HOLD_MARKETCAP_CHG5": "市值变动5日",
        "HOLD_MARKETCAP_CHG10": "市值变动10日",
    }
    big = big.rename(columns={k: v for k, v in rename.items() if k in big.columns})
    drop_cols = [c for c in ["IS_ADJ_DATE", "EX_DIVIDEND_DATE", "EQUITY_RECORD_DATE", "RN",
                             "HOLD_SHARES_FADJ", "HOLD_SHARES_ADJ"] if c in big.columns]
    if drop_cols:
        big = big.drop(columns=drop_cols)
    return big


# ====================== SQLite 持股历史库（数据层） ======================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hsgt_hold.db")

# 入库列（含 eastmoney 返回的全部数值字段，单一数据源）
DB_COLS = ["日期", "代码", "名称", "行业", "持股数", "持股变动", "增持股数",
           "持股市值", "持股占比", "增持市值", "增持占比",
           "增持幅度", "流通占比", "总股本占比",
           "参与者数", "市值变动1日", "市值变动5日", "市值变动10日",
           "涨跌幅", "收盘价"]

# 目标列 -> 接口源列 映射
SRC_MAP = {
    "日期": "日期", "代码": "代码", "名称": "名称", "行业": "行业",
    "持股数": "持股数", "持股变动": "持股变动", "增持股数": "增持股数",
    "持股市值": "持股市值", "持股占比%": "持股占比", "增持市值": "增持市值",
    "增持占比%": "增持占比",
    "增持幅度%": "增持幅度", "流通占比%": "流通占比", "总股本占比%": "总股本占比",
    "参与者数": "参与者数",
    "市值变动1日": "市值变动1日", "市值变动5日": "市值变动5日", "市值变动10日": "市值变动10日",
    "涨跌幅%": "涨跌幅", "收盘价": "收盘价",
}


def init_db():
    """建表并迁移补齐新字段（表已存在时 ALTER ADD，幂等）。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS south_hold_ranks (
            日期 TEXT, 代码 TEXT, 名称 TEXT, 行业 TEXT,
            持股数 REAL, 持股变动 REAL, 增持股数 REAL,
            持股市值 REAL, 持股占比 REAL, 增持市值 REAL,
            增持占比 REAL, 涨跌幅 REAL, 收盘价 REAL,
            PRIMARY KEY (日期, 代码)
        )
    """)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(south_hold_ranks)")
    existing = {r[1] for r in cur.fetchall()}
    for col in ["增持幅度", "流通占比", "总股本占比", "参与者数",
                "市值变动1日", "市值变动5日", "市值变动10日"]:
        if col not in existing:
            cur.execute(f"ALTER TABLE south_hold_ranks ADD COLUMN {col} REAL")
    conn.commit()
    conn.close()


def save_hold_history(start, end):
    """拉区间南向持股榜写入 SQLite（幂等 INSERT OR REPLACE），返回 (写入行数, 交易日数)。"""
    df = get_hold_stats("south", start, end)
    if df.empty:
        return 0, 0
    df = df.copy()
    df["日期"] = pd.to_datetime(df["持股日期"]).dt.strftime("%Y-%m-%d")
    # 同股挂 002/004 两类型数值相同，按 日期+代码 去重
    df = df.drop_duplicates(subset=["日期", "代码"], keep="first")
    out = pd.DataFrame()
    for dst_col in DB_COLS:
        src = next((s for s, d in SRC_MAP.items() if d == dst_col), None)
        out[dst_col] = df[src] if src in df.columns else None
    for c in DB_COLS[4:]:  # 数值列
        out[c] = pd.to_numeric(out[c], errors="coerce")

    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        f"INSERT OR REPLACE INTO south_hold_ranks ({','.join(DB_COLS)}) "
        f"VALUES ({','.join(['?'] * len(DB_COLS))})",
        out[DB_COLS].where(pd.notna(out), None).values.tolist(),
    )
    conn.commit()
    conn.close()
    return len(out), out["日期"].nunique()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="south", choices=["north", "south"])
    ap.add_argument("--start", default="20260707")
    ap.add_argument("--end", default="20260708")
    ap.add_argument("--type", default=None, help="港股通类型: 002(沪港通)/004(深港通)，留空取全量")
    a = ap.parse_args()

    df = get_hold_stats(a.source, a.start, a.end, a.type)
    if not df.empty:
        print(f"共 {len(df)} 行，列: {list(df.columns)}")
        print(df.head(10).to_string())
