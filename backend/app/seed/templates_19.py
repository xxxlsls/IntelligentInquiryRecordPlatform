"""
19 类电诈案由模板 + 通用模板种子数据（对应需求文档 12.1 / FR-3.3.1）

设计：
- COMMON_QUESTIONS 定义跨案由通用的标准问题集（按五章节组织）；
- CATEGORIES 定义 19 类案由的名称、编码、特征信号词（严格取自 12.1）与专属补充问题；
- 通用模板作为兜底（12.1 说明），适用于无法归入 19 类或跨类组合情形；
- build_templates() 组装为可供 template_service 创建的模板结构。

信号词严格对应 12.1 案由清单的"典型特征信号词"列，用于 AI 推荐的 F_sig 因子。
"""

from app.core.enums import Chapter

# ============================================================
# 通用标准问题集（按大纲章节，五章节结构 FR-3.3.3）
# 每项：(question, target_elements)
# ============================================================
COMMON_QUESTIONS: dict[Chapter, list[tuple[str, str | None]]] = {
    Chapter.FIXED_OPENING: [
        ("请说明你的姓名、出生日期、身份证号码、住址及工作单位。", "P-01"),
        ("你是否知晓如实陈述的义务与作伪证的法律责任？", None),
        ("本次询问你是否需要申请回避或聘请翻译？", None),
    ],
    Chapter.CONTACT_LURE: [
        ("对方是通过什么方式、什么时间首次与你取得联系的？", "C-01"),
        ("对方使用了哪些电话号码、聊天账号或网址与你联系？请提供具体信息。", "C-01,N-02,N-04"),
        ("你是否点击过对方发来的链接、二维码，或下载过指定 APP？", "N-01,N-02,N-03"),
    ],
    Chapter.FRAUD_PROCESS: [
        ("请详细描述你被骗的完整经过。", None),
        ("对方自称是什么身份？以什么理由让你进行操作？", "P-02"),
        ("整个过程中你是否与对方进行过屏幕共享或远程控制？", "N-05"),
    ],
    Chapter.FUND_LOSS: [
        ("请明确每笔转账的时间、金额及支付方式。", "F-01,F-02,F-03"),
        ("请提供你的转出银行卡号及对方收款卡号、户名和开户行。", "F-04,F-05,F-06"),
        ("请提供转账流水号，并说明累计损失总额。", "F-07,F-08"),
    ],
    Chapter.EVIDENCE_SUPPLEMENT: [
        ("你是否保留了通话记录、转账凭证、聊天截图等证据材料？", None),
        ("是否涉及快递包裹往来？如有请提供快递单号与收发信息。", "D-01,D-04"),
        ("关于本案你还有其他需要补充说明的情况吗？", None),
    ],
}


