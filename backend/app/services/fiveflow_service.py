"""
五流要素分析引擎（BE-6）

实现需求文档：
- FR-3.4.3 五流覆盖度实时计算与缺口定位；
- 5.2 要素抽取规则（ER-1~ER-5：异步抽取、实体识别 NER、增量更新、抽取降级、证据摘要）；
- 5.3 覆盖度计算与状态判定规则（四状态：已收集/需补充/重点缺口/不涉及）；
- FR-3.5.3 历史笔录解析导入的要素抽取。

要素抽取采用"正则实体识别 + 关键词关系映射"的工程化实现：
针对五流各要素（5.1）定义识别规则（手机号、卡号、金额、URL、时间、快递单号等），
从问答文本中抽取候选值并映射到对应要素编号。该实现可替换为真实 NER 模型（扩展点）。
"""

import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import (
    FLOW_TYPE_LABEL,
    ElementStatus,
    FlowType,
)
from app.models.fiveflow import FiveFlowElement, FlowElementDefinition
from app.models.record import QAItem, RecordSession
from app.schemas.fiveflow import (
    FiveFlowAnalysisResult,
    FiveFlowElementOut,
    FlowCoverage,
)


# ============================================================
# 要素识别正则规则（对应 5.1 各要素字段类型）
# ============================================================
# 手机号：11 位，1 开头
_RE_PHONE = re.compile(r"1[3-9]\d{9}")
# 银行卡号：16~19 位数字
_RE_CARD = re.compile(r"\b\d{16,19}\b")
# 金额：数字 + 元/万/块/万元，或带千分位
_RE_AMOUNT = re.compile(r"(\d[\d,]*\.?\d*)\s*(万元|万|元|块钱|块)")
# URL/域名
_RE_URL = re.compile(r"(https?://[^\s，。]+|www\.[^\s，。]+|[a-zA-Z0-9\-]+\.(?:com|cn|net|org|top|xyz|vip)(?:/[^\s，。]*)?)")
# IP 地址
_RE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# 快递单号：常见为 10~15 位数字或字母数字组合（含 SF/YT/ZTO 等前缀）
_RE_EXPRESS = re.compile(r"\b(?:SF|YT|ZTO|JD|EMS)?\d{10,15}\b", re.IGNORECASE)
# 时间：日期时间常见表达
_RE_TIME = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?(?:\s*\d{1,2}[:时]\d{1,2}(?:[:分]\d{1,2})?)?")
# 时长：X 分钟/小时
_RE_DURATION = re.compile(r"\d+\s*(分钟|小时|个小时|秒)")
# 身份证号
_RE_IDCARD = re.compile(r"\b\d{17}[\dXx]\b|\b\d{15}\b")

# 关键词 → 要素编号映射（用于关系抽取，命中关键词的问答倾向于采集对应要素）
_KEYWORD_ELEMENT_MAP: dict[str, list[str]] = {
    "客服": ["P-02"], "冒充": ["P-02"], "公检法": ["P-02"], "警察": ["P-02"], "代办": ["P-03"],
    "电话": ["C-01", "C-02"], "来电": ["C-01"], "主叫": ["C-01"], "被叫": ["C-02"], "短信": ["C-05"],
    "通话": ["C-03", "C-04"],
    "二维码": ["N-01"], "网址": ["N-02"], "域名": ["N-02"], "网站": ["N-02"], "链接": ["N-02"],
    "app": ["N-03"], "软件": ["N-03"], "微信": ["N-04"], "qq": ["N-04"], "聊天": ["N-04"],
    "屏幕共享": ["N-05"], "远程控制": ["N-05"], "共享屏幕": ["N-05"],
    "ip": ["N-06"], "设备": ["N-06"],
    "转账": ["F-01", "F-02", "F-04", "F-06"], "汇款": ["F-01", "F-02"], "银行": ["F-03", "F-05"],
    "支付宝": ["F-03"], "虚拟币": ["F-03"], "USDT": ["F-03"], "卡号": ["F-04", "F-06"],
    "开户行": ["F-05"], "流水号": ["F-07"], "损失": ["F-08"], "亏损": ["F-08"], "被骗": ["F-08"],
    "快递": ["D-01", "D-05"], "单号": ["D-01"], "寄件": ["D-02", "D-04"], "收件": ["D-03", "D-04"],
    "包裹": ["D-05"], "地址": ["D-04"],
    "身份证": ["P-01"], "姓名": ["P-01"], "受害人": ["P-01"], "团伙": ["P-04"], "角色": ["P-04"],
}

