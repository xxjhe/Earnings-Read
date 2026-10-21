# -*- coding: utf-8 -*-
"""报告二生成器：公司财务分析解读 HTML（自包含，内嵌 ECharts）。

结构:
    1. 头部: 公司/代码/数据源/口径说明
    2. 核心结论 KPI 卡 + 自动解读文字
    3. 五大模块: 股权增加值 / 资产资本 / 现金流 / 债务 / 财务分析汇总
       每模块: 关键指标图表 + 全量指标表
    4. 季度跟踪: 近 13 个季度关键指标
    5. 附录: 数据口径与局限
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .chart_specs import SPECS, SKIPPED

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def _safe_div(a, b):
    """逐元素除法，0/NaN 分母 -> NaN。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    if isinstance(out, pd.Series):
        return out.replace([np.inf, -np.inf], np.nan)
    return out


def _fmt(v, fmt):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    if fmt == "pct":
        return f"{v * 100:,.2f}%"
    if fmt == "x":
        return f"{v:,.2f}"
    if fmt == "d":
        return f"{v:,.0f}"
    if fmt == "txt":
        return str(v)
    return f"{v:,.2f}"


def _num(v):
    return None if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else round(float(v), 6)


def _ser(s: pd.Series, fmt="yi"):
    """Series -> {"labels": [...], "values": [...]}，丢弃全 NaN 前缀年份。"""
    labels = [p[:4] if p.endswith("12-31") else p for p in s.index]
    vals = [_num(v) for v in s.values]
    return {"labels": labels, "values": vals}


def _chart(chart_id: str, title: str, series_list, y_fmt="yi", height=300):
    """series_list: [(name, {labels, values}, type)] type: bar/line"""
    return {"id": chart_id, "title": title, "series": [
        {"name": n, "data": d, "type": t} for n, d, t in series_list],
        "y_fmt": y_fmt, "height": height}


def _pct_text(v):
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v*100:.1f}%"


def _yi_text(v):
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.2f}亿"


def _latest(s: pd.Series, n=1):
    """倒数第 n 个非 NaN 值"""
    vals = s.dropna()
    return vals.iloc[-n] if len(vals) >= n else np.nan


