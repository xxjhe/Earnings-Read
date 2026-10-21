#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fin_analyze — 公司财务分析脚本（复现 Wind《财务分析模型（季度）》全指标）。

用法:
    python fin_analyze.py 博力威                    # akshare/东方财富(免token)
    python fin_analyze.py 688345.SH                 # 代码亦可
    python fin_analyze.py 博力威 --source tushare --token <TOKEN>
    python fin_analyze.py 博力威 --qe               # 同时输出季度引擎明细CSV

输出:
    报告二_<公司名>_财务分析解读.html   自包含分析报告(年度+季度)
    output/<code>_annual.csv           年度全指标明细
    output/<code>_quarterly.csv        季度全指标明细
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from finmodel.datasource import fetch            # noqa: E402
from finmodel.engine import Engine               # noqa: E402
from finmodel.report import render_report2       # noqa: E402


def modules_to_frame(modules: dict) -> pd.DataFrame:
    rows = {}
    for mod in modules.values():
        for grp, label, s, fmt in mod.items:
            if isinstance(s, pd.Series):
                rows[f"{mod.name}|{grp}|{label}"] = s
    return pd.DataFrame(rows).T


def main():
    ap = argparse.ArgumentParser(description="公司财务分析（复现Wind财务分析模型）")
    ap.add_argument("company", help="公司名称或代码，如 博力威 / 688345 / 688345.SH")
    ap.add_argument("--source", default="akshare", choices=["akshare", "tushare", "em"],
                    help="em=东方财富 datacenter 直连（不经 akshare，可用于交叉验证）")
    ap.add_argument("--no-segments", action="store_true", help="不拉取东财F10分部数据")
    ap.add_argument("--token", default=None, help="tushare token（source=tushare 时需要）")
    ap.add_argument("--cqe", type=float, default=0.10, help="股权资金成本率假设，默认0.10")
    ap.add_argument("--out", default=None, help="输出 HTML 路径")
    args = ap.parse_args()

    print(f"[1/3] 拉取 {args.company} 财务数据（{args.source}）...")
    rs = fetch(args.company, source=args.source, token=args.token)
    name = rs.meta.get("name") or args.company
    print(f"      -> {rs.meta['code']} {name}，年度 {len(rs.annual['rev'])} 期，季度 {len(rs.quarterly['rev'])} 期")
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    code = rs.meta["code"].replace(".", "_")

    # 东财 F10 分部数据（主营构成：按产品/行业/地区 收入·成本·毛利率）
    if not args.no_segments:
        try:
            from finmodel.em_direct import fetch_segments
            seg = fetch_segments(rs.meta["code"])
            if not seg.empty:
                seg_path = out_dir / f"{code}_segments.csv"
                seg.to_csv(seg_path, index=False, encoding="utf-8-sig")
                latest = seg[seg["report_date"] == seg["report_date"].max()]
                top = latest[latest["dim"] == "按产品"].head(3)
                brief = "；".join(f"{r.item} {r.income:.1f}亿({r.income_ratio:.0%})"
                                  for r in top.itertuples())
                print(f"      -> 分部数据 {len(seg)} 行 -> {seg_path.name}")
                print(f"         最新期({seg['report_date'].max()})按产品: {brief}")
        except Exception as e:
            print(f"      -> [warn] 分部数据拉取失败（不影响主流程）: {e}", file=sys.stderr)

    print("[2/3] 运行计算引擎（年度 + 季度）...")
    eng_a = Engine(rs.annual, freq="A", cost_of_equity=args.cqe)
    mods_a = eng_a.run_all()
    eng_q = Engine(rs.quarterly, freq="Q", cost_of_equity=args.cqe)
    mods_q = eng_q.run_all()

    modules_to_frame(mods_a).to_csv(out_dir / f"{code}_annual.csv", encoding="utf-8-sig")
    modules_to_frame(mods_q).to_csv(out_dir / f"{code}_quarterly.csv", encoding="utf-8-sig")

    print("[3/3] 生成 HTML 分析报告...")
    label = f"{name}（{rs.meta['code']}）"
    html_text = render_report2(label, rs.meta, mods_a, mods_q,
                               raw_annual=rs.annual, raw_quarterly=rs.quarterly)
    out_html = Path(args.out) if args.out else ROOT / f"报告二_{name}_财务分析解读.html"
    out_html.write_text(html_text, encoding="utf-8")
    print(f"完成 -> {out_html}")
    print(f"明细 -> {out_dir / (code + '_annual.csv')} / {code + '_quarterly.csv'}")


if __name__ == "__main__":
    main()
