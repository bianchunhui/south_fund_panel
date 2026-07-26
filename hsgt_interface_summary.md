# 沪深港通 akshare 接口实测对照表（2026-07-08）

> 测试环境：akshare 1.18.64（akshare venv）
> 结论主线：**可用且能取最新数据的，目前全部是南向（港股通）；北向（外资买A股）相关接口因 2024-05-13 / 2024-08-19 披露政策调整，基本全废或停在 2024-08-16。**

## 一、可用 + 能取最新数据（仅南向 / 港股通）

| # | 接口内容（中文简述） | akshare 调用方式 | 最新数据日期 | 备注 |
|---|---|---|---|---|
| 1 | 港股通(沪+深) 实时净买入额 / 资金流（分钟级，9:00–16:10） | `ak.stock_hsgt_fund_min_em(symbol="南向资金")` | 2026-07-08（收盘定格） | 单位推断万元，南向合计约 142 亿 |
| 2 | 港股通整体 每日净买额 / 买入 / 卖出 / 累计净买额 | `ak.stock_hsgt_hist_em(symbol="南向资金")` | 2026-07-08 | 当日资金流入/余额列恒空，其余真实 |
| 3 | 沪港通下港股通 每日净买额（基准恒生指数） | `ak.stock_hsgt_hist_em(symbol="港股通沪")` | 2026-07-08 | 自 2014-11-17 全有值 |
| 4 | 深港通下港股通 每日净买额（基准恒生指数） | `ak.stock_hsgt_hist_em(symbol="港股通深")` | 2026-07-08 | 2199 行，净买额 71.64 亿 |
| 5 | 港股通 机构持股统计（机构名称 / 持股只数 / 持股市值 / 变化-1/5/10日） | `ak.stock_hsgt_institution_statistics_em(market="南向持股", start_date, end_date)` | 2026-07-07 | akshare 原生可用，无需修改 |
| 6 | 单只港股通标的 南向聚合持股（持股数量 / 市值 / 占A股比 / 变化） | `ak.stock_hsgt_individual_em(symbol="<港股代码，如 00700>")` | 2026-07-07 | **传港股代码自动走南向**；A股代码则走北向（止于 2024-08-16） |
| 7 | 港股通 个股持股统计（增持市值 / 持股数 / 持股占比） | akshare 原生 ❌（`symbol="南向持股"` filter 写错） → 用底层直连 | 2026-07-07 | 见下方底层地址；已封装 `south_hold_stat.py` |

### 第 7 项底层调用（akshare 不可用，需直连）

```
GET https://datacenter-web.eastmoney.com/api/data/v1/get
  reportName = RPT_MUTUAL_STOCK_HOLDRANKS
  filter     = (TRADE_DATE>='YYYY-MM-DD')(TRADE_DATE<='YYYY-MM-DD')
               # 不限制 MUTUAL_TYPE（akshare 错用 001/003，那是沪/深股通）
  columns    = ALL
  source/client = WEB
  Referer    = https://data.eastmoney.com/hsgtcg/  （带 UA/Referer 头，否则返回"服务器繁忙"）
```
→ 可用工具：`south_hold_stat.py`（支持 `--start/--end/--type 002|004/--source north|south`）

---

## 二、已确认不可用（北向方向，列作参考）

| 接口内容 | akshare 调用 | 状态 | 根因 |
|---|---|---|---|
| 北向资金 分钟级 | `stock_hsgt_fund_min_em(symbol="北向资金")` | 拉到今天但金额全 0 | 2024-05-13 起停披露实时净买额 |
| 北向资金 日频 | `stock_hsgt_hist_em(symbol="北向资金")` | 不报错但金额列全 NaN | 真实数据止于 2024-08-16 |
| 北向持股榜 | `stock_hsgt_hold_stock_em(market="北向", indicator=*)` | 崩溃 TypeError | 底层 `RPT_MUTUAL_STOCK_NORTHSTA` 已下线 |
| 北向持股统计 | `stock_hsgt_stock_statistics_em(symbol="北向持股")` | 崩溃 TypeError | 同上报废 reportName |
| 北向机构统计 | `stock_hsgt_institution_statistics_em(market="北向持股")` | 崩溃 TypeError | 底层 `PRT_MUTUAL_ORG_STA` 北向维度空 |
| 北向个股聚合持股 | `stock_hsgt_individual_em(symbol="<A股代码>")` | 有数据但止于 2024-08-16 | 数据冻结，无最新 |
| 北向个股成交明细(券商) | `stock_hsgt_individual_detail_em(symbol="<A股代码>")` | 近期区间崩溃；历史≤2024-08-16 可用 | 底层 `RPT_MUTUAL_HOLD_DET` 仅北向且止于 2024-08-16；空区间触发 akshare bug |

---

## 三、一句话结论

- **做南向（港股通）资金流 / 持股监控**：上面第 1–7 项全部可用，实时更新到今天。
- **做北向（外资买A股）分析**：公开市场接口基本拿不到最新数据，仅 `individual_em`（A股代码）能取 2017–2024-08-16 的历史聚合持股作回测；要最新北向只能换交易所官方披露或付费源（如恒生聚源 MCP）。
- **`individual_em` 是"方向自动切换"接口**：传 A 股代码→北向（旧），传港股代码→南向（新），写脚本时字段结构随方向不同，须动态取列。