# ============================================================
# 19 类案由定义（严格对应 12.1 案由清单与特征信号词）
# 每项：(案由名称, 模板编码, [特征信号词], 模板描述, {章节: [(专属问题, 目标要素)]})
# ============================================================
CATEGORIES: list[tuple] = [
    (
        "冒充电商物流客服", "TPL_01",
        ["退款", "理赔", "客服", "快递丢失", "刷单理赔"],
        "冒充电商或物流客服，以退款理赔、快递丢失赔付为由诱导受害人转账的诈骗手法。",
        {Chapter.CONTACT_LURE: [("对方自称是哪个电商/快递平台的客服？工号或店铺名称是什么？", "P-02")]},
    ),
    (
        "网络婚恋交友", "TPL_02",
        ["交友", "婚恋", "情感", "投资", "聊天软件"],
        "以婚恋交友为名建立情感关系，进而诱导投资或转账的诈骗手法（俗称杀猪盘）。",
        {Chapter.CONTACT_LURE: [("你们是通过哪个交友/聊天软件认识的？对方账号是什么？", "N-04")]},
    ),
    (
        "虚假投资理财", "TPL_03",
        ["投资", "理财", "炒股", "APP", "高回报", "亏损"],
        "以高额回报为诱饵，诱导受害人下载虚假投资 APP 进行炒股、理财投资造成亏损的诈骗手法。",
        {
            Chapter.CONTACT_LURE: [("你下载的投资 APP 叫什么名称？从哪里下载的？", "N-03"),
                                  ("是谁推荐你进行投资的？通过什么渠道联系？", "N-04")],
            Chapter.FUND_LOSS: [("你在该平台投入的总金额和显示亏损金额分别是多少？", "F-02,F-08")],
        },
    ),
    (
        "虚假征信", "TPL_04",
        ["征信", "注销校园贷", "信用修复", "央行征信"],
        "冒充金融监管或银行人员，以注销校园贷、修复征信为由诱导转账的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("对方声称你的征信存在什么异常？要求你如何操作？", "P-02")]},
    ),
    (
        "刷单返利", "TPL_05",
        ["刷单", "返利", "佣金", "任务", "兼职"],
        "以刷单兼职返佣金为诱饵，前期小额返利后诱导大额充值无法提现的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("你参与的刷单任务是通过什么平台发布的？", "N-02,N-03")]},
    ),
    (
        "冒充公检法", "TPL_06",
        ["公检法", "通缉令", "涉嫌洗钱", "安全账户"],
        "冒充公安、检察、法院人员，以涉嫌犯罪、通缉令为由要求转入安全账户的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("对方自称是哪个单位的？是否向你出示过通缉令或证件？", "P-02")]},
    ),
    (
        "冒充领导熟人", "TPL_07",
        ["领导", "熟人", "换号", "急用钱"],
        "冒充领导或熟人，以换号、急用钱为由诱导受害人转账的诈骗手法。",
        {Chapter.CONTACT_LURE: [("对方是通过什么号码或账号联系你的？是否自称换了号码？", "C-01,N-04")]},
    ),
    (
        "冒充客服退款", "TPL_08",
        ["退款", "取消会员", "误操作理赔"],
        "冒充客服以退款、取消会员、误操作理赔为由诱导操作的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("对方以什么理由要求你操作退款或取消会员？", "P-02")]},
    ),
    (
        "虚假购物服务", "TPL_09",
        ["低价", "代购", "预付", "不发货"],
        "以低价代购、预付货款为名收款后不发货的诈骗手法。",
        {Chapter.CONTACT_LURE: [("你是在哪个平台或渠道看到的购物信息？", "N-02,N-03")]},
    ),
    (
        "虚假贷款", "TPL_10",
        ["贷款", "无抵押", "刷流水", "解冻金"],
        "以无抵押低息贷款为诱饵，要求缴纳刷流水、解冻金等费用的诈骗手法。",
        {Chapter.FUND_LOSS: [("对方以什么名目要求你缴纳费用（保证金/解冻金/刷流水）？", "F-02,F-03")]},
    ),
    (
        "代办信用卡", "TPL_11",
        ["代办", "信用卡", "提额", "手续费"],
        "以代办信用卡、提升额度为由收取手续费的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("对方承诺代办何种信用卡或提额服务？收取了多少手续费？", "F-02")]},
    ),
    (
        "游戏产品交易", "TPL_12",
        ["游戏账号", "装备", "代练", "私下交易"],
        "以游戏账号、装备交易或代练为名进行私下交易诈骗的手法。",
        {Chapter.CONTACT_LURE: [("交易是通过哪个游戏或平台进行的？是否脱离平台私下交易？", "N-02,N-04")]},
    ),
    (
        "网络游戏虚假交易", "TPL_13",
        ["充值", "返利", "客服锁单"],
        "网络游戏内虚假充值返利，以客服锁单为由诱导继续充值的诈骗手法。",
        {Chapter.FUND_LOSS: [("你累计充值金额是多少？对方以锁单为由要求你继续充值吗？", "F-02,F-08")]},
    ),
    (
        "中奖抽奖", "TPL_14",
        ["中奖", "领奖", "税金", "手续费"],
        "以中奖领奖为由要求缴纳税金、手续费的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("对方告知你中了什么奖？要求缴纳哪些费用才能领奖？", "F-02")]},
    ),
    (
        "红包返利", "TPL_15",
        ["红包", "返利", "群", "充值返"],
        "以红包返利、群内充值返现为由诱导转账的诈骗手法。",
        {Chapter.CONTACT_LURE: [("你是通过哪个群或平台参与的红包返利活动？", "N-04")]},
    ),
    (
        "冒充军警购物", "TPL_16",
        ["军警", "采购", "物资", "供应商"],
        "冒充军警单位采购物资，诱导供应商垫资采购的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("对方自称是哪个军警单位？要求你采购何种物资？", "P-02")]},
    ),
    (
        "虚假网络招嫖", "TPL_17",
        ["招嫖", "服务", "定金", "刷单"],
        "以网络招嫖提供服务为由收取定金、保证金的诈骗手法。",
        {Chapter.FUND_LOSS: [("对方以什么名目要求你支付定金或保证金？", "F-02,F-03")]},
    ),
    (
        "医保社保诈骗", "TPL_18",
        ["医保", "社保", "异常", "涉嫌骗保"],
        "冒充医保社保部门，以账户异常、涉嫌骗保为由诱导转账的诈骗手法。",
        {Chapter.FRAUD_PROCESS: [("对方声称你的医保/社保账户存在什么异常？", "P-02")]},
    ),
    (
        "其他新型网络诈骗", "TPL_19",
        ["屏幕共享", "远程控制", "虚拟币", "新手法"],
        "利用屏幕共享、远程控制、虚拟币等新型手法实施的网络诈骗。",
        {Chapter.FRAUD_PROCESS: [("对方是否要求你开启屏幕共享或安装远程控制软件？", "N-05"),
                                ("是否涉及虚拟币（如 USDT）转账？", "F-03")]},
    ),
]


