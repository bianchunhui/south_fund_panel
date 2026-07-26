# 港股通(南向)增持反势选股面板

用港股通(南向)每日持股数据，检验「南向增持幅度」对未来股价的影响，并把结论做成可交互面板 + 回测。

**核心发现：增持幅度是反势(反转)因子**——南向越追涨的标的，未来 5/10/20 日超额收益越差；反向做多「增持最少」组合有稳定 alpha。

---

## 核心结论（已回测验证，数据区间 2024-07-16 ~ 2026-07-15）

- 样本：469 交易日 / 740 只 / 257,232 行（东方财富接口仅提供 2024-07-16 起数据，更早为空）
- 同期性：增持幅度 vs 当日收益强正相关（IC +0.052）→ 南向在**追涨**
- 领先性：增持幅度 vs 未来 5/10/20 日超额收益**负相关**（IC −0.0056 / −0.0087 / −0.0108）→ 反转因子
- 复利回测（N=30，持有 5 日，每 5 日调仓，超额基准 = 同频宇宙等权）：
  - 多 Top-N（追热）：裸 −34%，超额 **−38%**
  - 多 Bot-N（反势）：裸 +26.7%，超额 **+21.5%**（夏普 0.76）
  - 多空反（多冷空热）：裸 +83.5%，超额 **+58.7%**（年化 +28%）
- 牛 / 非牛两段都赢 → 是 anti-crowding 倾斜，**无需市场状态开关**（牛市 edge 更薄，仅 +5.9% 超额，而非方向反转）

---

## 目录与文件

**核心脚本（已入库）：**

| 文件 | 作用 |
|------|------|
| `panel.py` | Streamlit 面板（6 个 Tab） |
| `south_hold_stat.py` | 数据层：eastmoney 直连 + SQLite 入库（单一数据源，字段定义只在此处） |
| `signal_test.py` | 因子四步检验（同期性 / IC / 分组 / OLS）→ `signal_test_results.json` + `group_cumret.png` |
| `rank_topn.py` | 复利回测（Top / Bottom-N）→ `topn_backtest.json` + `topn_cumret.png` |
| `sub_period_clean.py` | 牛 / 非牛分段验证 → `sub_period_clean.json` |
| `backfill_history.py` | 历史持股回补到 SQLite（按月分批、幂等覆盖） |
| `fetch_index.py` | 拉取 HSI / HSTECH 基准指数 → `index_hsi_hstech.csv` |
| `start_panel.bat` / `start_panel.ps1` | Windows 启动器（端口 8701，关窗级联杀进程树） |

**被 `.gitignore` 排除（不进仓库）：**

- `hsgt_hold.db` — 43MB 本地持仓库（个人隐私数据，可由脚本重建）
- `index_hsi_hstech.csv` — 基准指数缓存（可由 `fetch_index.py` 重建）
- `.workbuddy/` — 项目分析记忆与约定
- `check_hsgt_*.py` — 11 个探索探针脚本（调试用，非核心）
- `__pycache__/` / `start_panel.log`

---

## 环境依赖

- Python 3.13（测试环境）
- 依赖见 `requirements.txt`：

```bash
pip install -r requirements.txt
```

---

## 数据准备（首次必做）

仓库**不含**数据文件，clone 后需自己生成：

**1. 基准指数**（信号检验 / 回测需要）

```bash
python fetch_index.py
```

生成 `index_hsi_hstech.csv`。

**2. 南向持股历史库**（面板 Tab5 / Tab6 需要）

- 方式 A（批量回补，推荐）：

  ```bash
  python backfill_history.py --start 20250701 --end 20260715
  ```

- 方式 B（面板内实时下载）：启动面板 → Tab5「📥 下载」按钮，按日入库到 `hsgt_hold.db`。

SQLite 库默认路径：`hsgt_hold.db`（与脚本同目录），表名 `south_hold_ranks`。

---

## 启动面板

**Windows：** 双击 `start_panel.bat`（内部调用 `start_panel.ps1`），默认端口 **8701**，自动打开浏览器。

或手动启动：

```bash
python -m streamlit run panel.py --server.port 8701 --server.headless true
```

**关窗即停：** 启动器用 PowerShell Job 托管整棵 streamlit 进程树（外层 `python -m streamlit` → 内层 `python -c bootstrap server`），并在窗口关闭时级联 `taskkill /F /T` 杀掉所有子进程——含脱离进程组的 server 孤儿进程，解决「窗口关了，服务还在占端口」的问题。

---

## 面板 Tab 说明

- **Tab1–4（akshare 实时接口）**：分钟级净买额 / 日频净买 / 机构持股统计 / 个股持股明细。走 akshare 实时接口；部分筛选依赖本机 `stock_factor_project` 下的标的池 CSV，缺失时相关筛选会降级。
- **Tab5 持股排行榜**：读本地 SQLite 历史，选单日全市场持股排行（可排序）；库最新日非当天时提示手动下载。
- **Tab6 反势选股因子表**：读本地 SQLite，截面因子（增持幅度 z / 分位 / 反势评分 / 增持加速度 / 未来 5·10·20 日收益），支持行业筛选、评分阈值、导出 Top-N CSV。

---

## 因子检验与回测

```bash
python signal_test.py        # 四步检验
python rank_topn.py          # 复利回测
python sub_period_clean.py   # 牛/非牛分段
```

输出 JSON（数值结果）+ PNG（曲线图），在同目录生成。

---

## 免责声明

仅供研究与学习，不构成任何投资建议。