# 要素编号 → 字段类型（用于选择对应的正则抽取器）
_ELEMENT_EXTRACTOR: dict[str, str] = {
    "P-01": "idcard_or_name", "C-01": "phone", "C-02": "phone", "C-03": "duration",
    "C-04": "time", "N-02": "url", "N-06": "ip",
    "F-01": "time", "F-02": "amount", "F-04": "card", "F-06": "card", "F-08": "amount",
    "D-01": "express",
}


class FiveFlowService:
    """五流要素分析引擎。"""

    def __init__(self, db: Session):
        self.db = db
        # 缓存要素定义目录（5.1），按 element_code 索引
        self._definitions: dict[str, FlowElementDefinition] = {}
        self._load_definitions()

    def _load_definitions(self) -> None:
        """加载五流要素定义目录（FlowElementDefinition）。"""
        defs = self.db.execute(select(FlowElementDefinition)).scalars().all()
        self._definitions = {d.element_code: d for d in defs}

    @property
    def definitions(self) -> dict[str, FlowElementDefinition]:
        """返回要素定义目录（element_code → 定义）。"""
        return self._definitions

    def list_definitions(self, flow_type: FlowType | None = None) -> list[FlowElementDefinition]:
        """列出要素定义（可按流类型过滤），供前端展示 5.1 明细表。"""
        stmt = select(FlowElementDefinition)
        if flow_type:
            stmt = stmt.where(FlowElementDefinition.flow_type == flow_type.value)
        stmt = stmt.order_by(FlowElementDefinition.sort_order)
        return list(self.db.execute(stmt).scalars().all())

    # ============================================================
    # 一、要素抽取（ER-1~ER-5）
    # ============================================================
    def extract_from_qa(self, session_id: str, qa_items: Iterable[QAItem]) -> None:
        """从问答项抽取五流要素并持久化（ER-1 异步抽取、ER-3 增量更新）。

        对每条已作答问答执行实体识别与关系抽取，将结果映射到 5.1 各要素字段，
        写入/更新 FiveFlowElement（按 session_id + element_code 唯一）。
        抽取失败或低置信度不自动填充，标记待手动确认（ER-4）。

        :param session_id: 会话ID
        :param qa_items: 需抽取的问答项（增量抽取时仅传变更项）
        """
        for qa in qa_items:
            if not qa.is_answered:
                continue
            text = f"{qa.question} {qa.answer}"
            self._extract_single_qa(session_id, qa, text)
        self.db.commit()

    def _extract_single_qa(self, session_id: str, qa: QAItem, text: str) -> None:
        """对单条问答执行抽取。"""
        lower_text = text.lower()
        # 通过关键词映射确定该问答可能涉及的要素编号
        candidate_codes: set[str] = set()
        for keyword, codes in _KEYWORD_ELEMENT_MAP.items():
            if keyword in lower_text:
                candidate_codes.update(codes)

        # 对每个候选要素，用对应正则抽取具体值
        for code in candidate_codes:
            definition = self._definitions.get(code)
            if definition is None:
                continue
            value, snippet = self._extract_value(code, definition.field_type, text)
            if value:
                self._upsert_element(
                    session_id=session_id,
                    definition=definition,
                    value=value,
                    evidence_snippet=snippet,
                    source_qa_id=qa.id,
                    confidence=0.9,
                    need_manual_confirm=False,
                )

    def _extract_value(self, code: str, field_type: str, text: str) -> tuple[str | None, str | None]:
        """根据要素字段类型从文本抽取值。

        :return: (抽取值, 证据摘要片段)；未抽取到返回 (None, None)
        """
        extractor_key = _ELEMENT_EXTRACTOR.get(code, field_type)

        if extractor_key == "phone":
            m = _RE_PHONE.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        if extractor_key == "card":
            m = _RE_CARD.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        if extractor_key == "amount":
            m = _RE_AMOUNT.search(text)
            if m:
                return (m.group(), self._snippet(text, m.start(), m.end()))
            return (None, None)
        if extractor_key == "url":
            m = _RE_URL.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        if extractor_key == "ip":
            m = _RE_IP.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        if extractor_key == "time":
            m = _RE_TIME.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        if extractor_key == "duration":
            m = _RE_DURATION.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        if extractor_key == "express":
            m = _RE_EXPRESS.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        if extractor_key == "idcard_or_name":
            m = _RE_IDCARD.search(text)
            return (m.group(), self._snippet(text, m.start(), m.end())) if m else (None, None)
        return (None, None)

    @staticmethod
    def _snippet(text: str, start: int, end: int, window: int = 15) -> str:
        """截取命中值附近的证据摘要片段（ER-5）。"""
        left = max(0, start - window)
        right = min(len(text), end + window)
        prefix = "…" if left > 0 else ""
        suffix = "…" if right < len(text) else ""
        return f"{prefix}{text[left:right]}{suffix}"

    def _upsert_element(
        self,
        *,
        session_id: str,
        definition: FlowElementDefinition,
        value: str | None,
        evidence_snippet: str | None,
        source_qa_id: str | None,
        confidence: float,
        need_manual_confirm: bool,
    ) -> FiveFlowElement:
        """插入或更新会话级五流要素（按 session_id + element_code 唯一）。"""
        element = self.db.execute(
            select(FiveFlowElement).where(
                FiveFlowElement.session_id == session_id,
                FiveFlowElement.element_code == definition.element_code,
            )
        ).scalar_one_or_none()

        if element is None:
            element = FiveFlowElement(
                session_id=session_id,
                flow_type=definition.flow_type,
                element_code=definition.element_code,
            )
            self.db.add(element)

        # 仅在抽取到新值时更新（避免覆盖已有值）
        if value and not element.value:
            element.value = value
            element.evidence_snippet = evidence_snippet
            element.source_qa_id = source_qa_id
        elif value and element.value:
            # 已有值则追加证据摘要（多笔转账等场景）
            if evidence_snippet and evidence_snippet not in (element.evidence_snippet or ""):
                element.evidence_snippet = f"{element.evidence_snippet or ''} | {evidence_snippet}"
        element.confidence = confidence
        element.need_manual_confirm = need_manual_confirm
        return element

    # ============================================================
    # 二、覆盖度计算与状态判定（5.3 / FR-3.4.3）
    # ============================================================
    def compute_coverage(
        self,
        session: RecordSession,
        involved_flows: set[FlowType] | None = None,
    ) -> FiveFlowAnalysisResult:
        """计算五流覆盖度与状态（5.3 覆盖度公式与四状态判定）。

        Cov(Flow) = N_collected / N_required × 100%
        四状态：已收集(100%) / 需补充(0<Cov<100%) / 重点缺口(核心要素缺失) / 不涉及(N_required=0)

        :param session: 笔录会话
        :param involved_flows: 涉及的流集合（None 表示全部流均涉及）
        :return: 五流分析结果
        """
        # 加载会话已抽取的要素
        elements = self.db.execute(
            select(FiveFlowElement).where(FiveFlowElement.session_id == session.id)
        ).scalars().all()
        element_map: dict[str, FiveFlowElement] = {e.element_code: e for e in elements}

        # 核心要素清单（5.3，可配）
        core_codes = set(settings.FIVEFLOW_CORE_ELEMENTS)

        flows: list[FlowCoverage] = []
        has_key_gap = False
        total_required = 0
        total_collected = 0

        for flow in FlowType:
            flow_defs = [d for d in self._definitions.values() if d.flow_type == flow.value]
            flow_defs.sort(key=lambda d: d.sort_order)

            # 判断该流是否涉及（N_required=0 → 不涉及）
            is_involved = involved_flows is None or flow in involved_flows
            if not is_involved or not flow_defs:
                flows.append(FlowCoverage(
                    flow_type=flow,
                    flow_label=FLOW_TYPE_LABEL[flow],
                    coverage=0.0,
                    status=ElementStatus.NOT_INVOLVED,
                    collected_count=0,
                    required_count=0,
                    elements=[],
                    evidence_summary=[],
                    key_gaps=[],
                ))
                continue

            required_count = len(flow_defs)
            collected_count = 0
            element_outs: list[FiveFlowElementOut] = []
            evidence_summary: list[str] = []
            key_gaps: list[str] = []
            flow_has_key_gap = False

            for d in flow_defs:
                el = element_map.get(d.element_code)
                is_core = d.element_code in core_codes or d.is_core
                collected = bool(el and el.is_collected)
                if collected:
                    collected_count += 1
                    # 证据摘要（ER-5）
                    if el.evidence_snippet:
                        evidence_summary.append(f"{d.element_name}：{el.evidence_snippet}")
                    elif el.value:
                        evidence_summary.append(f"{d.element_name}：{el.value}")
                    status = ElementStatus.COLLECTED
                else:
                    # 未采集：核心要素缺失→重点缺口，否则需补充
                    if is_core:
                        status = ElementStatus.KEY_GAP
                        flow_has_key_gap = True
                        key_gaps.append(d.element_name)
                    else:
                        status = ElementStatus.NEED_SUPPLEMENT

                element_outs.append(FiveFlowElementOut(
                    id=el.id if el else f"def_{d.element_code}",
                    session_id=session.id,
                    flow_type=flow,
                    element_code=d.element_code,
                    element_name=d.element_name,
                    value=el.value if el else None,
                    status=status,
                    evidence_snippet=el.evidence_snippet if el else None,
                    is_core=is_core,
                    need_manual_confirm=el.need_manual_confirm if el else False,
                ))

            # 覆盖度 = N_collected / N_required × 100%
            coverage = round(collected_count / required_count * 100, 1) if required_count > 0 else 0.0
            # 流级状态判定（5.3 四状态）
            if flow_has_key_gap:
                flow_status = ElementStatus.KEY_GAP
                has_key_gap = True
            elif coverage >= 100:
                flow_status = ElementStatus.COLLECTED
            elif coverage > 0:
                flow_status = ElementStatus.NEED_SUPPLEMENT
            else:
                flow_status = ElementStatus.NEED_SUPPLEMENT

            total_required += required_count
            total_collected += collected_count

            flows.append(FlowCoverage(
                flow_type=flow,
                flow_label=FLOW_TYPE_LABEL[flow],
                coverage=coverage,
                status=flow_status,
                collected_count=collected_count,
                required_count=required_count,
                elements=element_outs,
                evidence_summary=evidence_summary,
                key_gaps=key_gaps,
            ))

        overall = round(total_collected / total_required * 100, 1) if total_required > 0 else 0.0
        return FiveFlowAnalysisResult(
            session_id=session.id,
            flows=flows,
            overall_coverage=overall,
            has_key_gap=has_key_gap,
        )

    def collect_key_gap_elements(self, analysis: FiveFlowAnalysisResult) -> list[dict]:
        """从分析结果中提取重点缺口要素清单（供 AI 生成追问，GR-1）。

        :return: [{"code","name","flow_label"}]
        """
        gaps: list[dict] = []
        for flow in analysis.flows:
            if flow.status != ElementStatus.KEY_GAP:
                continue
            for el in flow.elements:
                if el.status == ElementStatus.KEY_GAP:
                    gaps.append({
                        "code": el.element_code,
                        "name": el.element_name or el.element_code,
                        "flow_label": flow.flow_label,
                    })
        return gaps

    def sync_element_status(self, session_id: str) -> None:
        """同步持久化要素的状态字段（依据是否采集更新 status）。

        在覆盖度计算后可调用，将计算出的要素状态回写数据库，保证 DE-6 status 字段准确。
        """
        elements = self.db.execute(
            select(FiveFlowElement).where(FiveFlowElement.session_id == session_id)
        ).scalars().all()
        core_codes = set(settings.FIVEFLOW_CORE_ELEMENTS)
        for el in elements:
            if el.is_collected:
                el.status = ElementStatus.COLLECTED.value
            elif el.element_code in core_codes:
                el.status = ElementStatus.KEY_GAP.value
            else:
                el.status = ElementStatus.NEED_SUPPLEMENT.value
        self.db.commit()