class Interpret:
    """规则引擎: 根据最新年度指标生成解读段落。"""

    def __init__(self, modules: dict, meta: dict):
        self.m = modules
        self.meta = meta
        self.ev = modules["股权增加值分析"]
        self.ac = modules["资产资本分析"]
        self.cf = modules["现金流分析"]
        self.debt = modules["债务分析"]
        self.sm = modules["财务分析"]

    def g(self, mod, label, n=1):
        return _latest(mod.get(label), n)

    def run(self):
        out = []
        ev, ac, cf, debt, sm = self.ev, self.ac, self.cf, self.debt, self.sm

        # ---- 盈利与价值创造
        roe = self.g(ev, "ROE")
        roic = self.g(sm, "ROIC")
        eva = self.g(ev, "经济增加值EVA")
        noplat = self.g(ev, "NOPLAT")
        ebitda = self.g(ev, "EBITDA")
        paras = []
        if not np.isnan(roic):
            vs_cost = "高于" if roic > 0.10 else "低于"
            paras.append(f"最新年度投入资本回报率 ROIC 为 {_pct_text(roic)}，{vs_cost} 10% 的股权资金成本假设")
        if not np.isnan(eva):
            paras.append(f"经济增加值 EVA 为 {_yi_text(eva)}（{'为正，公司在创造超出资金成本的价值' if eva > 0 else '为负，当期利润未能覆盖股权资金成本'}）")
        if not np.isnan(roe):
            paras.append(f"ROE 为 {_pct_text(roe)}")
        if paras:
            out.append(("价值创造", "；".join(paras) + "。"))

        # ---- 成长性
        g_rev = self.g(ev, "营业收入增长率")
        rev = self.g(ev, "营业收入")
        g_np = self.g(ev, "归母净利润增速")
        np_now = self.g(ev, "归母净利润")
        np_prev = self.g(ev, "归母净利润", 2)
        paras = []
        if not np.isnan(g_rev):
            trend = ""
            g_prev = self.g(ev, "营业收入增长率", 2)
            if not np.isnan(g_prev):
                trend = "，增速较上期回升" if g_rev > g_prev else "，增速较上期放缓"
            word = "同比增长" if g_rev >= 0 else "同比下降"
            paras.append(f"营业收入 {_yi_text(rev)}，{word} {_pct_text(abs(g_rev))}{trend}")
        if not np.isnan(np_now) and not np.isnan(np_prev):
            if np_prev < 0 <= np_now:
                paras.append(f"归母净利润 {_yi_text(np_now)}，扭亏为盈（上年同期 {_yi_text(np_prev)}）")
            elif np_prev > 0 > np_now:
                paras.append(f"归母净利润 {_yi_text(np_now)}，由盈转亏（上年同期 {_yi_text(np_prev)}）")
            elif np_prev < 0 and np_now < 0:
                paras.append(f"归母净利润 {_yi_text(np_now)}，{'减亏' if np_now > np_prev else '增亏'}（上年同期 {_yi_text(np_prev)}）")
            elif not np.isnan(g_np):
                word = "增速" if g_np >= 0 else "降幅"
                paras.append(f"归母净利润{_yi_text(np_now)}，同比{word} {_pct_text(abs(g_np))}")
        if paras:
            out.append(("成长性", "；".join(paras) + "。"))

        # ---- 盈利质量
        eq_ = self.g(ev, "收益质量(非经常/净利润)")
        gm = self.g(ev, "毛利率")
        paras = []
        if not np.isnan(eq_):
            q = "收益主要来自经常性损益，质量较高" if abs(eq_) < 0.1 else ("非经常性损益占比较高，盈利质量需关注" if abs(eq_) < 0.3 else "盈利严重依赖非经常性损益")
            paras.append(f"非经常性损益占净利润 {_pct_text(eq_)}（{q}）")
        if not np.isnan(gm):
            paras.append(f"毛利率 {_pct_text(gm)}")
        impair_r = self.g(ev, "信用减值/应收类资产")
        if not np.isnan(impair_r) and impair_r > 0.05:
            paras.append(f"信用减值占应收类资产比例达 {_pct_text(impair_r)}，回款风险需要关注")
        if paras:
            out.append(("盈利质量", "；".join(paras) + "。"))

        # ---- 现金流
        cfo = self.g(cf, "经营活动现金流净额")
        fcf = self.g(cf, "自由现金流FCF")
        style = self.g(cf, "现金流风格八分类")
        suff = self.g(debt, "现金自给率")
        paras = []
        if not np.isnan(cfo):
            paras.append(f"经营现金流净额 {_yi_text(cfo)}")
        if not np.isnan(fcf):
            paras.append(f"自由现金流 FCF {_yi_text(fcf)}（{'为正，经营造血覆盖投资' if fcf > 0 else '为负，投资支出依赖外部筹资'}）")
        if isinstance(style, str) and style:
            paras.append(f"现金流风格为「{style}」")
        if not np.isnan(suff):
            paras.append(f"现金自给率 {_pct_text(suff)}")
        np_cash = self.g(cf, "净现比(CFO/净利润)")
        if not np.isnan(np_cash):
            q = ("利润有现金支撑" if np_cash >= 0.8 else
                 ("利润现金含量一般" if np_cash >= 0.5 else "利润与现金流背离，需核查应收/存货占用"))
            paras.append(f"净现比(CFO/净利润) {_pct_text(np_cash)}（{q}）")
        scr = self.g(cf, "销售收现比(收现/营业收入)")
        if not np.isnan(scr):
            paras.append(f"销售收现比 {_pct_text(scr)}（含税收现口径，持续大于1为正常，明显小于1提示收入现金含量不足）")
        if paras:
            out.append(("现金流", "；".join(paras) + "。"))

        # ---- 债务与偿债
        ibd_r = self.g(ac, "有息负债率")
        d_cost = self.g(debt, "税前债务成本")
        paras = []
        if not np.isnan(ibd_r):
            lvl = "杠杆较低" if ibd_r < 0.2 else ("杠杆适中" if ibd_r < 0.4 else "杠杆偏高")
            paras.append(f"有息负债率 {_pct_text(ibd_r)}（{lvl}）")
        if not np.isnan(d_cost) and not np.isnan(roic):
            spread = roic - d_cost
            paras.append(f"税前债务成本 {_pct_text(d_cost)}，ROIC 与债务成本利差 {_pct_text(spread)}"
                         f"（{'利差为正，加杠杆对股东有利' if spread > 0 else '利差为负，举债在侵蚀股东价值'}）")
        int_cover = self.g(debt, "利息保障倍数(EBITDA)")
        if not np.isnan(int_cover):
            lvl = ("利息覆盖充足" if int_cover >= 4 else
                   ("利息覆盖偏紧" if int_cover >= 2 else "EBITDA 难以覆盖利息支出，偿债压力大"))
            paras.append(f"利息保障倍数(EBITDA) {int_cover:.1f} 倍（{lvl}）")
        if paras:
            out.append(("债务与资本结构", "；".join(paras) + "。"))

        # ---- 营运效率
        op_cycle = self.g(ac, "营业周期")
        cash_cycle = self.g(ac, "现金周期")
        if not np.isnan(op_cycle):
            prev_cycle = self.g(ac, "营业周期", 2)
            trend = ""
            if not np.isnan(prev_cycle):
                delta = op_cycle - prev_cycle
                trend = f"，同比{'拉长' if delta > 0 else '缩短'} {abs(delta):.0f} 天"
            out.append(("营运效率", f"营业周期 {op_cycle:.0f} 天，现金周期 {cash_cycle:.0f} 天{trend}。"))
        return out


