# -*- coding: utf-8 -*-
"""数据获取层：公司名/代码 -> 标准化三大报表（亿元）。

数据源:
    akshare (默认): 东方财富报表接口，免 token。
    tushare (可选): 需设置环境变量 TUSHARE_TOKEN 或传入 token（需 2000+ 积分）。

输出结构 RawStatements:
    annual / quarterly: 每个都是 dict[str, pd.Series]，键为标准字段名，
        Series 的 index 为报告期 'YYYY-MM-DD'（升序）。
        annual    -> 年度口径（利润表/现金流为全年累计，资产负债表为期末时点）
        quarterly -> 单季口径（利润表/现金流由 YTD 差分得到，资产负债表为期末时点）
    meta: 公司代码、名称、数据源等。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

YI = 1e8  # 元 -> 亿元

# ---------------------------------------------------------------------------
# 标准字段定义: canon_name -> (源字段列表(按优先级), 符号变换)
#   符号变换: None 原值; "neg" 取负
# 资产负债表 / 利润表 / 现金流量表(含补充资料) 共用一套 canon 命名。
# ---------------------------------------------------------------------------

# 利润表 (income statement)
IS_MAP = {
    "rev_total":       ["TOTAL_OPERATE_INCOME"],          # 营业总收入
    "rev":             ["OPERATE_INCOME"],                # 营业收入
    "cost":            ["OPERATE_COST"],                  # 营业成本
    "tax_surcharge":   ["OPERATE_TAX_ADD"],               # 税金及附加
    "sell_exp":        ["SALE_EXPENSE"],                  # 销售费用
    "manage_exp_raw":  ["MANAGE_EXPENSE"],                # 管理费用(报表口径)
    "rd_exp":          ["RESEARCH_EXPENSE"],              # 研发费用(报表口径)
    "fin_exp":         ["FINANCE_EXPENSE"],               # 财务费用
    "int_exp":         ["FE_INTEREST_EXPENSE"],           # 其中:利息费用
    "int_inc":         ["FE_INTEREST_INCOME"],            # 其中:利息收入
    "impair_asset":    [("ASSET_IMPAIRMENT_INCOME", "neg")],   # 资产减值损失(损失为正)
    "impair_credit":   [("CREDIT_IMPAIRMENT_INCOME", "neg")],  # 信用减值损失(损失为正)
    "fv_change":       ["FAIRVALUE_CHANGE_INCOME"],       # 公允价值变动收益
    "invest_income":   ["INVEST_INCOME"],                 # 投资净收益
    "exchange_income": ["EXCHANGE_INCOME"],               # 汇兑收益
    "asset_disposal":  ["ASSET_DISPOSAL_INCOME"],         # 资产处置收益
    "other_income":    ["OTHER_INCOME"],                  # 其他收益
    "op_profit":       ["OPERATE_PROFIT"],                # 营业利润
    "non_op_income":   ["NONBUSINESS_INCOME"],            # 营业外收入
    "non_op_exp":      ["NONBUSINESS_EXPENSE"],           # 营业外支出
    "total_profit":    ["TOTAL_PROFIT"],                  # 利润总额
    "income_tax":      ["INCOME_TAX"],                    # 所得税
    "net_profit":      ["NETPROFIT"],                     # 净利润
    "np_parent":       ["PARENT_NETPROFIT"],              # 归母净利润
    "np_deducted":     ["DEDUCT_PARENT_NETPROFIT"],       # 扣非归母净利润
    "minority_pl":     ["MINORITY_INTEREST"],             # 少数股东损益
}

# 资产负债表 (balance sheet)
BS_MAP = {
    "cash":            ["MONETARYFUNDS"],                 # 货币资金
    "trade_fa":        ["TRADE_FINASSET"],                # 交易性金融资产
    "note_rece":       ["NOTE_RECE"],                     # 应收票据
    "ar":              ["ACCOUNTS_RECE"],                 # 应收账款
    "rece_financing":  ["FINANCE_RECE"],                  # 应收款项融资
    "prepay":          ["PREPAYMENT"],                    # 预付款项
    "other_rece":      ["OTHER_RECE"],                    # 其他应收款
    "inventory":       ["INVENTORY"],                     # 存货
    "contract_asset":  ["CONTRACT_ASSET"],                # 合同资产
    "total_ca":        ["TOTAL_CURRENT_ASSETS"],          # 流动资产合计
    "afs_fa":          ["AVAILABLE_SALE_FINASSET"],       # 可供出售金融资产(旧准则)
    "htm_invest":      ["HOLD_MATURITY_INVEST"],          # 持有至到期投资(旧准则)
    "long_rece":       ["LONG_RECE"],                     # 长期应收款
    "lt_eq_invest":    ["LONG_EQUITY_INVEST"],            # 长期股权投资
    "invest_re":       ["INVEST_REALESTATE"],             # 投资性房地产
    "fixed_asset":     ["FIXED_ASSET"],                   # 固定资产(净额,见后合并清理)
    "fa_cleanup":      ["FIXED_ASSET_DISPOSAL"],          # 固定资产清理
    "cip":             ["CIP"],                           # 在建工程(净额,见后合并工程物资)
    "proj_material":   ["PROJECT_MATERIAL"],              # 工程物资
    "oil_gas":         ["OIL_GAS_ASSET"],                 # 油气资产
    "bio_asset":       ["PRODUCTIVE_BIOLOGY_ASSET"],      # 生产性生物资产
    "intangible":      ["INTANGIBLE_ASSET"],              # 无形资产
    "dev_exp":         ["DEVELOP_EXPENSE"],               # 开发支出
    "goodwill":        ["GOODWILL"],                      # 商誉
    "lt_prepaid":      ["LONG_PREPAID_EXPENSE"],          # 长期待摊费用
    "total_nca":       ["TOTAL_NONCURRENT_ASSETS"],       # 非流动资产合计
    "total_assets":    ["TOTAL_ASSETS"],                  # 资产总计
    "st_loan":         ["SHORT_LOAN"],                    # 短期借款
    "note_pay":        ["NOTE_PAYABLE"],                  # 应付票据
    "ap":              ["ACCOUNTS_PAYABLE"],              # 应付账款
    "advance_rece":    ["ADVANCE_RECEIVABLES"],           # 预收款项
    "contract_liab":   ["CONTRACT_LIAB"],                 # 合同负债
    "payroll":         ["STAFF_SALARY_PAYABLE"],          # 应付职工薪酬
    "tax_pay":         ["TAX_PAYABLE"],                   # 应交税费
    "ncl_1y":          ["NONCURRENT_LIAB_1YEAR"],         # 一年内到期的非流动负债
    "accrued_exp":     ["ACCRUED_EXPENSE"],               # 预提费用
    "st_bond":         ["SHORT_BOND_PAYABLE"],            # 应付短期债券
    "total_cl":        ["TOTAL_CURRENT_LIAB"],            # 流动负债合计
    "other_cl_line":   ["OTHER_CURRENT_LIAB"],            # 其他流动负债(报表行)
    "other_ncl_line":  ["OTHER_NONCURRENT_LIAB"],         # 其他非流动负债(报表行)
    "lt_loan":         ["LONG_LOAN"],                     # 长期借款
    "bond_pay":        ["BOND_PAYABLE"],                  # 应付债券
    "lease_liab":      ["LEASE_LIAB"],                    # 租赁负债
    "lt_payable":      ["LONG_PAYABLE"],                  # 长期应付款
    "total_ncl":       ["TOTAL_NONCURRENT_LIAB"],         # 非流动负债合计
    "total_liab":      ["TOTAL_LIABILITIES"],             # 负债合计
    "share_capital":   ["SHARE_CAPITAL"],                 # 股本
    "cap_reserve":     ["CAPITAL_RESERVE"],               # 资本公积
    "treasury":        ["TREASURY_SHARES"],               # 库存股
    "surplus_reserve": ["SURPLUS_RESERVE"],               # 盈余公积
    "undistributed":   ["UNASSIGN_RPOFIT"],               # 未分配利润
    "minority_eq":     ["MINORITY_EQUITY"],               # 少数股东权益
    "parent_eq":       ["TOTAL_PARENT_EQUITY"],           # 归母股东权益
    "total_eq":        ["TOTAL_EQUITY"],                  # 股东权益合计
}

# 现金流量表 (cash flow, 含补充资料)
CF_MAP = {
    "sales_cash":      ["SALES_SERVICES"],                # 销售商品提供劳务收到的现金
    "buy_services":    ["BUY_SERVICES"],                  # 购买商品接受劳务支付的现金
    "cfo":             ["NETCASH_OPERATE"],               # 经营活动现金流净额
    "withdraw_invest": ["WITHDRAW_INVEST"],               # 收回投资收到的现金
    "invest_income_cash": ["RECEIVE_INVEST_INCOME"],      # 取得投资收益收到的现金
    "disposal_lt_asset": ["DISPOSAL_LONG_ASSET"],         # 处置固定资产等收回的现金
    "disposal_sub":    ["DISPOSAL_SUBSIDIARY_OTHER"],     # 处置子公司收到的现金
    "other_invest_in": ["RECEIVE_OTHER_INVEST"],          # 收到其他与投资活动有关的现金
    "capex":           ["CONSTRUCT_LONG_ASSET"],          # 购建固定资产等支付的现金
    "invest_pay":      ["INVEST_PAY_CASH"],               # 投资支付的现金
    "acquire_sub":     ["OBTAIN_SUBSIDIARY_OTHER"],       # 取得子公司支付的现金
    "other_invest_out": ["PAY_OTHER_INVEST"],             # 支付其他与投资活动有关的现金
    "cfi":             ["NETCASH_INVEST"],                # 投资活动现金流净额
    "accept_invest":   ["ACCEPT_INVEST_CASH"],            # 吸收投资收到的现金
    "borrow_in":       ["RECEIVE_LOAN_CASH"],             # 取得借款收到的现金
    "bond_in":         ["ISSUE_BOND"],                    # 发行债券收到的现金
    "other_fin_in":    ["RECEIVE_OTHER_FINANCE"],         # 收到其他与筹资活动有关的现金
    "repay_debt":      ["PAY_DEBT_CASH"],                 # 偿还债务支付的现金
    "div_int_paid":    ["ASSIGN_DIVIDEND_PORFIT"],        # 分配股利利润或偿付利息支付的现金
    "other_fin_out":   ["PAY_OTHER_FINANCE"],             # 支付其他与筹资活动有关的现金
    "cff":             ["NETCASH_FINANCE"],               # 筹资活动现金流净额
    "fx_effect":       ["RATE_CHANGE_EFFECT"],            # 汇率变动影响
    "cce_add":         ["CCE_ADD"],                       # 现金及现金等价物净增加额
    # 补充资料
    "impair_provision": ["ASSET_IMPAIRMENT"],             # 资产减值准备(补充资料)
    "depr":            ["FA_IR_DEPR"],                    # 固定资产折旧等
    "amort_ia":        ["IA_AMORTIZE"],                   # 无形资产摊销
    "amort_lpe":       ["LPE_AMORTIZE"],                  # 长期待摊费用摊销
    "disposal_loss":   ["DISPOSAL_LONGASSET_LOSS"],       # 处置长期资产损失
    "scrap_loss":      ["FA_SCRAP_LOSS"],                 # 固定资产报废损失
}

# tushare 映射 (canon -> tushare 字段; 特殊处理在代码中)
TS_IS_MAP = {
    "rev_total": "total_revenue", "rev": "revenue", "cost": "oper_cost",
    "tax_surcharge": "biz_tax_surchg", "sell_exp": "sell_exp",
    "manage_exp_raw": "admin_exp", "rd_exp": "rd_exp", "fin_exp": "fin_exp",
    "int_exp": "fin_exp_int_exp", "int_inc": "fin_exp_int_inc",
    "fv_change": "fv_value_chg_gain", "invest_income": "invest_income",
    "asset_disposal": "asset_disp_income", "other_income": "oth_income",
    "op_profit": "operate_profit", "non_op_income": "non_oper_income",
    "non_op_exp": "non_oper_exp", "total_profit": "total_profit",
    "income_tax": "income_tax", "net_profit": "n_income",
    "np_parent": "n_income_attr_p", "minority_pl": "minority_gain",
}
TS_BS_MAP = {
    "cash": "money_cap", "trade_fa": "trad_asset", "note_rece": "notes_receiv",
    "ar": "accounts_receiv", "rece_financing": "receiv_financing",
    "prepay": "prepayment", "other_rece": "oth_receiv", "inventory": "inventories",
    "contract_asset": "contract_assets", "total_ca": "total_cur_assets",
    "afs_fa": "fa_avail_for_sale", "htm_invest": "htm_invest", "long_rece": "lt_rec",
    "lt_eq_invest": "lt_eqt_invest", "invest_re": "invest_real_estate",
    "fixed_asset": "fix_assets_total", "cip": "cip_total",
    "fixed_detail": "fix_assets", "cip_detail": "cip",
    "fa_cleanup": "fix_assets_disp", "proj_material": "proj_mat",
    "oil_gas": "oil_and_gas_assets", "bio_asset": "produc_bio_assets",
    "intangible": "intan_assets", "dev_exp": "r_and_d", "goodwill": "goodwill",
    "lt_prepaid": "lt_amor_exp", "total_nca": "total_nca", "total_assets": "total_assets",
    "st_loan": "st_borr", "note_pay": "notes_payable", "ap": "acct_payable",
    "advance_rece": "adv_receipts", "contract_liab": "contract_liab",
    "payroll": "payroll_payable", "tax_pay": "taxes_payable",
    "ncl_1y": "non_cur_liab_due_1y", "accrued_exp": "acc_exp",
    "st_bond": "st_bonds_payable", "total_cl": "total_cur_liab",
    "other_cl_line": "oth_cur_liab", "other_ncl_line": "oth_ncl",
    "lt_loan": "lt_borr", "bond_pay": "bond_payable", "lease_liab": "lease_liab",
    "lt_payable": "lt_payable", "total_ncl": "total_ncl", "total_liab": "total_liab",
    "share_capital": "total_share", "cap_reserve": "cap_rese",
    "treasury": "treasury_share", "surplus_reserve": "surplus_rese",
    "undistributed": "undistr_porfit", "minority_eq": "minority_int",
    "parent_eq": "total_hldr_eqy_exc_min_int", "total_eq": "total_hldr_eqy_inc_min_int",
}
TS_CF_MAP = {
    "sales_cash": "c_fr_sale_sg", "buy_services": "c_pay_goods_purch_ser",
    "cfo": "n_cashflow_act",
    "withdraw_invest": "c_disp_withdrwl_invest", "invest_income_cash": "c_recp_return_invest",
    "disposal_lt_asset": "n_recp_disp_fiolta", "disposal_sub": "n_recp_disp_sobu",
    "other_invest_in": "oth_recp_ral_inv_act", "capex": "c_pay_acq_const_fiolta",
    "invest_pay": "c_paid_invest", "acquire_sub": "n_disp_subs_oth_biz",
    "other_invest_out": "oth_pay_ral_inv_act", "cfi": "n_cashflow_inv_act",
    "accept_invest": "c_recp_cap_contrib", "borrow_in": "c_recp_borrow",
    "bond_in": "proc_issue_bonds", "other_fin_in": "oth_cash_recp_ral_fnc_act",
    "repay_debt": "c_prepay_amt_borr", "div_int_paid": "c_pay_dist_dpcp_int_exp",
    "other_fin_out": "oth_cashpay_ral_fnc_act", "cff": "n_cash_flows_fnc_act",
    "fx_effect": "eff_fx_flu_cash", "cce_add": "n_incr_cash_cash_equ",
    "impair_provision": "prov_depr_assets", "depr": "depr_fa_coga_dpba",
    "amort_ia": "amort_intang_assets", "amort_lpe": "lt_amort_deferred_exp",
    "disposal_loss": "loss_disp_fiolta", "scrap_loss": "loss_scr_fa",
}


@dataclass
class RawStatements:
    annual: dict = field(default_factory=dict)      # canon -> pd.Series (年末累计/期末)
    quarterly: dict = field(default_factory=dict)   # canon -> pd.Series (单季/季末)
    meta: dict = field(default_factory=dict)


def _norm_code(code_or_name: str) -> tuple[str, str, str]:
    """接受 '博力威' / '688345' / '688345.SH' / 'SH688345'，返回 (EM代码, ts_code, 名称)。

    注：北交所新代码段 920xxx 以 9 开头（易被误判为沪市），统一在此识别为 BJ。
    """

    def ex_of(num: str) -> str:
        if num.startswith(("4", "8", "920")):
            return "BJ"
        if num.startswith(("6", "9")):
            return "SH"
        return "SZ"

    s = str(code_or_name).strip()
    m = re.fullmatch(r"(\d{6})(?:\.(SH|SZ|BJ))?", s, re.I)
    if m:
        num, ex = m.group(1), (m.group(2) or "").upper()
        if not ex:
            ex = ex_of(num)
        return ex + num, num + "." + ex, ""
    m = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", s, re.I)
    if m:
        ex, num = m.group(1).upper(), m.group(2)
        return ex + num, num + "." + ex, ""
    # 按名称查找
    import akshare as ak
    df = ak.stock_info_a_code_name()
    hit = df[df["name"] == s]
    if hit.empty:
        hit = df[df["name"].str.contains(re.escape(s), na=False)]
    if hit.empty:
        raise ValueError(f"找不到公司: {code_or_name}")
    num = hit.iloc[0]["code"]
    ex = ex_of(num)
    return ex + num, num + "." + ex, hit.iloc[0]["name"]


def _canon_from_em(df: pd.DataFrame, mapping: dict) -> dict:
    """EM DataFrame (行=报告期) -> canon dict of pd.Series (亿元)。"""
    df = df.copy()
    df["R"] = pd.to_datetime(df["REPORT_DATE"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("R").drop_duplicates(subset="R", keep="last").set_index("R")
    out = {}
    for canon, sources in mapping.items():
        ser = None
        for src in sources:
            name, sign = src if isinstance(src, tuple) else (src, None)
            if name in df.columns:
                v = pd.to_numeric(df[name], errors="coerce")
                if sign == "neg":
                    v = -v
                ser = v.fillna(0.0)
                break
        if ser is None:
            ser = pd.Series(0.0, index=df.index)
        out[canon] = ser / YI
    # 扣非归母为 0 时回退为归母（原表第53行逻辑）
    if "np_deducted" in out and "np_parent" in out:
        d, p = out["np_deducted"], out["np_parent"]
        out["np_deducted"] = d.where(d != 0.0, p)
    return out


def _merge_admin_rd(canon_is: dict) -> None:
    """管理费用(模型口径) = 报表管理费用 + 研发费用（原表第24行逻辑）。"""
    canon_is["manage_exp"] = canon_is["manage_exp_raw"].fillna(0) + canon_is["rd_exp"].fillna(0)


def _advance_plus_contract(canon_bs: dict) -> None:
    """预收款项(模型口径) = 预收款项 + 合同负债（原表第130行逻辑）。"""
    canon_bs["advance"] = canon_bs["advance_rece"].fillna(0) + canon_bs["contract_liab"].fillna(0)


def _fin_lease_liab(canon_bs: dict) -> None:
    """融资负债 = 租赁负债 + 长期应付款（原表155+156行逻辑）。"""
    canon_bs["fin_lease"] = canon_bs["lease_liab"].fillna(0) + canon_bs["lt_payable"].fillna(0)


def _fixed_cip_detail(canon_bs: dict) -> None:
    """固定资产/在建工程: canon fixed_asset/cip 存"合计"口径(含清理/工程物资),
    fixed_detail/cip_detail 存净额口径（原表101/104 与 102/105 的区别）。"""
    fa = canon_bs.get("fixed_asset")
    cleanup = canon_bs.get("fa_cleanup")
    cip = canon_bs.get("cip")
    proj = canon_bs.get("proj_material")
    if fa is not None:
        canon_bs["fixed_detail"] = fa
        canon_bs["fixed_asset"] = fa.fillna(0) + (cleanup.fillna(0) if cleanup is not None else 0.0)
    if cip is not None:
        canon_bs["cip_detail"] = cip
        canon_bs["cip"] = cip.fillna(0) + (proj.fillna(0) if proj is not None else 0.0)


def _to_quarterly(is_ytd: dict, cf_ytd: dict, bs: dict) -> tuple[dict, dict, dict]:
    """利润表/现金流 YTD -> 单季差分；资产负债表为期末时点直接保留。"""
    def diff(d):
        out = {}
        idx = None
        for k, s in d.items():
            idx = s.index
            break
        if idx is None:
            return d
        for k, s in d.items():
            s = s.sort_index()
            vals = []
            prev_year, prev_val = None, 0.0
            for dt, v in s.items():
                y, mm = dt[:4], dt[5:7]
                if mm == "03":
                    vals.append(v)
                else:
                    base = s.get(f"{y}-03-31", 0.0)
                    if mm == "06":
                        vals.append(v - base)
                    elif mm == "09":
                        b6 = s.get(f"{y}-06-30", base)
                        vals.append(v - b6)
                    else:  # 12
                        b9 = s.get(f"{y}-09-30", s.get(f"{y}-06-30", base))
                        vals.append(v - b9)
                prev_year, prev_val = y, v
            out[k] = pd.Series(vals, index=s.index)
        return out
    return diff(is_ytd), diff(cf_ytd), bs


def fetch_akshare(code_or_name: str) -> RawStatements:
    import akshare as ak
    em_code, ts_code, name = _norm_code(code_or_name)
    if not name:
        try:
            names = ak.stock_info_a_code_name()
            row = names[names["code"] == ts_code[:6]]
            name = row.iloc[0]["name"] if not row.empty else ts_code
        except Exception:
            name = ts_code
    is_df = ak.stock_profit_sheet_by_report_em(symbol=em_code)
    bs_df = ak.stock_balance_sheet_by_report_em(symbol=em_code)
    cf_df = ak.stock_cash_flow_sheet_by_report_em(symbol=em_code)

    is_ytd = _canon_from_em(is_df, IS_MAP)
    bs = _canon_from_em(bs_df, BS_MAP)
    cf_ytd = _canon_from_em(cf_df, CF_MAP)
    _merge_admin_rd(is_ytd)
    _advance_plus_contract(bs)
    _fin_lease_liab(bs)
    _fixed_cip_detail(bs)

    ann_sel = lambda d: {k: s[s.index.str.endswith("12-31")] for k, s in d.items()}
    annual = {}
    annual.update(ann_sel(is_ytd))
    annual.update(ann_sel(bs))
    annual.update(ann_sel(cf_ytd))

    is_q, cf_q, bs_q = _to_quarterly(is_ytd, cf_ytd, bs)
    quarterly = {}
    quarterly.update(is_q)
    quarterly.update(bs_q)
    quarterly.update(cf_q)

    return RawStatements(annual=annual, quarterly=quarterly,
                         meta={"code": ts_code, "em_code": em_code, "name": name,
                               "source": "akshare/东方财富"})


def _ts_canon(pro, api: str, ts_code: str, mapping: dict) -> dict:
    # 显式 fields：tushare 默认列子集不含 oth_income/asset_disp_income/
    # credit_impa_loss 等；fields 中不存在的字段名会被静默忽略，不会报错
    cols = list(dict.fromkeys(["end_date", *mapping.values(),
                               "credit_impa_loss", "assets_impair_loss"]))
    df = getattr(pro, api)(ts_code=ts_code, fields=",".join(cols))
    if df is None or df.empty:
        return {}
    df = df.drop_duplicates(subset="end_date", keep="last")
    df["R"] = pd.to_datetime(df["end_date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("R").set_index("R")
    out = {}
    for canon, col in mapping.items():
        if col in df.columns:
            out[canon] = pd.to_numeric(df[col], errors="coerce").fillna(0.0) / YI
        else:
            out[canon] = pd.Series(0.0, index=df.index)
    # 减值转换仅限利润表：income 中 assets_impair_loss 新准则为收益口径(损失为负)，
    # credit_impa_loss 同为损失为负；现金流量表补充资料中的同名字段是加回项
    # (损失为正)，口径相反，绝不能混入
    if api == "income" and "assets_impair_loss" in df.columns:
        v = pd.to_numeric(df["assets_impair_loss"], errors="coerce").fillna(0.0)
        # 新准则(2019+)取负；旧准则报表该项目本就以损失为正列示，tushare 存为正值
        new_std = df.index >= "2019-01-01"
        out["impair_asset"] = pd.Series(np.where(new_std, -v, v), index=df.index) / YI
    if api == "income" and "credit_impa_loss" in df.columns:
        v = pd.to_numeric(df["credit_impa_loss"], errors="coerce").fillna(0.0)
        out["impair_credit"] = -v / YI
    if "net_expo_undue" in df.columns:
        pass
    # 扣非归母: tushare income 无此字段，留 0，由 fetch_tushare 用 fina_indicator 补；
    # 仅 income 字典占位，避免 bs/cf 的零值在 annual.update 时覆盖已补好的数据
    if api == "income":
        out.setdefault("np_deducted", pd.Series(0.0, index=df.index))
    return out


def fetch_tushare(code_or_name: str, token: str | None = None) -> RawStatements:
    import tushare as ts
    token = token or os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("tushare 需要 token：设置环境变量 TUSHARE_TOKEN 或用 --token 传入")
    ts.set_token(token)
    pro = ts.pro_api()
    em_code, ts_code, name = _norm_code(code_or_name)
    is_ytd = _ts_canon(pro, "income", ts_code, TS_IS_MAP)
    bs = _ts_canon(pro, "balancesheet", ts_code, TS_BS_MAP)
    cf_ytd = _ts_canon(pro, "cashflow", ts_code, TS_CF_MAP)
    # 扣非归母：income 接口无此字段，从 fina_indicator.profit_dedt 补充；失败则回退归母
    try:
        fi = pro.fina_indicator(ts_code=ts_code, fields="end_date,profit_dedt")
        if fi is not None and not fi.empty:
            # fina_indicator 返回为日期降序，keep="first" 保留最新调整值
            fi = fi.drop_duplicates(subset="end_date", keep="first")
            fi["R"] = pd.to_datetime(fi["end_date"]).dt.strftime("%Y-%m-%d")
            ded = pd.to_numeric(fi.set_index("R")["profit_dedt"], errors="coerce") / YI
            is_ytd["np_deducted"] = ded.reindex(is_ytd["net_profit"].index)
    except Exception as e:
        import sys
        print(f"[warn] fina_indicator 补扣非失败: {e}", file=sys.stderr)
    d = is_ytd["np_deducted"]
    p = is_ytd["np_parent"]
    is_ytd["np_deducted"] = d.where(d.notna() & (d != 0.0), p)
    # 应收款项融资：tushare 资产负债表无此字段，用 akshare/东方财富补充；失败则保持 0
    try:
        import akshare as ak
        em_bs = ak.stock_balance_sheet_by_report_em(symbol=em_code)
        if "FINANCE_RECE" in em_bs.columns:
            dates = pd.to_datetime(em_bs["REPORT_DATE"]).dt.strftime("%Y-%m-%d")
            rf = pd.to_numeric(em_bs["FINANCE_RECE"], errors="coerce").fillna(0.0)
            rf = pd.Series(rf.values, index=dates).groupby(level=0).last() / YI
            rf = rf.reindex(bs["total_assets"].index).fillna(0.0)
            bs["rece_financing"] = rf
    except Exception as e:
        import sys
        print(f"[warn] akshare 补应收款项融资失败(按 0 处理): {e}", file=sys.stderr)
    _merge_admin_rd(is_ytd)
    _advance_plus_contract(bs)
    _fin_lease_liab(bs)
    _fixed_cip_detail(bs)

    ann_sel = lambda d: {k: s[s.index.str.endswith("12-31")] for k, s in d.items()}
    annual = {}
    annual.update(ann_sel(is_ytd))
    annual.update(ann_sel(bs))
    annual.update(ann_sel(cf_ytd))
    is_q, cf_q, bs_q = _to_quarterly(is_ytd, cf_ytd, bs)
    quarterly = {}
    quarterly.update(is_q)
    quarterly.update(bs_q)
    quarterly.update(cf_q)
    return RawStatements(annual=annual, quarterly=quarterly,
                         meta={"code": ts_code, "em_code": em_code,
                               "name": name or ts_code, "source": "tushare"})


def fetch_em(code_or_name: str) -> RawStatements:
    """东方财富 datacenter 直连（不经 akshare 封装层）。

    与 akshare 通道同源（均为东财报表数据），但请求链路独立，
    可用于交叉验证；列名与 IS_MAP/BS_MAP/CF_MAP 完全兼容。
    名称→代码的查找仍复用 akshare（传入纯代码时不需要 akshare）。
    """
    from . import em_direct
    em_code, ts_code, name = _norm_code(code_or_name)
    is_df = em_direct.fetch_em_income(em_code)
    bs_df = em_direct.fetch_em_balance(em_code)
    cf_df = em_direct.fetch_em_cashflow(em_code)

    is_ytd = _canon_from_em(is_df, IS_MAP)
    bs = _canon_from_em(bs_df, BS_MAP)
    cf_ytd = _canon_from_em(cf_df, CF_MAP)
    _merge_admin_rd(is_ytd)
    _advance_plus_contract(bs)
    _fin_lease_liab(bs)
    _fixed_cip_detail(bs)

    ann_sel = lambda d: {k: s[s.index.str.endswith("12-31")] for k, s in d.items()}
    annual = {}
    annual.update(ann_sel(is_ytd))
    annual.update(ann_sel(bs))
    annual.update(ann_sel(cf_ytd))
    is_q, cf_q, bs_q = _to_quarterly(is_ytd, cf_ytd, bs)
    quarterly = {}
    quarterly.update(is_q)
    quarterly.update(bs_q)
    quarterly.update(cf_q)
    return RawStatements(annual=annual, quarterly=quarterly,
                         meta={"code": ts_code, "em_code": em_code,
                               "name": name or ts_code, "source": "东方财富直连(datacenter)"})


def fetch(code_or_name: str, source: str = "akshare", token: str | None = None) -> RawStatements:
    if source == "tushare":
        return fetch_tushare(code_or_name, token)
    if source == "em":
        return fetch_em(code_or_name)
    return fetch_akshare(code_or_name)
