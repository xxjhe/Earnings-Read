# -*- coding: utf-8 -*-
"""原《财务分析模型（季度）》112 张图表的复现规格（数据无关，任意公司通用）。

每张图: {"id", "sec", "freq", "title", "stack", "series": [(名称, 形态, 格式, 引用)]}
  sec   : 报告章节归属（年度模块名 / "报表概览" / "季度-xxx"）
  freq  : "A" 年度（末11期） / "Q" 季度（末13期）
  形态  : "bar" | "line" | "area"
  格式  : "yi" 亿元 | "pct" 百分比 | "days" 天 | "x" 倍/次
  引用  : ("e", 模块, 指标) 引擎指标 | ("r", canon) 原始字段 | ("const", n)
          ("add"/"sub"/"mul"/"div"/"neg", [引用...])
          ("yoy", 引用) 同比(A=1期,Q=4期) | ("qoq", 引用) 环比
          ("diff", 引用) 一阶差分 | ("avg2", 引用) 两期均值
跳过 18 张（数据在 tushare 免费口径不可得）：账龄/坏账附注、折旧成新附注、
费用附注明细、人均费用、成本分析、收入分析（分部/附注数据）。
重复图已合并：chart121→120, chart159→158, chart157→156, chart87→66, chart49→39。
"""

EV, AC, CF, DB, SM = "股权增加值分析", "资产资本分析", "现金流分析", "债务分析", "财务分析"


def E(mod, label):
    return ("e", mod, label)


def R(canon):
    return ("r", canon)


def div(a, b):
    return ("div", [a, b])


def sub(*args):
    return ("sub", list(args))


def add(*args):
    return ("add", list(args))


def neg(a):
    return ("neg", [a])


def yoy(a):
    return ("yoy", [a])


def qoq(a):
    return ("qoq", [a])


def diff(a):
    return ("diff", [a])


def avg2(a):
    return ("avg2", [a])


def const(n):
    return ("const", n)


_REV = E(EV, "营业收入")

# 资本结构(权益+负债构成)系列，年度/季度共用（库存股取负，权益其它为残差）
def _cap_struct_series():
    eq_parts = [R("share_capital"), R("cap_reserve"), neg(R("treasury")),
                R("surplus_reserve"), R("undistributed")]
    other_eq = sub(R("parent_eq"), *eq_parts)          # 权益其它 = 归母 - 五项
    return [
        ("股本", "bar", "yi", R("share_capital")),
        ("资本公积", "bar", "yi", R("cap_reserve")),
        ("减:库存股", "bar", "yi", neg(R("treasury"))),
        ("盈余公积金", "bar", "yi", R("surplus_reserve")),
        ("未分配利润", "bar", "yi", R("undistributed")),
        ("其它(权益)", "bar", "yi", other_eq),
        ("短期负债", "bar", "yi", E(AC, "短期有息负债")),
        ("长期负债", "bar", "yi", E(AC, "长期有息负债")),
        ("其他项(负债)", "bar", "yi", E(AC, "无息及其他负债")),
    ]


# 资产结构系列（其他项 = 资产总额 - 四大块）
# 注: 原表资产结构区"营运资产"(r55) = 营运资产合计-营运负债 = 营运资本净额口径
def _asset_struct_series():
    blocks = [E(AC, "金融资产合计"), E(AC, "营运资本"), E(AC, "长期股权投资"), E(AC, "长期经营资产")]
    other = sub(E(AC, "资产总额(模型口径)"), *blocks)
    return [
        ("金融资产", "bar", "yi", blocks[0]),
        ("营运资产(净额)", "bar", "yi", blocks[1]),
        ("长期股权投资", "bar", "yi", blocks[2]),
        ("长期经营资产", "bar", "yi", blocks[3]),
        ("其他项", "bar", "yi", other),
    ]


# 长期运营资产合计（原表 r156/r211 口径 = 固定资产+在建+无形+开发+商誉+长待摊）
_LT_OP_RAW = ("add", [R("fixed_detail"), R("cip_detail"), R("intangible"),
                      R("dev_exp"), R("goodwill"), R("lt_prepaid")])