class Report2:
    def __init__(self, company_label: str, meta: dict,
                 annual: dict, quarterly: dict,
                 raw_annual: dict | None = None, raw_quarterly: dict | None = None):
        self.company = company_label
        self.meta = meta
        self.annual = annual      # modules dict (freq A)
        self.quarterly = quarterly  # modules dict (freq Q)
        self.raw = {"A": raw_annual or {}, "Q": raw_quarterly or {}}
        self.charts = []          # 全部图表（规格驱动）
        self.chart_secs = []      # [(sec, freq, [chart])] 保持 SPECS 顺序

    # ---------------- 引用解析 ----------------
    def _resolve(self, ref, freq: str):
        """chart_specs 引用 -> pd.Series（或标量）。"""
        kind = ref[0]
        if kind == "e":
            mod = (self.annual if freq == "A" else self.quarterly).get(ref[1])
            return mod.get(ref[2]) if mod else None
        if kind == "r":
            return self.raw[freq].get(ref[1])
        if kind == "const":
            return float(ref[1])
        if kind == "neg":
            a = self._resolve(ref[1][0], freq)
            return -a if a is not None else None
        args = [self._resolve(x, freq) for x in ref[1]]
        if any(a is None for a in args):
            return None
        if kind == "add":
            out = args[0]
            for a in args[1:]:
                out = out + a
            return out
        if kind == "sub":
            out = args[0]
            for a in args[1:]:
                out = out - a
            return out
        if kind == "mul":
            out = args[0]
            for a in args[1:]:
                out = out * a
            return out
        if kind == "div":
            return _safe_div(args[0], args[1])
        if kind == "yoy":                       # 同比: 年度=1期, 季度=4期
            lag = 1 if freq == "A" else 4
            return _safe_div(args[0], args[0].shift(lag)) - 1
        if kind == "qoq":
            return _safe_div(args[0], args[0].shift(1)) - 1
        if kind == "diff":
            return args[0] - args[0].shift(1)
        if kind == "avg2":
            return (args[0] + args[0].shift(1)) / 2
        return None

    # ---------------- 图表 ----------------
    def _build_charts(self):
        self.charts, self.chart_secs = [], []
        for spec in SPECS:
            freq = spec["freq"]
            n_cats = 11 if freq == "A" else 13
            series_out = []
            cats = None
            for name, kind, fmt, ref in spec["series"]:
                s = self._resolve(ref, freq)
                if s is None or not isinstance(s, pd.Series):
                    continue
                s = s.dropna()
                if s.empty:
                    continue
                s = s.iloc[-n_cats:]
                if cats is None or len(s.index) > len(cats):
                    cats = list(s.index)
                series_out.append((name, kind, fmt, s))
            if not series_out or cats is None:
                continue
            cats = cats[-n_cats:]
            labels = ([c[:4] for c in cats] if freq == "A"
                      else [c[2:7].replace("-", "Q") for c in cats])
            fmts = {f for _, _, f, _ in series_out}
            dual = "pct" in fmts and len(fmts) > 1
            chart_series = []
            for name, kind, fmt, s in series_out:
                chart_series.append({
                    "name": name,
                    "type": ("line" if kind == "area" else kind),
                    "area": kind == "area",
                    "stack": bool(spec["stack"] and kind in ("bar", "area")),
                    "pct": fmt == "pct",
                    "yaxis": 1 if (dual and fmt == "pct") else 0,
                    "values": [_num(s.get(c)) for c in cats],
                })
            chart = {"id": f"{spec['id']}", "title": spec["title"], "labels": labels,
                     "series": chart_series, "dual": dual,
                     "left_pct": (not dual and "pct" in fmts),
                     "height": 300, "stack": spec["stack"]}
            self.charts.append(chart)
            self.chart_secs.append((spec["sec"], freq, chart))

    def _charts_of(self, sec: str) -> list:
        return [c for s, _, c in self.chart_secs if s == sec]

    @staticmethod
    def _gallery(charts, h3=False):
        if not charts:
            return ""
        tag = "h3" if h3 else "h2"
        title = "图表" if h3 else "图表总览"
        s = f"<{tag}>{title}</{tag}><div class='grid2'>"
        for c in charts:
            s += (f'<div class="chart"><div class="ct">{html.escape(c["title"])}</div>'
                  f'<div id="{c["id"]}" style="width:100%;height:{c["height"]}px"></div></div>')
        return s + "</div>"

    def _head(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(self.company)} · 财务分析报告</title>