def build_templates() -> list[dict]:
    """组装 19 类案由模板 + 通用兜底模板为可创建的结构。

    :return: 模板字典列表，每项含 name/code/category/description/is_general/questions/signal_words
    """
    templates: list[dict] = []

    # 19 类案由模板
    for idx, (name, code, signal_words, description, extra_questions) in enumerate(CATEGORIES, start=1):
        questions = []
        # 通用问题集
        for chapter in Chapter:
            for q, target in COMMON_QUESTIONS[chapter]:
                questions.append({
                    "chapter": chapter.value, "question": q,
                    "sort_order": len(questions), "target_elements": target,
                })
        # 案由专属问题（插入到对应章节末尾）
        for chapter, extra_list in extra_questions.items():
            for q, target in extra_list:
                questions.append({
                    "chapter": chapter.value, "question": q,
                    "sort_order": len(questions), "target_elements": target,
                })
        # 特征信号词（权重默认 1.0，核心案由词可加权）
        signal_word_items = [{"word": w, "weight": 1.0} for w in signal_words]

        templates.append({
            "name": f"{name}类询问模板",
            "code": code,
            "category": name,
            "description": description,
            "is_general": False,
            "is_enabled": True,
            "sort_order": idx,
            "questions": questions,
            "signal_words": signal_word_items,
        })

    # 通用兜底模板（12.1：适用于无法归入 19 类或跨类组合情形）
    general_questions = []
    for chapter in Chapter:
        for q, target in COMMON_QUESTIONS[chapter]:
            general_questions.append({
                "chapter": chapter.value, "question": q,
                "sort_order": len(general_questions), "target_elements": target,
            })
    templates.append({
        "name": "通用询问模板",
        "code": "TPL_GENERAL",
        "category": "通用",
        "description": "适用于无法归入 19 类具体案由或跨类组合情形的通用询问兜底模板。",
        "is_general": True,
        "is_enabled": True,
        "sort_order": 100,
        "questions": general_questions,
        "signal_words": [{"word": "诈骗", "weight": 0.5}, {"word": "被骗", "weight": 0.5}],
    })

    return templates