_SPECS = [
    # ================= 报表概览（利润表/现金流量表，年度） =================
    {"id": "chart122", "sec": "报表概览", "freq": "A", "title": "营业收入与增速", "stack": False,
     "series": [("营业收入", "bar", "yi", _REV), ("收入增速", "line", "pct", E(EV, "营业收入增长率"))]},
    {"id": "chart10", "sec": "报表概览", "freq": "A", "title": "盈利能力比率", "stack": False,
     "series": [("毛利率", "line", "pct", E(EV, "毛利率")),
                ("净利率", "line", "pct", div(R("net_profit"), _REV)),
                ("销售费率", "line", "pct", div(R("sell_exp"), _REV)),
                ("管理费率(含研发)", "line", "pct", div(R("manage_exp"), _REV))]},
    {"id": "chart9", "sec": "报表概览", "freq": "A", "title": "期间费用与减值比率", "stack": False,
     "series": [("销售费率", "line", "pct", div(R("sell_exp"), _REV)),
                ("管理费率(含研发)", "line", "pct", div(R("manage_exp"), _REV)),
                ("财务费率", "line", "pct", div(R("fin_exp"), _REV)),
                ("减值率", "line", "pct", div(add(R("impair_asset"), R("impair_credit")), _REV))]},
    {"id": "chart8", "sec": "报表概览", "freq": "A", "title": "总费用率(费用+减值)/营业收入", "stack": False,
     "series": [("总费用率", "line", "pct",
                 div(add(R("sell_exp"), R("manage_exp"), R("fin_exp"),
                         R("impair_asset"), R("impair_credit")), _REV))]},
    {"id": "chart11", "sec": "报表概览", "freq": "A", "title": "财务费用与财务费率", "stack": False,
     "series": [("财务费用", "bar", "yi", R("fin_exp")),
                ("财务费率", "line", "pct", div(R("fin_exp"), _REV))]},
    {"id": "chart12", "sec": "报表概览", "freq": "A", "title": "营收成本费用构成", "stack": True,
     "series": [("营业成本", "area", "yi", R("cost")),
                ("税金及附加", "area", "yi", R("tax_surcharge")),
                ("销售费用", "area", "yi", R("sell_exp")),
                ("管理费用(含研发)", "area", "yi", R("manage_exp")),
                ("财务费用", "area", "yi", R("fin_exp")),
                ("资产减值损失", "area", "yi", R("impair_asset")),
                ("信用减值损失", "area", "yi", R("impair_credit")),
                ("营业利润", "area", "yi", R("op_profit"))]},
    {"id": "chart15", "sec": "报表概览", "freq": "A", "title": "经营现金流/息前税后经营利润", "stack": False,
     "series": [("收益含金量", "line", "pct", div(R("cfo"), E(EV, "息前税后经营利润")))]},
    {"id": "chart16", "sec": "报表概览", "freq": "A", "title": "购建长期资产支付的现金(资本开支)", "stack": False,
     "series": [("资本开支", "bar", "yi", R("capex"))]},

    # ================= 股权增加值分析（年度） =================
    {"id": "chart137", "sec": EV, "freq": "A", "title": "营业收入去向构成", "stack": True,
     "series": [("营业成本", "area", "yi", E(EV, "营业成本")),
                ("总费用", "area", "yi", E(EV, "总费用")),
                ("经营所得税", "area", "yi", E(EV, "经营所得税")),
                ("息前税后经营利润", "area", "yi", E(EV, "息前税后经营利润"))]},
    {"id": "chart131", "sec": EV, "freq": "A", "title": "财务费用中的利息支出", "stack": False,
     "series": [("利息支出", "line", "yi", E(EV, "利息支出"))]},
    {"id": "chart132", "sec": EV, "freq": "A", "title": "利息率(利息收入/金融资产)", "stack": False,
     "series": [("利息率", "line", "pct", E(EV, "利息率"))]},
    {"id": "chart136", "sec": EV, "freq": "A", "title": "研发费用率", "stack": False,
     "series": [("研发费用率", "line", "pct", div(E(CF, "研发投入"), _REV))]},
    {"id": "chart140", "sec": EV, "freq": "A", "title": "阶段利润1(收入-成本-销售-税金)/营业收入", "stack": False,
     "series": [("阶段利润1/营收", "line", "pct",
                 div(E(EV, "阶段利润1(收入-成本-销售-税金)"), _REV))]},
    {"id": "chart133", "sec": EV, "freq": "A", "title": "净利率", "stack": False,
     "series": [("净利率", "line", "pct", div(E(EV, "净利润"), _REV))]},
    {"id": "chart141", "sec": EV, "freq": "A", "title": "归母净利率(归母/营业收入)", "stack": False,
     "series": [("归母净利率", "line", "pct", div(E(EV, "归母净利润"), _REV))]},
    {"id": "chart139", "sec": EV, "freq": "A", "title": "净利润变化拆分", "stack": False,
     "series": [("毛利增加", "bar", "yi", E(EV, "毛利增加")),
                ("费用减少", "bar", "yi", E(EV, "费用减少")),
                ("税费减少", "bar", "yi", E(EV, "税费减少")),
                ("财务收入增加", "bar", "yi", E(EV, "财务收入增加"))]},
    {"id": "chart138", "sec": EV, "freq": "A", "title": "净利润增长贡献拆分", "stack": False,
     "series": [("费用减少", "bar", "yi", E(EV, "费用减少")),
                ("税费减少", "bar", "yi", E(EV, "税费减少")),
                ("财务收入增加", "bar", "yi", E(EV, "财务收入增加")),
                ("净利润增加额", "bar", "yi", E(EV, "净利润增加额"))]},
    {"id": "chart134", "sec": EV, "freq": "A", "title": "表观ROCE", "stack": False,
     "series": [("表观ROCE", "line", "pct", E(EV, "表观ROCE"))]},
    {"id": "chart135", "sec": EV, "freq": "A", "title": "去杠杆ROCE", "stack": False,
     "series": [("去杠杆ROCE", "line", "pct", E(EV, "去杠杆ROCE"))]},

    # ================= 资产资本分析（年度） =================
    {"id": "chart77", "sec": AC, "freq": "A", "title": "资产结构", "stack": True,
     "series": _asset_struct_series()},
    {"id": "chart76", "sec": AC, "freq": "A", "title": "资本结构(权益+负债构成)", "stack": True,
     "series": _cap_struct_series()},
    {"id": "chart88", "sec": AC, "freq": "A", "title": "金融资产/资产总额", "stack": False,
     "series": [("金融资产占比", "line", "pct", div(E(AC, "金融资产合计"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart78", "sec": AC, "freq": "A", "title": "营运资产/资产总额", "stack": False,
     "series": [("营运资产占比", "line", "pct", div(E(AC, "营运资产"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart92", "sec": AC, "freq": "A", "title": "长期股权投资/资产总额", "stack": False,
     "series": [("长投占比", "line", "pct", div(E(AC, "长期股权投资"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart91", "sec": AC, "freq": "A", "title": "长期经营资产/资产总额", "stack": False,
     "series": [("长期经营资产占比", "line", "pct", div(E(AC, "长期经营资产"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart90", "sec": AC, "freq": "A", "title": "资本公积/资本总额", "stack": False,
     "series": [("资本公积占比", "line", "pct", div(R("cap_reserve"), E(AC, "资本总额(模型口径)")))]},
    {"id": "chart89", "sec": AC, "freq": "A", "title": "(盈余公积+未分配利润)/资本总额", "stack": False,
     "series": [("留存收益占比", "line", "pct",
                 div(add(R("surplus_reserve"), R("undistributed")), E(AC, "资本总额(模型口径)")))]},
    {"id": "chart79", "sec": AC, "freq": "A", "title": "有息负债/资产总额", "stack": False,
     "series": [("有息负债占比", "line", "pct", div(E(AC, "有息负债合计"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart81", "sec": AC, "freq": "A", "title": "净资产增速", "stack": False,
     "series": [("净资产增速", "line", "pct", yoy(E(AC, "股东权益")))]},
    {"id": "chart50", "sec": AC, "freq": "A", "title": "营运资本合计", "stack": False,
     "series": [("营运资本", "line", "yi", E(AC, "营运资本"))]},
    {"id": "chart83", "sec": AC, "freq": "A", "title": "营运资产构成", "stack": False,
     "series": [("应收票据", "bar", "yi", R("note_rece")),
                ("应收账款净值", "bar", "yi", R("ar")),
                ("长期应收账款净值", "bar", "yi", R("long_rece")),
                ("存货净值", "bar", "yi", R("inventory")),
                ("预付账款", "bar", "yi", R("prepay")),
                ("其他应收账款净值", "bar", "yi", R("other_rece"))]},
    {"id": "chart82", "sec": AC, "freq": "A", "title": "营运负债构成", "stack": False,
     "series": [("应付票据", "bar", "yi", R("note_pay")),
                ("应付账款", "bar", "yi", R("ap")),
                ("预收账款(含合同负债)", "bar", "yi", R("advance")),
                ("应付职工薪酬", "bar", "yi", R("payroll")),
                ("应交税费", "bar", "yi", R("tax_pay"))]},
    {"id": "chart80", "sec": AC, "freq": "A", "title": "长期经营资产构成", "stack": False,
     "series": [("固定资产净值", "bar", "yi", R("fixed_detail")),
                ("在建工程净值", "bar", "yi", R("cip_detail")),
                ("无形资产净值", "bar", "yi", R("intangible")),
                ("开发支出", "bar", "yi", R("dev_exp")),
                ("商誉净值", "bar", "yi", R("goodwill")),
                ("长期待摊费用", "bar", "yi", R("lt_prepaid"))]},
    {"id": "chart93", "sec": AC, "freq": "A", "title": "营业周期", "stack": False,
     "series": [("营业周期", "line", "days", E(AC, "营业周期"))]},
    {"id": "chart86", "sec": AC, "freq": "A", "title": "应收/存货/应付周转天数", "stack": False,
     "series": [("应收天数", "line", "days", E(AC, "应收周转天数")),
                ("存货天数", "line", "days", E(AC, "存货周转天数")),
                ("应付天数", "line", "days", E(AC, "应付周转天数"))]},
    {"id": "chart67", "sec": AC, "freq": "A", "title": "应收账款周转天数", "stack": False,
     "series": [("应收天数", "line", "days", E(AC, "应收周转天数"))]},
    {"id": "chart69", "sec": AC, "freq": "A", "title": "存货周转天数", "stack": False,
     "series": [("存货天数", "line", "days", E(AC, "存货周转天数"))]},
    {"id": "chart68", "sec": AC, "freq": "A", "title": "应付账款周转天数", "stack": False,
     "series": [("应付天数", "line", "days", E(AC, "应付周转天数"))]},
    {"id": "chart70", "sec": AC, "freq": "A", "title": "现金周期", "stack": False,
     "series": [("现金周期", "line", "days", E(AC, "现金周期"))]},
    {"id": "chart66", "sec": AC, "freq": "A", "title": "营运资产周转率", "stack": False,
     "series": [("营运资产周转率", "line", "x", div(_REV, E(AC, "营运资产")))]},
    {"id": "chart84", "sec": AC, "freq": "A", "title": "固定资产周转率", "stack": False,
     "series": [("固定资产周转率", "line", "x", div(_REV, avg2(R("fixed_detail"))))]},
    {"id": "chart85", "sec": AC, "freq": "A", "title": "长期运营资产周转率", "stack": False,
     "series": [("长期运营资产周转率", "line", "x", div(_REV, E(AC, "长期经营资产")))]},
    {"id": "chart74", "sec": AC, "freq": "A", "title": "RE / 股本回报率 / ROCE", "stack": False,
     "series": [("剩余收益RE", "bar", "yi", E(AC, "剩余收益RE")),
                ("股本回报率", "line", "pct", E(AC, "股本回报率")),
                ("ROCE", "line", "pct", E(AC, "ROCE"))]},
    {"id": "chart75", "sec": AC, "freq": "A", "title": "全经营ROIC", "stack": False,
     "series": [("全经营ROIC", "line", "pct", E(AC, "全经营ROIC"))]},

    # ================= 现金流分析（年度） =================
    {"id": "chart148", "sec": CF, "freq": "A", "title": "经营活动现金流净额", "stack": False,
     "series": [("经营现金流净额", "bar", "yi", E(CF, "经营活动现金流净额"))]},
    {"id": "chart143", "sec": CF, "freq": "A", "title": "经营补偿后现金盈余", "stack": False,
     "series": [("经营补偿后现金盈余", "bar", "yi", E(CF, "经营补偿后现金盈余"))]},
    {"id": "chart149", "sec": CF, "freq": "A", "title": "自由现金流FCF", "stack": False,
     "series": [("FCF", "bar", "yi", E(CF, "自由现金流FCF"))]},
    {"id": "chart145", "sec": CF, "freq": "A", "title": "借款收到的现金", "stack": False,
     "series": [("借款收到", "bar", "yi", E(CF, "借款收到(含发债)"))]},
    {"id": "chart144", "sec": CF, "freq": "A", "title": "债务/股权筹资净额", "stack": False,
     "series": [("债务筹资净额", "bar", "yi", E(CF, "债务筹资净额")),
                ("股权筹资净额", "bar", "yi", E(CF, "股权筹资净额"))]},
    {"id": "chart147", "sec": CF, "freq": "A", "title": "债务筹资净额", "stack": False,
     "series": [("债务筹资净额", "bar", "yi", E(CF, "债务筹资净额"))]},
    {"id": "chart142", "sec": CF, "freq": "A", "title": "长期资产扩张性投资支出比例", "stack": False,
     "series": [("扩张比例", "line", "pct", E(CF, "扩张比例"))]},
    {"id": "chart146", "sec": CF, "freq": "A", "title": "研发效率(Δ收入/(研发+扩张投资))", "stack": False,
     "series": [("研发效率", "line", "x", E(CF, "研发效率(Δ收入/(研发+扩张投资))"))]},

    # ================= 债务分析（年度） =================
    {"id": "chart154", "sec": DB, "freq": "A", "title": "现金自给率", "stack": False,
     "series": [("现金自给率", "line", "pct", E(DB, "现金自给率"))]},
    {"id": "chart155", "sec": DB, "freq": "A", "title": "新增有息债务构成", "stack": False,
     "series": [("新增短期借款", "bar", "yi", diff(R("st_loan"))),
                ("新增短期债券", "bar", "yi", diff(R("st_bond"))),
                ("新增一年内到期非流动负债", "bar", "yi", diff(R("ncl_1y"))),
                ("新增长期借款", "bar", "yi", diff(R("lt_loan"))),
                ("新增长期债券", "bar", "yi", diff(R("bond_pay")))]},
    {"id": "chart156", "sec": DB, "freq": "A", "title": "税前债务成本", "stack": False,
     "series": [("税前债务成本", "line", "pct", E(DB, "税前债务成本"))]},

    # ================= 财务分析（年度） =================
    {"id": "chart158", "sec": SM, "freq": "A", "title": "ROIC", "stack": False,
     "series": [("ROIC", "line", "pct", E(SM, "ROIC"))]},
    {"id": "chart160", "sec": SM, "freq": "A", "title": "经营FCFF", "stack": False,
     "series": [("经营FCFF", "bar", "yi", E(SM, "经营FCFF"))]},

    # ================= 季度-报表 =================
    {"id": "chart94", "sec": "季度-报表", "freq": "Q", "title": "单季营业收入增速", "stack": False,
     "series": [("收入增速", "line", "pct", E(EV, "营业收入增长率"))]},
    {"id": "chart13", "sec": "季度-报表", "freq": "Q", "title": "单季费用与减值比率", "stack": False,
     "series": [("销售费率", "line", "pct", div(R("sell_exp"), _REV)),
                ("管理费率(含研发)", "line", "pct", div(R("manage_exp"), _REV)),
                ("财务费率", "line", "pct", div(R("fin_exp"), _REV)),
                ("减值率", "line", "pct", div(add(R("impair_asset"), R("impair_credit")), _REV))]},
    {"id": "chart14", "sec": "季度-报表", "freq": "Q", "title": "单季总费用率", "stack": False,
     "series": [("总费用率", "line", "pct",
                 div(add(R("sell_exp"), R("manage_exp"), R("fin_exp"),
                         R("impair_asset"), R("impair_credit")), _REV))]},
    {"id": "chart17", "sec": "季度-报表", "freq": "Q", "title": "单季经营性现金流净额", "stack": False,
     "series": [("经营现金流净额", "bar", "yi", R("cfo"))]},

    # ================= 季度-股权增加值分析 =================
    {"id": "chart119", "sec": "季度-" + EV, "freq": "Q", "title": "单季营业收入去向构成", "stack": True,
     "series": [("营业成本", "area", "yi", E(EV, "营业成本")),
                ("总费用", "area", "yi", E(EV, "总费用")),
                ("经营所得税", "area", "yi", E(EV, "经营所得税")),
                ("息前税后经营利润", "area", "yi", E(EV, "息前税后经营利润"))]},
    {"id": "chart117", "sec": "季度-" + EV, "freq": "Q", "title": "单季研发投入", "stack": False,
     "series": [("研发投入", "line", "yi", E(CF, "研发投入"))]},
    {"id": "chart118", "sec": "季度-" + EV, "freq": "Q", "title": "单季阶段利润1/营业收入", "stack": False,
     "series": [("阶段利润1/营收", "line", "pct",
                 div(E(EV, "阶段利润1(收入-成本-销售-税金)"), _REV))]},
    {"id": "chart103", "sec": "季度-" + EV, "freq": "Q", "title": "单季利息支出", "stack": False,
     "series": [("利息支出", "line", "yi", E(EV, "利息支出"))]},
    {"id": "chart104", "sec": "季度-" + EV, "freq": "Q", "title": "单季利息率", "stack": False,
     "series": [("利息率", "line", "pct", E(EV, "利息率"))]},
    {"id": "chart105", "sec": "季度-" + EV, "freq": "Q", "title": "单季收益质量(非经常/净利润)", "stack": False,
     "series": [("收益质量", "line", "pct", E(EV, "收益质量(非经常/净利润)"))]},
    {"id": "chart106", "sec": "季度-" + EV, "freq": "Q", "title": "单季表观ROCE", "stack": False,
     "series": [("表观ROCE", "line", "pct", E(EV, "表观ROCE"))]},
    {"id": "chart107", "sec": "季度-" + EV, "freq": "Q", "title": "单季去杠杆ROCE", "stack": False,
     "series": [("去杠杆ROCE", "line", "pct", E(EV, "去杠杆ROCE"))]},
    {"id": "chart120", "sec": "季度-" + EV, "freq": "Q", "title": "单季利润同比原因变化拆分", "stack": False,
     "series": [("毛利增加", "bar", "yi", E(EV, "毛利增加")),
                ("费用减少", "bar", "yi", E(EV, "费用减少")),
                ("税费减少", "bar", "yi", E(EV, "税费减少")),
                ("财务收入增加", "bar", "yi", E(EV, "财务收入增加"))]},

    # ================= 季度-资产资本分析 =================
    {"id": "chart37", "sec": "季度-" + AC, "freq": "Q", "title": "资产结构(季度)", "stack": True,
     "series": _asset_struct_series()},
    {"id": "chart36", "sec": "季度-" + AC, "freq": "Q", "title": "资本结构(季度)", "stack": True,
     "series": _cap_struct_series()},
    {"id": "chart38", "sec": "季度-" + AC, "freq": "Q", "title": "长期股权投资/资产总额(季度)", "stack": False,
     "series": [("长投占比", "line", "pct", div(E(AC, "长期股权投资"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart39", "sec": "季度-" + AC, "freq": "Q", "title": "长期经营资产/资产总额(季度)", "stack": False,
     "series": [("长期经营资产占比", "line", "pct", div(E(AC, "长期经营资产"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart40", "sec": "季度-" + AC, "freq": "Q", "title": "(盈余公积+未分配利润)/资本总额(季度)", "stack": False,
     "series": [("留存收益占比", "line", "pct",
                 div(add(R("surplus_reserve"), R("undistributed")), E(AC, "资本总额(模型口径)")))]},
    {"id": "chart41", "sec": "季度-" + AC, "freq": "Q", "title": "资本公积/资本总额(季度)", "stack": False,
     "series": [("资本公积占比", "line", "pct", div(R("cap_reserve"), E(AC, "资本总额(模型口径)")))]},
    {"id": "chart42", "sec": "季度-" + AC, "freq": "Q", "title": "有息负债/资产总额(季度)", "stack": False,
     "series": [("有息负债占比", "line", "pct", div(E(AC, "有息负债合计"), E(AC, "资产总额(模型口径)")))]},
    {"id": "chart18", "sec": "季度-" + AC, "freq": "Q", "title": "营运资本合计(季度)", "stack": False,
     "series": [("营运资本", "line", "yi", E(AC, "营运资本"))]},
    {"id": "chart44", "sec": "季度-" + AC, "freq": "Q", "title": "净资产同比增速", "stack": False,
     "series": [("净资产同比增速", "line", "pct", yoy(E(AC, "股东权益")))]},
    {"id": "chart45", "sec": "季度-" + AC, "freq": "Q", "title": "净资产环比增速", "stack": False,
     "series": [("净资产环比增速", "line", "pct", qoq(E(AC, "股东权益")))]},
    {"id": "chart46", "sec": "季度-" + AC, "freq": "Q", "title": "营运资产构成(季度)", "stack": False,
     "series": [("应收票据", "bar", "yi", R("note_rece")),
                ("应收账款净值", "bar", "yi", R("ar")),
                ("应收款项融资", "bar", "yi", R("rece_financing")),
                ("合同资产", "bar", "yi", R("contract_asset")),
                ("预付账款", "bar", "yi", R("prepay")),
                ("存货净值", "bar", "yi", R("inventory"))]},
    {"id": "chart47", "sec": "季度-" + AC, "freq": "Q", "title": "营运负债构成(季度)", "stack": False,
     "series": [("应付票据", "bar", "yi", R("note_pay")),
                ("应付账款", "bar", "yi", R("ap")),
                ("预收账款(含合同负债)", "bar", "yi", R("advance")),
                ("应付职工薪酬", "bar", "yi", R("payroll")),
                ("应交税费", "bar", "yi", R("tax_pay"))]},
    {"id": "chart43", "sec": "季度-" + AC, "freq": "Q", "title": "长期经营资产构成(季度)", "stack": False,
     "series": [("固定资产净值", "bar", "yi", R("fixed_detail")),
                ("在建工程净值", "bar", "yi", R("cip_detail")),
                ("无形资产净值", "bar", "yi", R("intangible")),
                ("开发支出", "bar", "yi", R("dev_exp")),
                ("商誉净值", "bar", "yi", R("goodwill")),
                ("长期待摊费用", "bar", "yi", R("lt_prepaid"))]},
    {"id": "chart48", "sec": "季度-" + AC, "freq": "Q", "title": "产能周转情况(天)", "stack": False,
     "series": [("长期运营资产周转天数", "line", "days",
                 div(("mul", [const(90), _LT_OP_RAW]), _REV))]},

    # ================= 季度-现金流分析 =================
    {"id": "chart151", "sec": "季度-" + CF, "freq": "Q", "title": "单季经营补偿后现金盈余", "stack": False,
     "series": [("经营补偿后现金盈余", "bar", "yi", E(CF, "经营补偿后现金盈余"))]},
    {"id": "chart153", "sec": "季度-" + CF, "freq": "Q", "title": "单季借款收到的现金", "stack": False,
     "series": [("借款收到", "line", "yi", E(CF, "借款收到(含发债)"))]},
    {"id": "chart152", "sec": "季度-" + CF, "freq": "Q", "title": "单季债务/股权筹资净额", "stack": False,
     "series": [("债务筹资净额", "bar", "yi", E(CF, "债务筹资净额")),
                ("股权筹资净额", "bar", "yi", E(CF, "股权筹资净额"))]},
    {"id": "chart150", "sec": "季度-" + CF, "freq": "Q", "title": "单季扩张性投资支出比例", "stack": False,
     "series": [("扩张比例", "line", "pct", E(CF, "扩张比例"))]},
]

# 原模型中因数据不可得而跳过的图（附注/账龄/分部/授信额度）
SKIPPED = [
    ("chart1", "费用/每人(需员工人数，附注数据)"),
    ("chart2", "管理费用明细附注"),
    ("chart3", "附注-研发/人员"),
    ("chart4", "附注-存货或费用明细"),
    ("chart5", "坏账计提比例(账龄附注)"),
    ("chart6", "存货构成附注"),
    ("chart7", "附注单项"),
    ("chart71", "坏账计提比例(账龄附注，年度)"),
    ("chart34", "坏账计提比例(账龄附注，季度)"),
    ("chart72", "应收账款账龄结构(年度)"),
    ("chart35", "应收账款账龄结构(季度)"),
    ("chart73", "当期折旧率/固定资产成新率(需固定资产原值附注)"),
    ("chart161-164", "成本分析(分产品成本拆分，Wind 分部数据)"),
    ("chart165-166", "收入分析(分产品收入拆分，Wind 分部数据)"),
    ("chart153·系列2", "授信额度(非财报数据，已仅从该图剔除)"),
]

SPECS = _SPECS
