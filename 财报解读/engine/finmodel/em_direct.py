# -*- coding: utf-8 -*-
"""东方财富直连接口（不经 akshare 封装）。

两个能力：
1. 三大报表直连（datacenter-web API）——与 akshare 通道同源但独立请求链路，
   可用于交叉验证（akshare 返回 vs 直连返回逐字段比对）。
2. F10 主营构成（分部数据）——按产品/行业/地区的收入、成本、毛利率，
   补上原 Wind 模型「收入分析」「成本分析」表的分部数据缺口
   （原表依赖 Wind 终端函数 s_segment_*，公开接口此前不可得）。

接口（均为公开 Web 接口，无需 token）：
- datacenter: https://datacenter-web.eastmoney.com/api/data/v1/get
- F10:        https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax
- kline:      https://push2his.eastmoney.com/api/qt/stock/kline/get
"""
from __future__ import annotations

import re
import time

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
F10_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# push2his 编号镜像站（主站限流/瞬断时轮换，akshare 同款做法）
KLINE_HOSTS = [
    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://90.push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://25.push2his.eastmoney.com/api/qt/stock/kline/get",
]

# datacenter 报表 reportName（F10_FINANCE_G 系列列名与 akshare 通道完全一致，
# 可直接复用 datasource 的 IS_MAP/BS_MAP/CF_MAP；DMSK 系列字段不全，勿用）
REPORT_INCOME = "RPT_F10_FINANCE_GINCOME"
REPORT_BALANCE = "RPT_F10_FINANCE_GBALANCE"
REPORT_CASHFLOW = "RPT_F10_FINANCE_GCASHFLOW"

# F10 主营构成 MAINOP_TYPE -> 分类维度
MAINOP_DIM = {"1": "按行业", "2": "按产品", "3": "按地区"}


def _six_code(code_or_em: str) -> str:
    """从 '300274.SZ' / 'SZ300274' / '300274' 提取 6 位代码。"""
    m = re.search(r"(\d{6})", str(code_or_em))
    if not m:
        raise ValueError(f"无法解析代码: {code_or_em}")
    return m.group(1)


def _f10_code(code_or_em: str) -> str:
    """F10 接口代码格式：SZ300274 / SH688345 / BJ920720。"""
    s = str(code_or_em).upper().strip()
    if re.fullmatch(r"(SH|SZ|BJ)\d{6}", s):
        return s
    num = _six_code(s)
    if num.startswith(("4", "8", "920")):
        return "BJ" + num
    if num.startswith(("6", "9")):
        return "SH" + num
    return "SZ" + num


def _secucode(code_or_em: str) -> str:
    """SECUCODE 格式：300274.SZ / 688345.SH / 920720.BJ。"""
    s = str(code_or_em).upper().strip()
    m = re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", s)
    if m:
        return s
    if re.fullmatch(r"(SH|SZ|BJ)\d{6}", s):
        return s[2:] + "." + s[:2]
    num = _six_code(s)
    if num.startswith(("4", "8", "920")):
        return num + ".BJ"
    if num.startswith(("6", "9")):
        return num + ".SH"
    return num + ".SZ"


def fetch_dc_report(report_name: str, code_or_em: str, page_size: int = 100) -> pd.DataFrame:
    """分页拉取 datacenter 报表，返回原始 EM 列名的 DataFrame（行=报告期）。"""
    sc = _secucode(code_or_em)
    frames, page = [], 1
    while True:
        params = {
            "reportName": report_name, "columns": "ALL",
            "filter": f'(SECUCODE="{sc}")',
            "pageNumber": page, "pageSize": page_size,
            "sortColumns": "REPORT_DATE", "sortTypes": -1,
            "source": "HSF10", "client": "PC",
        }
        r = requests.get(DC_URL, params=params, timeout=20, headers=UA)
        r.raise_for_status()
        d = r.json()
        if not d.get("success") or not d.get("result"):
            break
        data = d["result"].get("data") or []
        frames.append(pd.DataFrame(data))
        if page >= d["result"].get("pages", 1):
            break
        page += 1
        time.sleep(0.3)
    if not frames:
        raise RuntimeError(f"datacenter 无数据: {report_name} {sc}")
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset="REPORT_DATE", keep="first")
    return df.sort_values("REPORT_DATE").reset_index(drop=True)


def fetch_em_income(code):   return fetch_dc_report(REPORT_INCOME, code)
def fetch_em_balance(code):  return fetch_dc_report(REPORT_BALANCE, code)
def fetch_em_cashflow(code): return fetch_dc_report(REPORT_CASHFLOW, code)


