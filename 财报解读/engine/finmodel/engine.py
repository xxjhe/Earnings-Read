# -*- coding: utf-8 -*-
"""指标计算引擎：复现《财务分析模型（季度）》五大模块全部公式。

输入: canon dict[str, pd.Series]（亿元，index 为报告期字符串，升序）
      —— 年度引擎吃年度口径，季度引擎吃单季口径，公式完全一致，
         仅增长率口径不同（年度=同比上一年，季度=同比上年前4季 / 环比上一季）。

输出: 各模块返回 list[(分组, 指标名, pd.Series, 格式)]，保持原表行顺序。
      格式: "yi" 亿元 | "pct" 百分比(数值为小数) | "x" 倍数 | "d" 天 | "txt" 文本

与原表的一致性说明（原样复现的 quirk）:
  * 应付账款周转的"平均应付"未做两期平均（原表即如此）。
  * "其他非流动负债"含租赁负债/长期应付款，与长期有息负债存在轻微重复计算（原表即如此）。
  * 股权资金成本 = 期末股东权益 × 10%（参数可调）。
  * 附注类手动项（坏账准备、固定资产原值、授信额度等）脚本无法获得，降级为 0 或近似，
    受影响的指标（固定资产成新率等）输出 None 并在报告中注明。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ASSUMED_COST_OF_EQUITY = 0.10   # 原表第108行假设：股权资金成本率 10%
DAYS = 360                      # 原表周转天数用 360 天


def _nan():
    return np.nan


class Module:
    """一个模块的计算结果容器：保持顺序的指标列表。"""

    def __init__(self, name):
        self.name = name
        self.items = []  # (group, label, series_or_scalar, fmt)

    def add(self, group, label, series, fmt="yi"):
        self.items.append((group, label, series, fmt))

    def get(self, label):
        for _, l, s, _ in self.items:
            if l == label:
                return s
        raise KeyError(label)

    def to_frame(self):
        return pd.DataFrame({l: s for _, l, s, f in self.items if isinstance(s, pd.Series)})


class Engine:
    def __init__(self, raw: dict, freq: str = "A", cost_of_equity: float = ASSUMED_COST_OF_EQUITY):
        """
        raw: canon dict of pd.Series
        freq: "A" 年度 / "Q" 季度（影响增长率的位移步长与年化）
        """
        self.raw = raw
        self.freq = freq
        self.cqe = cost_of_equity
        # 公共期间轴：所有序列索引的并集（升序）
        idx = sorted({p for s in raw.values() if isinstance(s, pd.Series) for p in s.index})
        self.periods = pd.Index(idx)
        self._cache = {}

    # ------------------------------------------------------------------ util
    def S(self, name) -> pd.Series:
        """取原始字段，对齐公共期间轴，缺失补 0。"""
        if name in self._cache:
            return self._cache[name]
        s = self.raw.get(name)
        if not isinstance(s, pd.Series):
            s = pd.Series(dtype=float)
        s = s.reindex(self.periods).fillna(0.0).astype(float)
        self._cache[name] = s
        return s

    def Sopt(self, name):
        """可选字段：未提供时返回 None（区分"未提供"与"全 0"）。"""
        s = self.raw.get(name)
        if not isinstance(s, pd.Series):
            return None
        return s.reindex(self.periods).fillna(0.0).astype(float)

    def prev(self, s: pd.Series, n: int = 1) -> pd.Series:
        """上一期（年度=上一年；季度=上一季）。第一期之前为 NaN。"""
        return s.shift(n)

    def yoy_base(self, s: pd.Series) -> pd.Series:
        """增长率基期：年度=shift(1)，季度=shift(4)（同比）。"""
        return s.shift(4 if self.freq == "Q" else 1)

    @staticmethod
    def div(a, b):
        """安全除：分母为 0/NaN -> NaN。a、b 可为 Series 或标量。"""
        if isinstance(a, pd.Series) or isinstance(b, pd.Series):
            a = a if isinstance(a, pd.Series) else pd.Series(a, index=b.index)
            b = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
            return a / b.replace(0.0, np.nan)
        if b in (0, None) or (isinstance(b, float) and np.isnan(b)):
            return np.nan
        return a / b

    @staticmethod
    def growth(s: pd.Series, base: pd.Series) -> pd.Series:
        """增长率 = s/base - 1（基期为 0 或 NaN -> NaN）。"""
        return Engine.div(s, base) - 1

    # ============================================================ 股权增加值
    def equity_value(self) -> Module:
        m = Module("股权增加值分析")
        S, prev, div = self.S, self.prev, self.div

        rev = S("rev")                       # 26 营业收入
        cost = S("cost")                     # 28 营业成本
        tax_sur = S("tax_surcharge")         # 35 税金及附加
        sell = S("sell_exp")                 # 33 销售费用
        manage = S("manage_exp")             # 40 管理费用(含研发)
        rd = S("rd_exp")                     # 44 研发费用
        fin = S("fin_exp")                   # 26 财务费用
        int_inc = S("int_inc")               # 68 利息收入(费用附注C10)
        int_exp = S("int_exp")               # 87 利息支出(费用附注C9)
        impair_a = S("impair_asset")         # 46 资产减值损失
        impair_c = S("impair_credit")        # 48 信用减值损失
        invest_inc = S("invest_income")      # 65 投资净收益
        fv = S("fv_change")                  # 67 公允价值变动
        disposal = S("asset_disposal")       # 资产处置收益
        other_inc = S("other_income")        # 其他收益
        non_op_i = S("non_op_income")        # 53 营业外收入
        non_op_e = S("non_op_exp")           # 54 营业外支出
        tax = S("income_tax")                # 97 所得税
        np_ = S("net_profit")                # 99 净利润
        np_parent = S("np_parent")           # 115 归母净利润
        depr = S("depr")
        amort = S("amort_ia") + S("amort_lpe")

        g_rev = self.growth(rev, self.yoy_base(rev))              # 27 收入增速
        gm = 1 - div(cost, rev)                                   # 29 毛利率
        g_gp = self.growth(rev - cost, self.yoy_base(rev - cost)) # 30 毛利增速
        # 32 销量贡献（先算），31 毛利率贡献
        gm_prev = self.yoy_base(gm)
        vol_contrib = (1 + g_gp) * Engine.div(gm_prev * (1 - gm), gm * (1 - gm_prev)) - 1
        gm_contrib = Engine.div(1 + g_gp, vol_contrib + 1) - 1

        stage1 = rev - cost - sell - tax_sur                      # 37 阶段利润1
        # 42 行政管理费 = 管理费用(含IS研发) - 研发费用(附注66费用化口径，缺则回退IS研发)
        rd_note_exp = self.Sopt("rd_note_expensed")
        rd_for_admin = rd_note_exp if rd_note_exp is not None else rd
        admin_only = manage - rd_for_admin
        # 47 资产减值/(长期经营资产期末+期初)（原表为两期之和，非均值）
        lt_op = self._lt_operating_assets()
        recv = S("note_rece") + S("ar") + S("rece_financing")
        impair_a_ratio = div(impair_a, lt_op + prev(lt_op))
        # 49 信用减值/(应收票据+应收账款净值+应收款项融资)（当期值，不平均）
        impair_c_ratio = div(impair_c, recv)
        stage2 = rev - cost - sell - tax_sur - manage - impair_a - impair_c  # 50 阶段利润2

        total_exp = sell + tax_sur + manage + impair_a + non_op_e - non_op_i + impair_c  # 55 总费用
        ebit_op = rev - cost - total_exp                          # 57 息税前经营利润
        # 98 实际税率（先算）：= 所得税 / 税前利润；税前利润见下
        fin_other = fin + int_inc - int_exp                       # 91 财务其他支出
        fin_asset_ebt = invest_inc + fv + int_inc + disposal + other_inc  # 72 息税前金融资产收益
        ebit = ebit_op + fin_asset_ebt                            # 78 EBIT
        profit_bt = ebit - int_exp - fin_other                    # 96 税前利润
        tax_rate = div(tax, profit_bt)                            # 98 实际税率
        tax_op = ebit_op * tax_rate                               # 62 经营所得税
        noplat_op = ebit_op - tax_op                              # 63 息前税后经营利润
        fin_tax = fin_asset_ebt * tax_rate                        # 73
        noplat_fin = fin_asset_ebt - fin_tax                      # 74 息前税后金融资产收益
        ebitda = ebit + depr + amort                              # 81 EBITDA
        noplat = noplat_op + noplat_fin                           # 84 NOPLAT
        int_rate = div(int_exp, self._interest_bearing_debt())    # 89 利息率
        tax_shield = -(int_exp + fin_other) * tax_rate            # 92 税盾
        fin_cost_at = (int_exp + fin_other) * (1 - tax_rate)      # 94 税后财务费用
        fin_burden = 1 - div(profit_bt, ebit)                     # 95 财务成本负担率
        err = noplat - fin_cost_at - np_                          # 100 误差项

        nri = np_ - S("np_deducted")                              # 103 非经常性损益(=净利润-扣非)
        earn_quality = div(nri, np_)                              # 104 收益质量
        np_ded = S("np_deducted")                                 # 105 扣非净利润
        g_np_ded = self.growth(np_ded.replace(0, np.nan), self.yoy_base(np_ded).replace(0, np.nan))  # 106

        eq = S("total_eq")                                        # 股东权益合计
        eq_cost = eq * self.cqe                                   # 107 股权资金成本
        eva = np_ - eq_cost                                       # 109 EVA
        g_np_parent = self.growth(np_parent.replace(0, np.nan),
                                  self.yoy_base(np_parent).replace(0, np.nan))  # 117
        undist = S("undistributed")
        retain = undist - prev(undist)                            # 127 留存收益
        retain_ratio = div(retain, np_parent)                     # 118 留存比例
        shares = S("share_capital")                               # 股本(亿股)
        eps = div(np_parent, shares)                              # 124 EPS
        # 128 派现：附注项，用 CF 近似 = 分配股利利息支付 - 利息支出
        div_paid = S("div_int_paid") - int_exp
        # 130 ROE：年度=净利润/股东权益；季度=归母净利润/股东权益（按原表）
        if self.freq == "Q":
            roe = div(np_parent, eq)
            # 季度版周转率/权益乘数用模型口径资产/资本（原表季度口径）
            m_assets, m_capital = self._model_totals()
            ta_turn = div(rev, m_assets)
            em = div(m_assets, m_capital)
        else:
            roe = div(np_, eq)
            ta_turn = div(rev, S("total_assets"))                     # 132 总资产周转率
            em = div(S("total_assets"), eq)                           # 133 权益乘数
        payout = div(div_paid, np_parent)                         # 134 股息支付率

        # 136-145 净利润增长拆分（137 毛利口径 = 收入-成本-销售费用，按原表；
        # 增量基期：年度=上年，季度=上年同季[原表季度版引用4列前]）
        yb = self.yoy_base
        gp = rev - cost - sell
        d_gp = gp - yb(gp)                                        # 137 毛利增加
        exp_ex_sell = total_exp - sell
        d_exp = -(exp_ex_sell - yb(exp_ex_sell))                  # 139 费用减少
        d_tax = -(tax - yb(tax))                                  # 141 税费减少
        fin_net = fin_asset_ebt - int_exp - fin_other
        d_fin = fin_net - yb(fin_net)                             # 143 财务收入增加
        d_np = np_ - yb(np_)                                      # 145 净利润增加额
        c_gp = div(d_gp, d_np.abs())
        c_exp = div(d_exp, d_np.abs())
        c_tax = div(d_tax, d_np.abs())
        c_fin = div(d_fin, d_np.abs())

        np_growth = self.growth(np_.replace(0, np.nan), yb(np_).replace(0, np.nan))  # 102/101
        roe_chg = div(roe, prev(roe)) - 1                         # 148 ROE变化(季度为环比)
        reinvest_retained = div(retain, np_) * roe                # 149 未分配利润再投资
        fin_reinvest = np_growth - roe_chg - reinvest_retained    # 150 筹资再投资(=147-148-149)
        op_share = div(noplat_op, noplat)                         # 153 经营利润占比
        fin_share = div(noplat_fin, noplat)                       # 154 金融收益占比

        # ---- 框架补充（框架 L1 战略画像 / L3 利润解构）----
        sell_rate = div(sell, rev)                                # 销售费用率
        manage_rate = div(manage, rev)                            # 管理费用率(含研发)
        rd_rate = div(rd, rev)                                    # 研发费用率(研发强度)
        fin_rate = div(fin, rev)                                  # 财务费用率
        minority_share = div(S("minority_pl"), np_)               # 少数股东损益占比

        # 157-161 ROCE
        apparent_assets = eq                                      # 157 表观资产
        apparent_roce = div(np_parent, prev(apparent_assets))     # 158 表观ROCE
        fin_assets = self._financial_assets()                     # 53 金融资产
        st_debt, lt_debt = self._st_debt(), self._lt_debt()
        net_op_assets = apparent_assets + st_debt + lt_debt - fin_assets  # 160 净经营资产
        delev_roce = div(noplat, prev(net_op_assets))             # 161 去杠杆ROCE

        A = m.add
        A("经营利润", "营业收入", rev, "yi")
        A("经营利润", "营业收入增长率", g_rev, "pct")
        A("经营利润", "营业成本", cost, "yi")
        A("经营利润", "毛利率", gm, "pct")
        A("经营利润", "毛利增速", g_gp, "pct")
        A("经营利润", "销量贡献", vol_contrib, "pct")
        A("经营利润", "毛利率贡献", gm_contrib, "pct")
        A("经营利润", "阶段利润1(收入-成本-销售-税金)", stage1, "yi")
        A("经营利润", "行政管理费", admin_only, "yi")
        A("经营利润", "资产减值损失", impair_a, "yi")
        A("经营利润", "资产减值/长期经营资产", impair_a_ratio, "pct")
        A("经营利润", "信用减值损失", impair_c, "yi")
        A("经营利润", "信用减值/应收类资产", impair_c_ratio, "pct")
        A("经营利润", "阶段利润2", stage2, "yi")
        A("经营利润", "总费用", total_exp, "yi")
        A("经营利润", "息税前经营利润", ebit_op, "yi")
        A("费用率", "销售费用率", sell_rate, "pct")
        A("费用率", "管理费用率(含研发)", manage_rate, "pct")
        A("费用率", "研发费用率", rd_rate, "pct")
        A("费用率", "财务费用率", fin_rate, "pct")
        A("利润解构", "经营所得税", tax_op, "yi")
        A("利润解构", "息前税后经营利润", noplat_op, "yi")
        A("利润解构", "息税前金融资产收益", fin_asset_ebt, "yi")
        A("利润解构", "金融资产收益所得税", fin_tax, "yi")
        A("利润解构", "息前税后金融资产收益", noplat_fin, "yi")
        A("利润解构", "EBIT", ebit, "yi")
        A("利润解构", "EBITDA", ebitda, "yi")
        A("利润解构", "NOPLAT", noplat, "yi")
        A("财务成本", "利息支出", int_exp, "yi")
        A("财务成本", "利息率", int_rate, "pct")
        A("财务成本", "财务其他支出", fin_other, "yi")
        A("财务成本", "税盾", tax_shield, "yi")
        A("财务成本", "税后财务费用", fin_cost_at, "yi")
        A("财务成本", "财务成本负担率", fin_burden, "pct")
        A("财务成本", "税前利润", profit_bt, "yi")
        A("财务成本", "所得税", tax, "yi")
        A("财务成本", "实际税率", tax_rate, "pct")
        A("财务成本", "净利润", np_, "yi")
        A("财务成本", "误差项(NOPLAT-税后财务费用-净利润)", err, "yi")
        A("净利润质量", "非经常性损益", nri, "yi")
        A("净利润质量", "收益质量(非经常/净利润)", earn_quality, "pct")
        A("净利润质量", "扣非净利润", np_ded, "yi")
        A("净利润质量", "扣非净利润增速", g_np_ded, "pct")
        A("净利润质量", "少数股东损益占比", minority_share, "pct")
        A("EVA", "股权资金成本", eq_cost, "yi")
        A("EVA", "经济增加值EVA", eva, "yi")
        A("股东回报", "归母净利润", np_parent, "yi")
        A("股东回报", "归母净利润增速", g_np_parent, "pct")
        A("股东回报", "留存比例", retain_ratio, "pct")
        A("股东回报", "每股收益EPS(元)", eps, "x")
        A("股东回报", "留存收益", retain, "yi")
        A("股东回报", "派现(CF近似)", div_paid, "yi")
        A("股东回报", "ROE", roe, "pct")
        A("股东回报", "总资产周转率", ta_turn, "x")
        A("股东回报", "权益乘数", em, "x")
        A("股东回报", "股息支付率", payout, "pct")
        A("净利润增长拆分", "毛利增加", d_gp, "yi")
        A("净利润增长拆分", "费用减少", d_exp, "yi")
        A("净利润增长拆分", "税费减少", d_tax, "yi")
        A("净利润增长拆分", "财务收入增加", d_fin, "yi")
        A("净利润增长拆分", "净利润增加额", d_np, "yi")
        A("净利润增长拆分", "毛利贡献率", c_gp, "pct")
        A("净利润增长拆分", "费用贡献率", c_exp, "pct")
        A("净利润增长拆分", "税费贡献率", c_tax, "pct")
        A("净利润增长拆分", "财务贡献率", c_fin, "pct")
        A("再投资", "净利润增长率", np_growth, "pct")
        A("再投资", "ROE变化", roe_chg, "pct")
        A("再投资", "未分配利润再投资", reinvest_retained, "pct")
        A("再投资", "筹资再投资", fin_reinvest, "pct")
        A("利润结构", "经营利润占比", op_share, "pct")
        A("利润结构", "金融收益占比", fin_share, "pct")
        A("ROCE", "表观资产(股东权益)", apparent_assets, "yi")
        A("ROCE", "表观ROCE", apparent_roce, "pct")
        A("ROCE", "净经营资产", net_op_assets, "yi")
        A("ROCE", "去杠杆ROCE", delev_roce, "pct")
        return m

    # ------------------------------------------------- 资产资本分析的内部构件
    def _other_liab_total(self) -> pd.Series:
        """无息其他负债 = (流动负债合计-短期有息-营运负债) + (非流动负债合计-长期借款-应付债券[-租赁])
        年度：非流动部分不减租赁(与长期有息的租赁形成轻微重复计算，原表quirk)；
        季度：非流动部分减 长期有息(含租赁)。"""
        S = self.S
        wl = self._working_liab()
        ocl = S("total_cl") - self._st_debt() - wl
        if self.freq == "Q":
            oncl = S("total_ncl") - self._lt_debt()
        else:
            oncl = S("total_ncl") - S("bond_pay") - S("lt_loan")
        return ocl + oncl

    def _model_totals(self):
        """模型口径 资产总额(64) 与 资本总额(69)。供 EV/AC 两模块共用。"""
        wc = self._working_assets() - self._working_liab()
        lt_op = self._lt_operating_assets()
        lt_eq_inv = self.S("lt_eq_invest")
        fa = self._financial_assets()
        other_assets = self._other_assets()
        assets = lt_op + lt_eq_inv + wc + fa + other_assets
        other_liab = self._other_liab_total()
        capital = self._st_debt() + self._lt_debt() + self.S("total_eq") + other_liab
        return assets, capital

    def _financial_assets(self) -> pd.Series:
        """138 金融资产合计 = 货币资金+交易性+可供出售+持有至到期+投资性房地产(+手动项0)"""
        S = self.S
        return (S("cash") + S("trade_fa") + S("afs_fa") + S("htm_invest") + S("invest_re"))

    def _working_assets(self) -> pd.Series:
        """171 营运资产 = 应收票据+应收账款+其他应收+预付+存货+长期应收+合同资产+应收款项融资"""
        S = self.S
        return (S("note_rece") + S("ar") + S("other_rece") + S("prepay") + S("inventory")
                + S("long_rece") + S("contract_asset") + S("rece_financing"))

    def _working_liab(self) -> pd.Series:
        """187 营运负债 = 应付票据+应付账款+预收(含合同负债)+应付职工薪酬+应交税费+预提费用"""
        S = self.S
        return (S("note_pay") + S("ap") + S("advance") + S("payroll") + S("tax_pay")
                + S("accrued_exp"))

    def _lt_operating_assets(self) -> pd.Series:
        """211 长期经营资产 = 固定资产+在建+无形+开发支出+商誉+长期待摊+其他(油气+生物)"""
        S = self.S
        return (S("fixed_asset") + S("cip") + S("intangible") + S("dev_exp")
                + S("goodwill") + S("lt_prepaid") + S("oil_gas") + S("bio_asset"))

    def _st_debt(self) -> pd.Series:
        """238 短期有息 = 短期借款+应付短期债券+一年内到期非流动负债"""
        S = self.S
        return S("st_loan") + S("st_bond") + S("ncl_1y")

    def _lt_debt(self) -> pd.Series:
        """长期有息：年度=长期借款+应付债券+融资负债(租赁+长期应付款,155+156)；
        季度=长期借款+应付债券+租赁负债(仅155，原表季度口径，原样复现)。"""
        S = self.S
        if self.freq == "Q":
            return S("lt_loan") + S("bond_pay") + S("lease_liab")
        return S("lt_loan") + S("bond_pay") + S("fin_lease")

    def _interest_bearing_debt(self) -> pd.Series:
        """243 有息负债"""
        return self._st_debt() + self._lt_debt()

    def _other_current_liab(self) -> pd.Series:
        """其他流动负债 = 流动负债合计-短期借款-应付票据-应付账款-应付短期债券-预收-薪酬-税费-预提-一年内到期"""
        S = self.S
        return (S("total_cl") - S("st_loan") - S("note_pay") - S("ap") - S("st_bond")
                - S("advance") - S("payroll") - S("tax_pay") - S("accrued_exp") - S("ncl_1y"))

    def _other_noncurrent_liab(self) -> pd.Series:
        """其他非流动负债 = 非流动负债合计-应付债券-长期借款（含租赁/长期应付款，原表quirk）"""
        S = self.S
        return S("total_ncl") - S("bond_pay") - S("lt_loan")

    def _other_assets(self) -> pd.Series:
        """220+224 其他资产（流动+非流动），年度/季度同构(季度为164/168行)。
        原表quirk: 长期应收款同时计入营运资产与其他流动资产(+长期应收)，
        并从非流动其他中剔除(-长期应收)。"""
        S = self.S
        wa = self._working_assets()
        lt_op = self._lt_operating_assets()
        other_ca = (S("total_ca") - S("cash") - S("trade_fa") - wa
                    + S("long_rece"))
        other_nca = (S("total_nca") - S("afs_fa") - S("htm_invest")
                     - S("invest_re") - lt_op - S("lt_eq_invest")
                     - S("long_rece"))
        return other_ca + other_nca

    # ============================================================ 资产资本
    def asset_capital(self) -> Module:
        m = Module("资产资本分析")
        S, prev, div = self.S, self.prev, self.div
        ev = self._ev  # 股权增加值模块（内部依赖）
        ev_m = ev()
        g = lambda label: ev_m.get(label)

        fa = self._financial_assets()                  # 138
        wa = self._working_assets()                    # 171 (毛口径)
        wl = self._working_liab()                      # 187
        wc = wa - wl                                   # 188/55 营运资本(净口径)
        d_wc = wc - prev(wc)                           # 189 追加营运资本
        lt_op = self._lt_operating_assets()            # 211
        other_assets = self._other_assets()            # 63=220+224
        lt_eq_inv = S("lt_eq_invest")                  # 144/59 长期股权投资
        # 64 资产总额 = 长期经营资产+长投+营运资本(净)+金融资产+其他项
        total_assets_model = lt_op + lt_eq_inv + wc + fa + other_assets
        st_debt, lt_debt = self._st_debt(), self._lt_debt()
        ibd = st_debt + lt_debt                        # 243 有息负债
        other_liab = self._other_liab_total()          # 252/195
        eq = S("total_eq")                             # 48
        total_capital = st_debt + lt_debt + eq + other_liab          # 69 资本总额
        ibd_ratio = div(ibd, total_capital)            # 70 有息负债率
        fin_leverage = div(ibd, eq)                    # 71 财务杠杆
        # 72 长期融资净额 = 股东权益+长期有息-长期经营资产-长投-营运资本(净)
        lt_fin_net = eq + lt_debt - lt_op - lt_eq_inv - wc
        # 74 营运资本长期化率 = (股东权益+长期有息+其他负债-长期经营资产-长投-其他资产)/营运资本(净)
        wc_lt_ratio = div(eq + lt_debt + other_liab - lt_op - lt_eq_inv - other_assets, wc)

        # ---- 框架补充（框架 L1 战略画像 / L2 资产资本结构）----
        fa_share = div(fa, total_assets_model)                    # 金融资产占比
        lt_op_share = div(lt_op, total_assets_model)              # 长期经营资产占比
        wc_share = div(wc, total_assets_model)                    # 营运资本(净)占比
        gw_eq = div(S("goodwill"), eq)                            # 商誉/净资产
        st_debt_share = div(st_debt, ibd)                         # 短期有息占比
        net_debt = ibd - S("cash")                                # 净债务(有息-货币资金)
        liab_ratio_report = div(S("total_liab"), S("total_assets"))  # 资产负债率(报表口径)
        minority_eq_share = div(S("minority_eq"), eq)             # 少数股东权益占比

        # 杜邦分解 (78-84): ROE = EBIT利润率 × 资产周转率 × 财务成本效应 × 财务杠杆倍数 × 所得税效应
        ebit_op = g("息税前经营利润")
        ebit = g("EBIT")
        profit_bt = g("税前利润")
        np_ = g("净利润")
        rev = S("rev")
        dupont_margin = div(ebit, rev)                 # 78 = 股权增加值!79 (EBIT/销售收入)
        dupont_turn = div(rev, total_assets_model)     # 资产周转率
        dupont_fin_cost = div(profit_bt, ebit)         # 财务成本效应
        dupont_leverage = div(total_capital, eq)       # 财务杠杆倍数
        dupont_tax = div(np_, profit_bt)               # 所得税效应
        dupont_roe = dupont_margin * dupont_turn * dupont_fin_cost * dupont_leverage * dupont_tax

        # 营业周期 (88-102)
        recv = S("note_rece") + S("ar") - S("advance")
        avg_recv = (recv + prev(recv)) / 2             # 88
        recv_turn = div(rev, avg_recv)                 # 89
        recv_days = div(DAYS, recv_turn)               # 90
        inv = S("inventory")
        avg_inv = (inv + prev(inv)) / 2                # 92
        cost = S("cost")
        inv_turn = div(cost, avg_inv)                  # 93
        inv_days = div(DAYS, inv_turn)                 # 94
        pay = S("note_pay") + S("ap") - S("prepay")    # 95 (原表quirk：未两期平均)
        pay_turn = div(cost, pay)                      # 96
        pay_days = div(DAYS, pay_turn)                 # 97
        adv_turn = div((S("advance") + prev(S("advance"))) / 2, rev)  # 99 预收周转
        op_cycle = recv_days + inv_days                # 101 营业周期
        cash_cycle = recv_days + inv_days - pay_days   # 102 现金周期

        # 投入资本 (112-128)
        # 112 全部投入资产 = 营运资本(净,55) + 长期资产(61+59) + 其他项(63) + 金融资产(53)
        all_invest_assets = wc + lt_op + lt_eq_inv + other_assets + fa
        core_assets = all_invest_assets - lt_eq_inv - fa                 # 113 核心生意资产
        avg_core = (core_assets + prev(core_assets)) / 2                 # 114
        noplat_op = g("息前税后经营利润")
        noplat = g("NOPLAT")
        core_roic = div(noplat_op, avg_core)                             # 115 核心ROIC
        all_roic = div(noplat, (all_invest_assets + prev(all_invest_assets)) / 2)  # 116
        total_invest_capital = ibd + eq + other_liab - fa                # 124 全部投入资本
        roic = div(noplat, total_invest_capital)                         # 125 投入资本回报率
        int_rate = g("利息率")
        tax_rate = g("实际税率")
        equity_return = div(noplat - ibd * int_rate * (1 - tax_rate), eq)  # 126 股本回报率
        re = noplat - ibd * int_rate * (1 - tax_rate) - eq * self.cqe      # 127 RE
        roce = div(re, eq)                                               # 128 ROCE

        # 固定资产成新率 199 = (固定资产+在建)/固定资产原值 —— 附注数据缺失 -> None
        fix_new = pd.Series(np.nan, index=self.periods)

        A = m.add
        A("资产结构", "金融资产合计", fa, "yi")
        A("资产结构", "营运资产", wa, "yi")
        A("资产结构", "营运负债", wl, "yi")
        A("资产结构", "营运资本", wc, "yi")
        A("资产结构", "追加营运资本", d_wc, "yi")
        A("资产结构", "长期经营资产", lt_op, "yi")
        A("资产结构", "长期股权投资", lt_eq_inv, "yi")
        A("资产结构", "其他资产(流动+非流动)", other_assets, "yi")
        A("资产结构", "资产总额(模型口径)", total_assets_model, "yi")
        A("资产结构", "金融资产占比", fa_share, "pct")
        A("资产结构", "长期经营资产占比", lt_op_share, "pct")
        A("资产结构", "营运资本(净)占比", wc_share, "pct")
        A("资产结构", "商誉/净资产", gw_eq, "pct")
        A("资本结构", "短期有息负债", st_debt, "yi")
        A("资本结构", "长期有息负债", lt_debt, "yi")
        A("资本结构", "有息负债合计", ibd, "yi")
        A("资本结构", "无息及其他负债", other_liab, "yi")
        A("资本结构", "股东权益", eq, "yi")
        A("资本结构", "资本总额(模型口径)", total_capital, "yi")
        A("资本结构", "有息负债率", ibd_ratio, "pct")
        A("资本结构", "财务杠杆(有息/权益)", fin_leverage, "x")
        A("资本结构", "长期融资净额", lt_fin_net, "yi")
        A("资本结构", "营运资本长期化率", wc_lt_ratio, "pct")
        A("资本结构", "短期有息占比", st_debt_share, "pct")
        A("资本结构", "净债务(有息-货币资金)", net_debt, "yi")
        A("资本结构", "资产负债率(报表口径)", liab_ratio_report, "pct")
        A("资本结构", "少数股东权益占比", minority_eq_share, "pct")
        A("杜邦分解", "息税前经营利润率", dupont_margin, "pct")
        A("杜邦分解", "资产周转率", dupont_turn, "x")
        A("杜邦分解", "财务成本效应", dupont_fin_cost, "x")
        A("杜邦分解", "财务杠杆倍数", dupont_leverage, "x")
        A("杜邦分解", "所得税效应", dupont_tax, "x")
        A("杜邦分解", "杜邦ROE(五因子连乘)", dupont_roe, "pct")
        A("营运效率", "平均应收(票据+账款-预收)", avg_recv, "yi")
        A("营运效率", "应收周转率", recv_turn, "x")
        A("营运效率", "应收周转天数", recv_days, "d")
        A("营运效率", "平均存货", avg_inv, "yi")
        A("营运效率", "存货周转率", inv_turn, "x")
        A("营运效率", "存货周转天数", inv_days, "d")
        A("营运效率", "应付(票据+账款-预付)", pay, "yi")
        A("营运效率", "应付周转率", pay_turn, "x")
        A("营运效率", "应付周转天数", pay_days, "d")
        A("营运效率", "预收周转率", adv_turn, "x")
        A("营运效率", "营业周期", op_cycle, "d")
        A("营运效率", "现金周期", cash_cycle, "d")
        A("投入资本回报", "全部投入资产", all_invest_assets, "yi")
        A("投入资本回报", "核心生意资产", core_assets, "yi")
        A("投入资本回报", "核心ROIC", core_roic, "pct")
        A("投入资本回报", "全经营ROIC", all_roic, "pct")
        A("投入资本回报", "全部投入资本", total_invest_capital, "yi")
        A("投入资本回报", "投入资本回报率ROIC", roic, "pct")
        A("投入资本回报", "股本回报率", equity_return, "pct")
        A("投入资本回报", "剩余收益RE", re, "yi")
        A("投入资本回报", "ROCE", roce, "pct")
        A("投入资本回报", "固定资产成新率(附注缺失)", fix_new, "pct")
        return m

    # ============================================================ 现金流分析
    def cashflow(self) -> Module:
        m = Module("现金流分析")
        S, prev, div = self.S, self.prev, self.div

        capex = S("capex")                     # 229 购建长期资产
        disposal_in = S("disposal_lt_asset")   # 223 处置收回
        net_lt_invest = capex - disposal_in    # 7 长期资产净投资
        depr = S("depr")
        amort = S("amort_ia") + S("amort_lpe")
        disp_loss = S("disposal_loss")         # 271
        scrap_loss = S("scrap_loss")           # 272
        # 13 扩张性资本投资 = 净投资 - 折旧 - 摊销 - 处置损失 - 报废损失
        exp_capex = net_lt_invest - depr - amort - disp_loss - scrap_loss
        lt_assets_begin = prev(self._lt_operating_assets())   # 14 期初长期资产
        exp_ratio = div(exp_capex, lt_assets_begin)           # 16 扩张比例
        # 18 研发投入 = 附注65(费用化+资本化)，缺附注数据时回退为利润表研发费用
        rd_note_total = self.Sopt("rd_note_total")
        rd = rd_note_total if rd_note_total is not None else S("rd_exp")
        rev = S("rev")
        d_rev = rev - self.yoy_base(rev)                      # 19 营收增长
        # 20 研发效率 = Δ收入 / 上期(研发+扩张投资)（原表引用上一期）
        rd_eff = div(d_rev, prev(rd) + prev(exp_capex))

        net_ma = S("acquire_sub") - S("disposal_sub")         # 25 净合并
        other_inv_in = S("withdraw_invest") + S("invest_income_cash") + S("other_invest_in")  # 31
        other_inv_out = S("invest_pay") + S("other_invest_out")                             # 34
        net_other_inv = other_inv_out - other_inv_in          # 35 净其他投资
        net_invest = net_other_inv + net_ma + net_lt_invest   # 36 净投资额

        borrow_in = S("borrow_in") + S("bond_in")             # 39 借款收到
        int_paid = S("int_exp")                               # 44 偿付利息(费用附注口径)
        debt_fin_net = borrow_in - S("repay_debt") - int_paid  # 45 债务筹资净额
        equity_in = S("accept_invest")                        # 48 吸收投资
        div_paid = S("div_int_paid") - int_paid               # 49 股利支付
        equity_fin_net = equity_in - div_paid                 # 50 股权筹资净额
        # 53 筹资净额 = 股权净额 + 债务净额 + 收到其他 - 支付其他
        fin_net = equity_fin_net + debt_fin_net + S("other_fin_in") - S("other_fin_out")

        non_cash = S("impair_provision") + depr + amort + disp_loss  # 63 非付现成本
        cfo = S("cfo")
        cfo_surplus = cfo - non_cash                          # 64 经营补偿后现金盈余
        fcf = cfo - net_invest - int_paid                     # 65 FCF
        cash_net = cfo - net_invest + fin_net                 # 66 现金流净额
        cfi = S("cfi")
        cff = S("cff")

        # 77 现金流风格八分类（按经营/投资/筹资净额正负）
        def style(row_cfo, row_cfi, row_cff):
            signs = []
            for v in (row_cfo, row_cfi, row_cff):
                if pd.isna(v):
                    return None
                signs.append("+" if v >= 0 else "-")
            key = "".join(signs)
            return {
                "+++": "妖精型(融资投资项目)", "++-": "老母鸡型(高股息)",
                "+-+": "蛮牛型(项目前景杠杆)", "+--": "明星型(市场空间)",
                "-++": "骗吃骗喝型(不关注)", "-+-": "混吃等死型(不关注)",
                "--+": "赌徒型(拐点)", "---": "大出血型(不关注)",
            }[key]
        styles = pd.Series(
            [style(cfo.get(p), cfi.get(p), cff.get(p)) for p in self.periods],
            index=self.periods, dtype=object)

        # ---- 框架补充（框架 L0/L5 利润含金量验证）----
        sales_cash_ratio = div(S("sales_cash"), rev)           # 销售收现比(收入现金含量)
        np_cash = div(cfo, S("net_profit"))                    # 净现比(CFO/净利润)
        buy_s = self.Sopt("buy_services")
        if buy_s is not None:
            # 购货付现比: 原模型收入/成本分析"现金支付比例"口径(分母含17%增值税假设)
            pay_ratio = div(buy_s, S("cost") * 1.17)
        else:
            pay_ratio = pd.Series(np.nan, index=self.periods)

        A = m.add
        A("投资活动", "长期资产净投资", net_lt_invest, "yi")
        A("投资活动", "扩张性资本投资", exp_capex, "yi")
        A("投资活动", "期初长期资产", lt_assets_begin, "yi")
        A("投资活动", "扩张比例", exp_ratio, "pct")
        A("投资活动", "研发投入", rd, "yi")
        A("投资活动", "营收增长", d_rev, "yi")
        A("投资活动", "研发效率(Δ收入/(研发+扩张投资))", rd_eff, "x")
        A("投资活动", "净合并(取得-处置子公司)", net_ma, "yi")
        A("投资活动", "其他投资收到", other_inv_in, "yi")
        A("投资活动", "其他投资支付", other_inv_out, "yi")
        A("投资活动", "净其他投资", net_other_inv, "yi")
        A("投资活动", "净投资额", net_invest, "yi")
        A("筹资活动", "借款收到(含发债)", borrow_in, "yi")
        A("筹资活动", "偿付利息", int_paid, "yi")
        A("筹资活动", "债务筹资净额", debt_fin_net, "yi")
        A("筹资活动", "吸收投资", equity_in, "yi")
        A("筹资活动", "股利支付", div_paid, "yi")
        A("筹资活动", "股权筹资净额", equity_fin_net, "yi")
        A("筹资活动", "筹资净额(模型口径)", fin_net, "yi")
        A("现金流合成", "非付现成本", non_cash, "yi")
        A("现金流合成", "经营活动现金流净额", cfo, "yi")
        A("现金流合成", "经营补偿后现金盈余", cfo_surplus, "yi")
        A("现金流合成", "自由现金流FCF", fcf, "yi")
        A("现金流合成", "现金流净额(模型口径)", cash_net, "yi")
        A("现金流合成", "投资活动现金流净额", cfi, "yi")
        A("现金流合成", "筹资活动现金流净额(报表)", cff, "yi")
        A("利润含金量", "销售收现比(收现/营业收入)", sales_cash_ratio, "pct")
        A("利润含金量", "净现比(CFO/净利润)", np_cash, "pct")
        A("利润含金量", "购货付现比(付现/营业成本×1.17)", pay_ratio, "pct")
        A("现金流风格", "现金流风格八分类", styles, "txt")
        return m

    # ============================================================ 债务分析
    def debt(self) -> Module:
        m = Module("债务分析")
        S, prev, div = self.S, self.prev, self.div
        cf_m = self.cashflow()
        ac_m = self.asset_capital()
        cg = lambda label: cf_m.get(label)
        ag = lambda label: ac_m.get(label)

        cash_end = S("cash")                                   # 5 期末现金需求
        invest_need = (cg("长期资产净投资") + cg("净合并(取得-处置子公司)")
                       + cg("净其他投资"))                       # 10 投资资金需求
        cfo = S("cfo")
        self_suff = (cfo / invest_need.replace(0, np.nan)).clip(upper=1.0)  # 15 现金自给率
        fin_need = invest_need - cfo                           # 19 投资筹资需求
        fin_net = cg("筹资净额(模型口径)")                      # 20
        fx_other = S("fx_effect")                              # 21 汇兑等其他
        cash_net = fx_other + fin_net - fin_need               # 22 现金净增加

        ibd = ag("有息负债合计")                                # 26 有息债务
        total_capital = ag("资本总额(模型口径)")                 # 43 投入资本合计
        debt_ratio = div(ibd, total_capital)                   # 27 债务资金比例
        st_debt, lt_debt = self._st_debt(), self._lt_debt()
        d_st = st_debt - prev(st_debt)
        d_lt = lt_debt - prev(lt_debt)
        d_ibd = ibd - prev(ibd)
        int_exp = S("int_exp")                                 # 40/47 债务成本=利息支出
        eq = S("total_eq")                                     # 41
        eq_ratio = div(eq, total_capital)                      # 42 股权资金比例
        avg_debt = (ibd + prev(ibd)) / 2                       # 48 平均有息债务
        pre_tax_cost = div(int_exp, avg_debt)                  # 49 税前债务成本
        ev_m = self.equity_value()
        tax_rate = ev_m.get("实际税率")
        after_tax_cost = pre_tax_cost * (1 - tax_rate)         # 50 税后债务成本
        cash_begin = prev(S("cash"))                           # 54 期初货币资金
        theory_end = cash_begin + cash_net                     # 55 理论期末
        err = cash_end - theory_end                            # 56 误差项

        # ---- 框架补充（框架 L5 偿债能力验证）----
        ebit = ev_m.get("EBIT")
        ebitda = ev_m.get("EBITDA")
        int_cover = div(ebit, int_exp)                         # 利息保障倍数(EBIT)
        int_cover_ebitda = div(ebitda, int_exp)                # 利息保障倍数(EBITDA)
        cfo_ibd = div(cfo, ibd)                                # 经营现金流/有息负债
        net_debt_ebitda = div(ibd - cash_end, ebitda)          # 净债务/EBITDA

        A = m.add
        A("资金平衡", "期末现金(货币资金)", cash_end, "yi")
        A("资金平衡", "投资资金需求", invest_need, "yi")
        A("资金平衡", "经营现金流净额", cfo, "yi")
        A("资金平衡", "现金自给率", self_suff, "pct")
        A("资金平衡", "投资筹资需求", fin_need, "yi")
        A("资金平衡", "筹资净额", fin_net, "yi")
        A("资金平衡", "汇兑等其他", fx_other, "yi")
        A("资金平衡", "现金净增加(模型口径)", cash_net, "yi")
        A("债务结构", "有息债务", ibd, "yi")
        A("债务结构", "其中:短期有息", st_debt, "yi")
        A("债务结构", "其中:长期有息", lt_debt, "yi")
        A("债务结构", "新增短期有息", d_st, "yi")
        A("债务结构", "新增长期有息", d_lt, "yi")
        A("债务结构", "新增有息债务", d_ibd, "yi")
        A("债务结构", "债务资金比例", debt_ratio, "pct")
        A("债务结构", "股东权益", eq, "yi")
        A("债务结构", "股权资金比例", eq_ratio, "pct")
        A("债务结构", "投入资本合计", total_capital, "yi")
        A("债务成本", "利息支出(债务成本)", int_exp, "yi")
        A("债务成本", "平均有息债务", avg_debt, "yi")
        A("债务成本", "税前债务成本", pre_tax_cost, "pct")
        A("债务成本", "税后债务成本", after_tax_cost, "pct")
        A("偿债能力", "利息保障倍数(EBIT)", int_cover, "x")
        A("偿债能力", "利息保障倍数(EBITDA)", int_cover_ebitda, "x")
        A("偿债能力", "经营现金流/有息负债", cfo_ibd, "pct")
        A("偿债能力", "净债务/EBITDA", net_debt_ebitda, "x")
        A("勾稽校验", "期初货币资金", cash_begin, "yi")
        A("勾稽校验", "理论期末现金", theory_end, "yi")
        A("勾稽校验", "误差项", err, "yi")
        return m

    # ============================================================ 财务分析(汇总)
    def summary(self) -> Module:
        m = Module("财务分析")
        S, prev, div = self.S, self.prev, self.div
        ev_m = self.equity_value()
        ac_m = self.asset_capital()
        cf_m = self.cashflow()
        debt_m = self.debt()
        eg, ag, cg, dg = ev_m.get, ac_m.get, cf_m.get, debt_m.get

        eq = S("total_eq")
        ibd = ag("有息负债合计")
        st_debt, lt_debt = self._st_debt(), self._lt_debt()
        fin_assets = self._financial_assets()
        noplat = eg("NOPLAT")
        net_op_assets = eq + st_debt + lt_debt - fin_assets     # 净经营资产
        roic = div(noplat, net_op_assets)                       # ROIC
        roic_dil = div(noplat, eq + st_debt + lt_debt)          # ROIC摊薄
        ebitda = eg("EBITDA")
        tax = S("income_tax")
        d_wc = ag("追加营运资本")
        exp_capex = cg("扩张性资本投资")
        fcff = ebitda - tax - d_wc - exp_capex                  # FCFF
        op_fcff = cg("经营补偿后现金盈余")                       # 经营FCFF
        int_exp, int_inc = S("int_exp"), S("int_inc")
        tax_rate = eg("实际税率")
        d_ibd = dg("新增有息债务")
        fcfe = fcff + (int_exp - int_inc) * (1 - tax_rate) + d_ibd  # FCFE

        A = m.add
        A("价值创造", "净经营资产", net_op_assets, "yi")
        A("价值创造", "NOPLAT", noplat, "yi")
        A("价值创造", "ROIC", roic, "pct")
        A("价值创造", "ROIC(摊薄)", roic_dil, "pct")
        A("价值创造", "EVA", eg("经济增加值EVA"), "yi")
        A("自由现金流", "EBITDA", ebitda, "yi")
        A("自由现金流", "所得税", tax, "yi")
        A("自由现金流", "追加营运资本", d_wc, "yi")
        A("自由现金流", "扩张性资本投资", exp_capex, "yi")
        A("自由现金流", "FCFF", fcff, "yi")
        A("自由现金流", "经营FCFF", op_fcff, "yi")
        A("自由现金流", "FCFE", fcfe, "yi")
        A("回报对比", "ROE", eg("ROE"), "pct")
        A("回报对比", "核心ROIC", ag("核心ROIC"), "pct")
        A("回报对比", "去杠杆ROCE", eg("去杠杆ROCE"), "pct")
        A("回报对比", "税前债务成本", dg("税前债务成本"), "pct")
        A("回报对比", "股权资金成本率(假设)", pd.Series(self.cqe, index=self.periods), "pct")
        return m

    # 缓存 equity_value 实例，供其他模块复用（避免重复计算）
    @property
    def _ev(self):
        return self.equity_value

    def run_all(self) -> dict:
        return {
            "股权增加值分析": self.equity_value(),
            "资产资本分析": self.asset_capital(),
            "现金流分析": self.cashflow(),
            "债务分析": self.debt(),
            "财务分析": self.summary(),
        }