<script>{ASSETS.joinpath('echarts.min.js').read_text(encoding='utf-8')}</script>
<style>
:root {{ --ink:#1a2233; --sub:#5a6478; --line:#e5e9f2; --accent:#2563eb; --good:#0e9f6e; --bad:#e02424; }}
* {{ box-sizing:border-box; }}
body {{ font-family:"Microsoft YaHei","PingFang SC",sans-serif; color:var(--ink); margin:0; background:#f6f8fb; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:32px 24px 64px; }}
h1 {{ font-size:26px; margin:0 0 6px; }}
.sub {{ color:var(--sub); font-size:13px; margin-bottom:24px; }}
h2 {{ font-size:19px; margin:38px 0 4px; border-left:4px solid var(--accent); padding-left:10px; }}
h3 {{ font-size:15px; color:var(--sub); margin:18px 0 8px; font-weight:600; }}
.note {{ color:var(--sub); font-size:12.5px; margin:2px 0 14px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:18px 0; }}
.card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.card .t {{ font-size:12.5px; color:var(--sub); }}
.card .v {{ font-size:21px; font-weight:700; margin:4px 0 2px; }}
.card .s {{ font-size:11.5px; color:var(--sub); }}
.interp {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:6px 20px 12px; }}
.interp li {{ margin:8px 0; line-height:1.75; font-size:14px; }}
.interp b {{ color:var(--accent); }}
table {{ border-collapse:collapse; width:100%; background:#fff; font-size:12.5px; margin:10px 0 20px; }}
th, td {{ border:1px solid var(--line); padding:5px 8px; text-align:right; white-space:nowrap; }}
th {{ background:#eef2f9; font-weight:600; }}
td:first-child, th:first-child {{ text-align:left; position:sticky; left:0; background:#f9fafc; }}
tr:hover td {{ background:#f2f6ff; }}
.tbl-wrap {{ overflow-x:auto; border-radius:8px; }}
.chart {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:10px 6px 2px; margin:12px 0; }}
.chart .ct {{ font-size:13px; font-weight:600; color:var(--ink); padding:2px 8px 0; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media (max-width:900px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
.grp {{ background:#eef2f9 !important; font-weight:700; }}
.pos {{ color:var(--good); }} .neg {{ color:var(--bad); }}
.footer {{ margin-top:44px; color:var(--sub); font-size:12px; line-height:1.9; }}
</style></head><body><div class="wrap">
<h1>{html.escape(self.company)} · 财务分析报告</h1>
<div class="sub">代码 {html.escape(self.meta.get('code',''))} ｜ 数据源 {html.escape(self.meta.get('source',''))} ｜
单位: 亿元人民币 ｜ 生成时间 {now} ｜ 计算引擎复现自《财务分析模型（季度）》Wind 版公式</div>
"""

    def _kpi_html(self, kpis):
        s = '<div class="cards">'
        for t, v, sub in kpis:
            s += f'<div class="card"><div class="t">{html.escape(t)}</div><div class="v">{html.escape(str(v))}</div><div class="s">{html.escape(str(sub))}</div></div>'
        return s + "</div>"

    def _interp_html(self, interp):
        s = "<h2>核心解读</h2><div class='interp'><ul>"
        for title, text in interp:
            s += f"<li><b>{html.escape(title)}</b> — {html.escape(text)}</li>"
        return s + "</ul></div>"

    def _module_html(self, name, mod):
        s = f"<h2>{html.escape(name)}</h2>"
        # 表格: 分组 -> 指标行
        periods = [p for p in mod.items[0][2].index] if mod.items and isinstance(mod.items[0][2], pd.Series) else []
        cols = [p[:4] if p.endswith("12-31") else p for p in periods]
        s += '<div class="tbl-wrap"><table><thead><tr><th>指标</th>' + "".join(
            f"<th>{html.escape(c)}</th>" for c in cols) + "</tr></thead><tbody>"
        last_grp = None
        for grp, label, ser, fmt in mod.items:
            if not isinstance(ser, pd.Series):
                continue
            if ser.dropna().empty:
                continue
            if grp != last_grp:
                s += f'<tr class="grp"><td colspan="{len(cols)+1}">{html.escape(grp)}</td></tr>'
                last_grp = grp
            row = f"<td>{html.escape(label)}</td>"
            for v in ser.values:
                txt = _fmt(v, fmt)
                cls = ""
                if isinstance(v, (int, float)) and not np.isnan(v) and fmt in ("yi", "pct"):
                    cls = ' class="neg"' if v < 0 else ""
                row += f"<td{cls}>{txt}</td>"
            s += row + "</tr>"
        s += "</tbody></table></div>"
        return s

    def _quarterly_html(self):
        qev = self.quarterly["股权增加值分析"]
        qac = self.quarterly["资产资本分析"]
        qcf = self.quarterly["现金流分析"]
        keep = [
            ("股权增加值分析", qev, ["营业收入", "营业收入增长率", "毛利率", "息税前经营利润",
                                     "EBIT", "NOPLAT", "归母净利润", "扣非净利润", "ROE"]),
            ("资产资本分析", qac, ["有息负债合计", "有息负债率", "营业周期", "现金周期"]),
            ("现金流分析", qcf, ["经营活动现金流净额", "自由现金流FCF", "现金流风格八分类"]),
        ]
        s = "<h2>季度跟踪</h2><div class='note'>单季口径；增长率为同比（上年同季）。</div>"
        for _, mod, labels in keep:
            items = [it for it in mod.items if it[1] in labels]
            if not items:
                continue
            periods = list(items[0][2].index)[-13:]
            s += "<h3>" + html.escape(mod.name) + "</h3>"
            s += '<div class="tbl-wrap"><table><thead><tr><th>指标</th>' + "".join(
                f"<th>{html.escape(p[2:7].replace('-', 'Q'))}</th>" for p in periods) + "</tr></thead><tbody>"
            for grp, label, ser, fmt in items:
                s += f"<td>{html.escape(label)}</td>"
                for p in periods:
                    v = ser.get(p, np.nan)
                    s += f"<td>{_fmt(v, fmt)}</td>"
                s += "</tr>"
            s += "</tbody></table></div>"
        return s

    def _appendix_html(self):
        skipped = "".join(f"<li><b>{html.escape(k)}</b>：{html.escape(v)}</li>" for k, v in SKIPPED)
        return f"""<h2>附录 · 口径与局限</h2>
<div class="footer">
<p>1. 计算引擎 1:1 复现原 Wind 模型的公式链（含其特有口径：营运资本净额计入资产总额、应付周转不做两期平均、
非流动其他负债与租赁负债的轻微重复计算等）。股权资金成本率假设 10%。图表按原模型 112 张图逐项比对复现，
重复图已合并（原 chart87/121/157/159/49/108），以下原图因数据在公开接口不可得而未复现：</p>
<ul style="font-size:12px; line-height:1.8">{skipped}</ul>
<p>2. 资产结构与资本结构图按累计柱状图（堆叠）展示，与原表各构成项口径一致
（资产结构区「营运资产」按原表 r55 口径 = 营运资产合计-营运负债，即净额）；
营运资产/营运负债/长期经营资产构成图保留原表的分组柱状样式。</p>
<p>3. 研发投入原表用报表附注（费用化+资本化），公开数据源回退为利润表研发费用；
派现为现金流近似（分配股利利息支付-利息支出）。</p>
<p>4. 原表季度版股权资金成本/EVA 存在列错位引用（引用年度表固定列），本脚本按当期股东权益×10%修正。</p>
<p>5. 附注专有数据（坏账准备、固定资产原值、商誉减值准备、授信额度等）公开接口无法获取，相关指标不输出。</p>
<p>6. 季度版长期有息负债 = 长期借款+应付债券+租赁负债；年度版另含长期应付款（均与原表一致）。</p>
<p>7. 「费用率」「利润含金量」「偿债能力」及资产/资本结构占比组为按《财务报表分析与股票估值》框架
补充的解读指标（原 Wind 模型未单列）；其中购货付现比分母沿用原模型收入/成本分析表的 17% 增值税假设。
原模型「收入分析」「成本分析」表的分部数据（按品种/地区）依赖 Wind 终端函数；2026-10-12 起已通过
东方财富 F10 接口（finmodel/em_direct.py）补充分部数据，输出至 output/{{代码}}_segments.csv
（按产品/行业/地区的收入·成本·毛利率），暂未并入本报告图表。</p>
</div>"""

def render_report2(company_label, meta, annual_modules, quarterly_modules,
                   raw_annual=None, raw_quarterly=None) -> str:
    r = Report2(company_label, meta, annual_modules, quarterly_modules,
                raw_annual, raw_quarterly)
    r._build_charts()
    interp = Interpret(annual_modules, meta).run()
    ev = annual_modules["股权增加值分析"]
    sm = annual_modules["财务分析"]
    cf = annual_modules["现金流分析"]
    ac = annual_modules["资产资本分析"]
    kpis = [
        ("营业收入", _fmt(_latest(ev.get("营业收入")), "yi") + " 亿", _fmt(_latest(ev.get("营业收入增长率")), "pct") + " 同比"),
        ("归母净利润", _fmt(_latest(ev.get("归母净利润")), "yi") + " 亿", _fmt(_latest(ev.get("归母净利润增速")), "pct") + " 同比"),
        ("ROE", _fmt(_latest(ev.get("ROE")), "pct"), "净利润/股东权益"),
        ("ROIC", _fmt(_latest(sm.get("ROIC")), "pct"), "NOPLAT/净经营资产"),
        ("EVA", _fmt(_latest(ev.get("经济增加值EVA")), "yi") + " 亿", "净利润-权益×10%"),
        ("FCFF", _fmt(_latest(sm.get("FCFF")), "yi") + " 亿", "EBITDA-税-Δ营运-扩张"),
        ("有息负债率", _fmt(_latest(ac.get("有息负债率")), "pct"), "有息/资本总额"),
        ("现金流风格", str(_latest(cf.get("现金流风格八分类")) or "—"), "经营/投资/筹资符号"),
    ]
    parts = [r._head(), r._kpi_html(kpis), r._interp_html(interp)]
    # 报表概览（利润表/现金流量表口径图）
    ov = r._charts_of("报表概览")
    if ov:
        parts.append("<h2>报表概览</h2>")
        parts.append(Report2._gallery(ov, h3=True))
    # 五大模块：全量指标表 + 本模块全部图表
    for name in ["股权增加值分析", "资产资本分析", "现金流分析", "债务分析", "财务分析"]:
        parts.append(r._module_html(name, annual_modules[name]))
        parts.append(Report2._gallery(r._charts_of(name), h3=True))
    # 季度跟踪：表 + 季度图（按子章节分组）
    parts.append(r._quarterly_html())
    for sec in ["季度-报表", "季度-股权增加值分析", "季度-资产资本分析", "季度-现金流分析"]:
        charts = r._charts_of(sec)
        if charts:
            parts.append(f"<h3>{html.escape(sec.replace('季度-', '季度 · '))} 图表</h3>")
            parts.append("<div class='grid2'>" + "".join(
                f'<div class="chart"><div class="ct">{html.escape(c["title"])}</div>'
                f'<div id="{c["id"]}" style="width:100%;height:{c["height"]}px"></div></div>'
                for c in charts) + "</div>")
    parts.append(r._appendix_html())
    # ECharts 初始化 JS
    parts.append("<script>const C=" + json.dumps(r.charts, ensure_ascii=False) + ";")
    parts.append("""
const fmtVal = (v, pct) => v == null ? "—" : (pct ? (v*100).toFixed(1)+"%" : (+v).toLocaleString("zh-CN",{maximumFractionDigits:2}));
for (const c of C) {
  const el = document.getElementById(c.id);
  if (!el) continue;
  const ch = echarts.init(el);
  const yAxis = [
    {type: "value", axisLabel: {formatter: v => c.left_pct ? (v*100).toFixed(0)+"%" : v}}
  ];
  if (c.dual) yAxis.push({type: "value", axisLabel: {formatter: v => (v*100).toFixed(0)+"%"}});
  const opt = {
    tooltip: {trigger: "axis", valueFormatter: null},
    legend: {bottom: 0, textStyle: {fontSize: 11}, type: "scroll"},
    grid: {left: 56, right: c.dual ? 56 : 20, top: 18, bottom: 58},
    xAxis: {type: "category", data: c.labels, axisLabel: {fontSize: 10, margin: 12}},
    yAxis: yAxis,
    series: c.series.map(s => ({
      name: s.name, type: s.type, data: s.values, smooth: s.type==="line" && !s.area,
      yAxisIndex: s.yaxis, stack: s.stack ? "total" : undefined,
      areaStyle: s.area ? {opacity: 0.55} : undefined,
      emphasis: {focus: "series"}
    })),
    color: ["#2563eb","#f59e0b","#0e9f6e","#8b5cf6","#e02424","#0891b2","#db2777","#65a30d","#f97316"]
  };
  ch.setOption(opt);
  window.addEventListener("resize", () => ch.resize());
}
</script></div></body></html>""")
    return "".join(parts)
