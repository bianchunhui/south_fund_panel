# -*- coding: utf-8 -*-
"""
拉取恒生指数(HSI)与恒生科技指数(HSTECH)日线，存 CSV，供市场中性化基准。

- 数据源：akshare stock_hk_index_daily_sina（eastmoney em 源在本环境连接被重置，sina 可用）
- 截取区间 2025-07-15 ~ 2026-07-15

用法：
    python fetch_index.py
"""
import akshare as ak
import pandas as pd

OUT = "index_hsi_hstech.csv"
START = "2024-07-16"
END = "2026-07-15"


def fetch(sym: str, name: str) -> pd.DataFrame:
    df = ak.stock_hk_index_daily_sina(symbol=sym)
    df = df.rename(columns={"date": "日期", "open": "开盘", "high": "最高",
                            "low": "最低", "close": "收盘", "volume": "成交量"})
    df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
    df = df[(df["日期"] >= START) & (df["日期"] <= END)].copy()
    df.insert(1, "指数", name)
    return df[["日期", "指数", "收盘", "开盘", "最高", "最低", "成交量"]]


def main():
    hsi = fetch("HSI", "恒生指数")
    hst = fetch("HSTECH", "恒生科技")
    out = pd.concat([hsi, hst], ignore_index=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"已写 {OUT}：{len(out)} 行 "
          f"({hsi['日期'].nunique()} 日 HSI + {hst['日期'].nunique()} 日 HSTECH)")


if __name__ == "__main__":
    main()
