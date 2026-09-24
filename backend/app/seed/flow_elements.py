"""
五流要素定义目录种子数据（对应需求文档 5.1 五流各要素明细表）

严格按照需求文档 5.1 的要素编号、名称、字段类型定义，
并根据 5.3 标注核心要素（默认资金流 F-01/F-02/F-04/F-06/F-08 为核心要素）。
"""

# 每项结构：(flow_type, element_code, element_name, field_type, description, is_core, sort_order)
FLOW_ELEMENT_DEFINITIONS: list[tuple] = [
    # ---------- 5.1.1 人员流（Person Flow）----------
    ("person", "P-01", "受害人身份", "idcard_or_name", "受害人姓名、身份证件等身份信息", False, 1),
    ("person", "P-02", "嫌疑人自称身份", "text", "嫌疑人冒充的身份（如客服、公检法人员）", False, 2),
    ("person", "P-03", "代办人", "text", "代为操作的人员信息", False, 3),
    ("person", "P-04", "团伙角色", "text", "诈骗团伙内部分工角色", False, 4),

    # ---------- 5.1.2 通信流（Communication Flow）----------
    ("communication", "C-01", "涉案主叫电话", "phone", "拨打给受害人的号码", False, 1),
    ("communication", "C-02", "涉案被叫电话", "phone", "受害人回拨/被叫号码", False, 2),
    ("communication", "C-03", "通话时长", "duration", "单次/累计通话时长", False, 3),
    ("communication", "C-04", "通话时段", "time", "通话发生的时间段", False, 4),
    ("communication", "C-05", "涉案短信", "text", "涉案短信内容", False, 5),

    # ---------- 5.1.3 网络流（Network Flow）----------
    ("network", "N-01", "引流二维码", "image", "引流使用的二维码", False, 1),
    ("network", "N-02", "涉案网址/域名", "url", "涉案网站网址或域名", False, 2),
    ("network", "N-03", "涉案 APP", "text", "涉案应用名称（如国盛智投）", False, 3),
    ("network", "N-04", "聊天工具账号", "text", "涉案聊天工具及账号", False, 4),
    ("network", "N-05", "屏幕共享记录", "text", "远程屏幕共享情况", False, 5),
    ("network", "N-06", "登录 IP 与设备标识", "ip", "涉案登录 IP、设备号", False, 6),

    # ---------- 5.1.4 资金流（Fund Flow）：核心要素（5.3）----------
    ("fund", "F-01", "转账时间", "time", "每笔转账的时间", True, 1),
    ("fund", "F-02", "转账金额", "amount", "每笔转账金额", True, 2),
    ("fund", "F-03", "支付通道", "text", "银行/第三方支付/虚拟币等", False, 3),
    ("fund", "F-04", "转出卡号", "card", "受害人转出银行卡号", True, 4),
    ("fund", "F-05", "对方开户行", "text", "收款方开户银行", False, 5),
    ("fund", "F-06", "对方卡号", "card", "收款方银行卡号", True, 6),
    ("fund", "F-07", "流水号", "text", "转账交易流水号", False, 7),
    ("fund", "F-08", "损失总额", "amount", "累计损失金额", True, 8),

    # ---------- 5.1.5 寄递流（Delivery Flow）----------
    ("delivery", "D-01", "快递单号", "express", "涉案快递单号", False, 1),
    ("delivery", "D-02", "寄件人", "text", "寄件人信息", False, 2),
    ("delivery", "D-03", "收件人", "text", "收件人信息", False, 3),
    ("delivery", "D-04", "收发地址", "text", "寄件/收件地址", False, 4),
    ("delivery", "D-05", "涉案包裹", "text", "包裹内容描述", False, 5),
]
