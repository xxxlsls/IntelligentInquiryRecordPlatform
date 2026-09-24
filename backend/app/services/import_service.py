"""
历史笔录解析导入服务（BE-6 扩展）

实现需求文档 FR-3.5.3 历史文本/文档笔录解析导入与会话重建：
处理逻辑：
1) 解析文档提取问答对（支持粘贴文本 / Word 文档）；
2) 大纲结构还原与章节归类；
3) 五流要素抽取生成证据图谱；
4) 识别缺失流 → 转化为继续问询草稿；
5) 重建新会话。

异常与边界：解析失败提示手工校对；非标准格式降级为纯文本导入；历史笔录不覆盖现有会话。
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    CHAPTER_LABEL,
    Chapter,
    ElementStatus,
    FlowType,
    QASource,
)
from app.core.exceptions import ValidationError
from app.models.record import QAItem, RecordSession
from app.schemas.fiveflow import ParseResult, ParsedQA
from app.services.fiveflow_service import FiveFlowService

# 问答对识别正则：匹配"问：...答：..."结构（兼容全角/半角冒号）
_RE_QUESTION = re.compile(r"^\s*问\s*[:：]\s*(.+)$")
_RE_ANSWER = re.compile(r"^\s*答\s*[:：]\s*(.+)$")

# 章节关键词映射（用于大纲结构还原与章节归类）
_CHAPTER_KEYWORDS: dict[Chapter, list[str]] = {
    Chapter.FIXED_OPENING: ["姓名", "出生", "身份证", "住址", "工作单位", "是否", "权利", "义务", "如实"],
    Chapter.CONTACT_LURE: ["如何认识", "联系", "电话", "微信", "qq", "二维码", "网址", "下载", "app", "引流", "添加"],
    Chapter.FRAUD_PROCESS: ["经过", "过程", "怎么", "如何被骗", "对方", "自称", "诱导", "操作", "屏幕共享"],
    Chapter.FUND_LOSS: ["转账", "汇款", "金额", "多少钱", "损失", "卡号", "银行", "支付", "流水"],
    Chapter.EVIDENCE_SUPPLEMENT: ["凭证", "截图", "记录", "证据", "补充", "快递", "包裹", "其他"],
}


class ImportService:
    """历史笔录解析导入服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.fiveflow_service = FiveFlowService(db)

    # ============================================================
    # 一、文本解析（FR-3.5.3 处理逻辑步骤 1~2）
    # ============================================================
    def parse_text(self, text: str) -> ParseResult:
        """解析笔录文本，提取问答对并归类章节。

        解析策略：
        - 按行扫描，识别"问："与"答："标记，配对为问答项；
        - 多行答案自动拼接；
        - 根据问题关键词归类大纲章节；
        - 非标准格式（无问答标记）降级为纯文本导入（异常与边界）。

        :param text: 笔录文本内容
        :return: 解析结果（问答对 + 五流分析 + 缺口草稿）
        """
        if not text or not text.strip():
            raise ValidationError("笔录文本内容为空")

        qa_pairs = self._extract_qa_pairs(text)

        # 非标准格式降级：未识别到问答对时，按段落作为问题导入（降级为纯文本）
        parse_success = True
        parse_message = ""
        if not qa_pairs:
            parse_success = False
            parse_message = "未识别到标准问答格式，已降级为纯文本导入，请手工校对"
            qa_pairs = self._fallback_plain_text(text)

        # 章节归类
        parsed_qa = [
            ParsedQA(
                chapter=self._classify_chapter(q).value,
                question=q,
                answer=a,
            )
            for q, a in qa_pairs
        ]

        return ParseResult(
            parsed_qa=parsed_qa,
            qa_count=len(parsed_qa),
            parse_success=parse_success,
            parse_message=parse_message or f"成功解析 {len(parsed_qa)} 组问答",
        )

    def parse_docx(self, content: bytes) -> ParseResult:
        """解析 Word 文档笔录（FR-3.5.3：上传已有笔录文件）。

        使用 python-docx 提取段落文本后复用文本解析逻辑。
        解析失败时提示手工校对（异常与边界）。
        """
        try:
            import io

            from docx import Document

            doc = Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return self.parse_text(text)
        except Exception as exc:  # noqa: BLE001
            # 解析失败提示手工校对（FR-3.5.3 异常与边界）
            raise ValidationError(f"Word 文档解析失败，请检查格式或手工校对：{exc}") from exc

    def _extract_qa_pairs(self, text: str) -> list[tuple[str, str | None]]:
        """从文本提取问答对列表 [(question, answer), ...]。"""
        pairs: list[tuple[str, str | None]] = []
        lines = text.splitlines()

        current_q: str | None = None
        current_a_lines: list[str] = []

        def flush() -> None:
            """将当前累积的问答对写入结果。"""
            nonlocal current_q, current_a_lines
            if current_q is not None:
                answer = "\n".join(current_a_lines).strip() if current_a_lines else None
                pairs.append((current_q.strip(), answer or None))
            current_q = None
            current_a_lines = []

        for line in lines:
            q_match = _RE_QUESTION.match(line)
            a_match = _RE_ANSWER.match(line)
            if q_match:
                # 遇到新问题，先保存上一对
                flush()
                current_q = q_match.group(1)
            elif a_match and current_q is not None:
                current_a_lines.append(a_match.group(1))
            elif current_q is not None and line.strip():
                # 答案续行（多行答案拼接）
                if current_a_lines:
                    current_a_lines.append(line.strip())

        flush()
        return pairs

    def _fallback_plain_text(self, text: str) -> list[tuple[str, str | None]]:
        """降级处理：将非标准文本按段落转为问题项（无答案，待手工校对）。"""
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        return [(p, None) for p in paragraphs[:100]]

    def _classify_chapter(self, question: str) -> Chapter:
        """根据问题关键词归类大纲章节（FR-3.5.3 大纲结构还原）。"""
        q_lower = question.lower()
        best_chapter = Chapter.EVIDENCE_SUPPLEMENT
        best_hits = 0
        for chapter, keywords in _CHAPTER_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw.lower() in q_lower)
            if hits > best_hits:
                best_hits = hits
                best_chapter = chapter
        return best_chapter

    # ============================================================
    # 二、五流分析与缺口识别（FR-3.5.3 处理逻辑步骤 3~4）
    # ============================================================
    def analyze_parsed_qa(self, parsed_qa: list[ParsedQA]) -> dict:
        """对解析出的问答执行五流要素抽取，生成证据图谱并识别缺失流。

        由于解析结果尚未持久化为会话，此处使用临时抽取逻辑：
        构造伪 QAItem 对象供五流引擎抽取，计算覆盖度并识别缺口。

        :return: {five_flow_analysis, missing_flows, followup_draft}
        """
        # 拼接全部问答文本，直接用正则抽取要素到内存（不落库）
        combined_text = " ".join(
            f"{q.question} {q.answer or ''}" for q in parsed_qa
        )
        # 统计各流要素命中情况
        flow_status = self._quick_flow_scan(combined_text)

        missing_flows: list[str] = []
        followup_draft: list[str] = []
        for flow, hit_count in flow_status.items():
            if hit_count == 0:
                missing_flows.append(flow)
                followup_draft.append(self._build_followup_question(flow))

        return {
            "missing_flows": missing_flows,
            "followup_draft": followup_draft,
            "flow_status": flow_status,
        }

    def _quick_flow_scan(self, text: str) -> dict[str, int]:
        """快速扫描五流命中数（用于历史笔录缺口识别，不落库）。"""
        lower = text.lower()
        scan_rules: dict[str, list[str]] = {
            "人员流": ["姓名", "身份证", "自称", "客服", "受害人", "代办"],
            "通信流": ["电话", "来电", "手机号", "通话", "短信"],
            "网络流": ["微信", "qq", "网址", "二维码", "app", "下载", "链接", "屏幕共享"],
            "资金流": ["转账", "汇款", "金额", "卡号", "银行", "损失", "支付", "流水"],
            "寄递流": ["快递", "单号", "包裹", "寄件", "收件"],
        }
        return {
            flow: sum(1 for kw in kws if kw.lower() in lower)
            for flow, kws in scan_rules.items()
        }

    @staticmethod
    def _build_followup_question(flow_label: str) -> str:
        """为缺失流构建继续问询草稿问题（FR-3.5.3：转化为继续问询草稿）。"""
        templates = {
            "通信流": "请补充说明涉案通话的主叫/被叫号码、通话时间与时长，以及是否收到涉案短信。",
            "网络流": "请补充说明对方通过何种网络渠道联系（微信/QQ/网址/二维码/APP），是否进行过屏幕共享。",
            "资金流": "请明确每笔转账的时间、金额、转出银行卡号及对方收款卡号和户名。",
            "寄递流": "请补充说明是否有涉案快递往来，包括快递单号、寄收件人及收发地址。",
            "人员流": "请补充说明受害人身份信息及嫌疑人自称身份、代办人等情况。",
        }
        return templates.get(flow_label, f"请补充说明{flow_label}相关情况。")

    # ============================================================
    # 三、会话重建（FR-3.5.3 处理逻辑步骤 5）
    # ============================================================
    def rebuild_session(
        self,
        session: RecordSession,
        parsed_qa: list[ParsedQA],
        followup_draft: list[str],
    ) -> RecordSession:
        """将解析结果转存为新问询会话（FR-3.5.3：历史笔录不覆盖现有会话）。

        :param session: 新创建的空白会话（由接口层先创建）
        :param parsed_qa: 解析出的问答对
        :param followup_draft: 缺口追问草稿问题（作为待作答问题追加）
        """
        sort_counter = 0
        # 写入解析出的历史问答（来源标记为手动新增，代表导入）
        for pq in parsed_qa:
            chapter = pq.chapter or Chapter.EVIDENCE_SUPPLEMENT.value
            self.db.add(QAItem(
                session_id=session.id,
                chapter=chapter,
                question=pq.question,
                answer=pq.answer,
                source=QASource.MANUAL.value,
                sort_order=sort_counter,
            ))
            sort_counter += 1

        # 缺口追问草稿作为未作答问题追加（支持二次补充问询）
        for draft_q in followup_draft:
            self.db.add(QAItem(
                session_id=session.id,
                chapter=Chapter.EVIDENCE_SUPPLEMENT.value,
                question=draft_q,
                answer=None,
                source=QASource.AI_RECOMMEND.value,
                sort_order=sort_counter,
            ))
            sort_counter += 1

        self.db.commit()
        self.db.refresh(session)

        # 对导入的已作答问答执行五流抽取（生成证据图谱）
        answered_items = self.db.execute(
            select(QAItem).where(QAItem.session_id == session.id)
        ).scalars().all()
        self.fiveflow_service.extract_from_qa(session.id, [q for q in answered_items if q.is_answered])

        return session