def fetch_segments(code_or_em: str) -> pd.DataFrame:
    """F10 主营构成 → 分部明细 DataFrame。

    返回列：report_date / dim(按行业|按产品|按地区) / item /
            income(亿元) / income_ratio / cost(亿元) / gross_margin
    同一报告期×维度下按收入降序；合计行（ITEM_NAME 含'合计'）剔除。
    """
    r = requests.get(F10_URL, params={"code": _f10_code(code_or_em)},
                     timeout=20, headers=UA)
    r.raise_for_status()
    d = r.json()
    rows = d.get("zygcfx") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"]).dt.strftime("%Y-%m-%d")
    df["item"] = df["ITEM_NAME"].astype(str).str.strip()
    df = df[~df["item"].str.contains("合计|补充", na=False)]
    income = pd.to_numeric(df["MAIN_BUSINESS_INCOME"], errors="coerce") / 1e8
    cost = pd.to_numeric(df["MAIN_BUSINESS_COST"], errors="coerce") / 1e8
    # 毛利率字段原始值口径不稳（实测偏小 100 倍），一律用 收入/成本 自算
    gm = (income - cost) / income.replace(0.0, pd.NA)
    out = pd.DataFrame({
        "report_date": df["REPORT_DATE"],
        "dim": df["MAINOP_TYPE"].astype(str).map(MAINOP_DIM).fillna(df["MAINOP_TYPE"].astype(str)),
        "item": df["item"],
        "income": income,
        "income_ratio": pd.to_numeric(df["MBI_RATIO"], errors="coerce"),
        "cost": cost,
        "gross_margin": gm,
    })
    out = out.dropna(subset=["income"])
    return out.sort_values(["report_date", "dim", "income"],
                           ascending=[True, True, False]).reset_index(drop=True)


def segments_pivot(seg: pd.DataFrame, dim: str = "按产品",
                   periods: int = 6) -> pd.DataFrame:
    """透视成 项目 × 报告期 的收入表（取最近 periods 个年报/中报期）。"""
    d = seg[seg["dim"] == dim]
    if d.empty:
        return d
    # 分部数据通常只有中报/年报；取最近 N 个报告期
    recent = sorted(d["report_date"].unique())[-periods:]
    d = d[d["report_date"].isin(recent)]
    return d.pivot_table(index="item", columns="report_date",
                         values="income", aggfunc="sum")


# ---------------- K线（push2his 行情接口，独立于 datacenter） ----------------

# secid 市场前缀：SH=1，SZ/BJ=0（与 datacenter 的 SECUCODE 格式不同）
KLT_MAP = {"daily": "101", "weekly": "102", "monthly": "103",
           "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
FQT_MAP = {"none": "0", "qfq": "1", "hfq": "2"}

# fields2 字段序：日期/开/收/高/低/量/额/振幅/涨跌幅/涨跌额/换手
_KLINE_COLS = ["date", "open", "close", "high", "low", "volume",
               "amount", "amplitude", "pct_chg", "chg", "turnover"]


def _secid(code_or_em: str) -> str:
    """push2his secid 格式：0.300274（深/北）/ 1.688345（沪）。"""
    num = _six_code(code_or_em)
    if num.startswith(("4", "8", "920")):   # 北交所 → 深系市场 0
        return f"0.{num}"
    if num.startswith(("6", "9")):
        return f"1.{num}"
    return f"0.{num}"


def fetch_kline(code_or_em: str, period: str = "daily", fqt: str = "qfq",
                beg: str = "0", end: str = "20500101") -> pd.DataFrame:
    """东财 push2his K线 → 标准 OHLCV DataFrame。

    参数:
        period: daily/weekly/monthly/5min/15min/30min/60min
        fqt:    none=不复权 / qfq=前复权 / hfq=后复权
        beg/end: '0'~'20500101' 全量；也可传 '20240101' 这类起始日
    返回列:
        date, open, close, high, low, volume(手), amount(元),
        amplitude(%), pct_chg(%), chg(元), turnover(%)
    """
    params = {
        "secid": _secid(code_or_em),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": KLT_MAP.get(period, period),
        "fqt": FQT_MAP.get(fqt, fqt),
        "beg": beg, "end": end,
        "lmt": "1000000",
    }
    d = None
    last_err: Exception | None = None
    for host in KLINE_HOSTS:                       # 主站+镜像轮换
        try:
            r = requests.get(host, params=params, timeout=20, headers=UA)
            r.raise_for_status()
            d = r.json()
            break
        except Exception as e:                     # noqa: BLE001
            last_err = e
            time.sleep(0.5)
    if d is None:
        raise RuntimeError(f"K线请求失败(已试{len(KLINE_HOSTS)}个host): {last_err}")
    klines = (d.get("data") or {}).get("klines") or []
    if not klines:
        raise RuntimeError(f"K线无数据: {code_or_em} {params['secid']}")
    rows = [ln.split(",") for ln in klines]
    df = pd.DataFrame(rows, columns=_KLINE_COLS)
    df["date"] = pd.to_datetime(df["date"])
    for c in _KLINE_COLS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
