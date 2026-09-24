"""
AI 研判推荐服务（BE-5）

实现需求文档：
- FR-3.3.2 基于案情文本的 AI 智能推荐匹配（匹配度加权算法）；
- FR-3.4.2 AI 特征提取与侦查研判建议；
- 5.4 重点缺口追问建议生成规则；
- 8.3 AI 侦查研判指引报告格式。

【匹配度加权算法】（FR-3.3.2）
    S(D,T) = α·F_sig(D,T) + β·F_cat(D,T) + γ·F_sem(D,T)
    - F_sig 信号词命中因子 = Σ(w_i·hit_i)/Σw_i
    - F_cat 案由类别因子：一致 1.0 / 同类近似 0.6 / 不一致 0
    - F_sem 语义相似因子：案情文本与模板描述的语义相似度（0~1）
    默认 α=0.4, β=0.2, γ=0.4；S≥阈值(0.6) 标记为高置信度推荐。

说明：语义相似因子在无外部大模型部署（12.3 Q-7 待确认）时，采用基于字符 n-gram
的轻量相似度算法作为可运行的工程化实现，接口层预留了替换为真实分类模型的扩展点。
"""

import re
from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import (
    Chapter,
    ElementStatus,
    FlowType,
    SuggestionType,
)
from app.models.record import AiSuggestion, QAItem, RecordSession
from app.models.template import Template
from app.schemas.ai import (
    AnalysisResult,
    CaseTypeJudgement,
    FactFeature,
    InvestigationGuide,
    SuggestionOut,
)
from app.schemas.template import TemplateRecommendItem, TemplateRecommendResult, TemplateOut


class AiService:
    """AI 研判推荐服务：模板推荐匹配 + 侦查研判建议生成。"""

    def __init__(self, db: Session):
        self.db = db

    # ============================================================
    # 一、模板智能推荐（FR-3.3.2）
    # ============================================================
    def recommend_templates(
        self,
        brief: str,
        case_category: str | None = None,
        top_n: int | None = None,
        enabled_templates: list[Template] | None = None,
    ) -> TemplateRecommendResult:
        """基于案情文本推荐模板（FR-3.3.2 处理逻辑）。

        :param brief: 简要案情文本
        :param case_category: 录入的案件类别（用于 F_cat）
        :param top_n: 推荐数量（默认取配置 AI_RECOMMEND_TOP_N）
        :param enabled_templates: 已加载的启用模板列表（避免重复查询）
        :return: 推荐结果（含降级标识）
        """
        n = top_n or settings.AI_RECOMMEND_TOP_N

        # 异常与边界：案情文本过短（<10 字）提示补充
        cleaned_brief = (brief or "").strip()
        if len(cleaned_brief) < 10:
            return TemplateRecommendResult(
                recommendations=[],
                is_degraded=True,
                degrade_reason="案情文本过短（少于 10 字），请补充案情后重试或直接检索全量模板库",
                total_templates=len(enabled_templates or []),
            )

        templates = enabled_templates if enabled_templates is not None else self._load_enabled_templates()
        if not templates:
            return TemplateRecommendResult(
                recommendations=[], is_degraded=True, degrade_reason="模板库为空", total_templates=0
            )

        # 逐一计算匹配度评分 S(D,T)
        scored: list[TemplateRecommendItem] = []
        for tpl in templates:
            item = self._score_template(cleaned_brief, case_category, tpl)
            scored.append(item)

        # 按 S(D,T) 降序排列，取 TOP N
        scored.sort(key=lambda x: x.match_score, reverse=True)
        top_items = scored[:n]

        # 判断是否存在高置信匹配；无高置信匹配时降级展示全量库（FR-3.3.2 异常与边界）
        has_high_confidence = any(it.is_high_confidence for it in top_items)
        return TemplateRecommendResult(
            recommendations=top_items,
            is_degraded=not has_high_confidence,
            degrade_reason=None if has_high_confidence else "无高置信度匹配，已降级展示，可从全量模板库检索选择",
            total_templates=len(templates),
        )

    def _load_enabled_templates(self) -> list[Template]:
        """加载全部启用模板（含信号词），停用模板不参与推荐。"""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        return list(
            self.db.execute(
                select(Template)
                .options(selectinload(Template.signal_words))
                .where(Template.is_enabled.is_(True))
            ).scalars().all()
        )

    def _score_template(self, brief: str, case_category: str | None, tpl: Template) -> TemplateRecommendItem:
        """计算单个模板对案情文本的匹配度评分（FR-3.3.2 加权算法）。"""
        # --- F_sig 信号词命中因子 = Σ(w_i·hit_i)/Σw_i ---
        f_sig, hit_words = self._compute_signal_factor(brief, tpl)
        # --- F_cat 案由类别因子 ---
        f_cat = self._compute_category_factor(case_category, tpl)
        # --- F_sem 语义相似因子 ---
        f_sem = self._compute_semantic_factor(brief, tpl)

        alpha = settings.AI_WEIGHT_SIGNAL
        beta = settings.AI_WEIGHT_CATEGORY
        gamma = settings.AI_WEIGHT_SEMANTIC

        # 综合评分 S(D,T)
        score = alpha * f_sig + beta * f_cat + gamma * f_sem
        score = round(max(0.0, min(1.0, score)), 4)
        is_high = score >= settings.AI_CONFIDENCE_THRESHOLD

        # 生成推荐理由（人类可读）
        reason = self._build_reason(tpl, hit_words, f_sig, f_cat, f_sem, is_high)

        return TemplateRecommendItem(
            template=TemplateOut.model_validate(tpl),
            match_score=score,
            match_percent=int(round(score * 100)),
            is_high_confidence=is_high,
            hit_signal_words=hit_words,
            signal_factor=round(f_sig, 4),
            category_factor=round(f_cat, 4),
            semantic_factor=round(f_sem, 4),
            reason=reason,
        )

    @staticmethod
    def _compute_signal_factor(brief: str, tpl: Template) -> tuple[float, list[str]]:
        """计算 F_sig 信号词命中因子。

        F_sig = Σ(w_i·hit_i)/Σw_i，hit_i∈{0,1} 表示案情文本是否命中第 i 个信号词。
        :return: (信号词因子, 命中的信号词列表)
        """
        signal_words = tpl.signal_words or []
        if not signal_words:
            return 0.0, []

        total_weight = sum(w.weight for w in signal_words)
        if total_weight <= 0:
            return 0.0, []

        hit_weight = 0.0
        hit_words: list[str] = []
        for w in signal_words:
            # 命中判定：信号词作为子串出现在案情文本中（中文分词简化处理）
            if w.word and w.word in brief:
                hit_weight += w.weight
                hit_words.append(w.word)

        return (hit_weight / total_weight), hit_words

    @staticmethod
    def _compute_category_factor(case_category: str | None, tpl: Template) -> float:
        """计算 F_cat 案由类别因子（FR-3.3.2）。

        一致取 1.0；同类近似取配置值（默认 0.6）；不一致取 0。
        近似判定：类别字符串互为子串或存在共同关键词。
        """
        if not case_category:
            return 0.0
        cat = case_category.strip()
        tpl_cat = (tpl.category or "").strip()
        # 完全一致
        if cat == tpl_cat:
            return 1.0
        # 同类近似：互为子串（如"虚假投资理财" vs "投资理财"）
        if cat and tpl_cat and (cat in tpl_cat or tpl_cat in cat):
            return settings.AI_CATEGORY_SIMILAR_SCORE
        return 0.0

    @staticmethod
    def _compute_semantic_factor(brief: str, tpl: Template) -> float:
        """计算 F_sem 语义相似因子（0~1）。

        工程化实现：将案情文本与"模板描述 + 案由 + 信号词"构成的模板语义指纹，
        基于字符 bigram 的余弦相似度度量文本相似程度。
        该实现可替换为真实分类/向量模型的输出（扩展点，12.3 Q-7）。
        """
        # 构建模板侧语义文本
        tpl_text_parts = [tpl.category or "", tpl.description or ""]
        tpl_text_parts.extend([w.word for w in (tpl.signal_words or []) if w.word])
        tpl_text = " ".join(p for p in tpl_text_parts if p)
        if not tpl_text or not brief:
            return 0.0

        brief_grams = AiService._char_bigrams(brief)
        tpl_grams = AiService._char_bigrams(tpl_text)
        if not brief_grams or not tpl_grams:
            return 0.0

        # 余弦相似度
        common = set(brief_grams) & set(tpl_grams)
        if not common:
            return 0.0
        dot = sum(brief_grams[g] * tpl_grams[g] for g in common)
        norm_a = sum(v * v for v in brief_grams.values()) ** 0.5
        norm_b = sum(v * v for v in tpl_grams.values()) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _char_bigrams(text: str) -> Counter:
        """提取文本的字符 bigram 词频（去除空白与标点），用于轻量语义相似度。"""
        # 仅保留中文、字母、数字
        cleaned = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", text)
        if len(cleaned) < 2:
            return Counter({cleaned: 1}) if cleaned else Counter()
        grams = [cleaned[i:i + 2] for i in range(len(cleaned) - 1)]
        return Counter(grams)

    @staticmethod
    def _build_reason(tpl: Template, hit_words: list[str], f_sig: float,
                      f_cat: float, f_sem: float, is_high: bool) -> str:
        """生成推荐理由文本（6.3 展开查看推荐理由）。"""
        parts = []
        if hit_words:
            parts.append(f"命中特征信号词：{'、'.join(hit_words[:5])}")
        if f_cat >= 1.0:
            parts.append(f"案由类别与「{tpl.category}」完全一致")
        elif f_cat > 0:
            parts.append(f"案由类别与「{tpl.category}」近似")
        if f_sem > 0:
            parts.append(f"案情语义相似度 {int(round(f_sem * 100))}%")
        prefix = "高置信度推荐" if is_high else "参考推荐"
        reason_body = "；".join(parts) if parts else "基于模板库综合匹配"
        return f"【{prefix}】{reason_body}。"

    # ============================================================
    # 二、AI 侦查研判建议（FR-3.4.2）
    # ============================================================
    def analyze(
        self,
        session: RecordSession,
        qa_items: list[QAItem],
        key_gap_elements: list[dict] | None = None,
    ) -> AnalysisResult:
        """基于问答上下文生成侦查研判建议（FR-3.4.2 处理逻辑）。

        步骤：
        1) 提取事实特征；
        2) 生成案由类型判定 + 判定依据支撑链；
        3) 生成侦查指引与推荐补充问题；
        4) 若存在重点缺口，追问建议置顶（GR-2）。

        :param session: 笔录会话
        :param qa_items: 当前问答上下文
        :param key_gap_elements: 重点缺口要素清单（由五流引擎计算，[{"code","name","flow"}]）
        :return: 研判聚合结果
        """
        # 拼接已作答问答作为上下文
        answered_text = " ".join(
            f"{q.question} {q.answer or ''}" for q in qa_items if q.is_answered
        )
        case_brief = session.case.brief if session.case else ""
        context_text = f"{case_brief} {answered_text}".strip()

        # 异常与边界：上下文不足时提示继续录入
        if len(context_text) < 10:
            return AnalysisResult(
                session_id=session.id,
                is_insufficient_context=True,
            )

        # 1) 事实特征提取（基于信号词命中）
        fact_features = self._extract_fact_features(context_text)

        # 2) 涉诈类型判定 + 依据支撑链
        judgement = self._judge_case_type(case_brief, answered_text, fact_features, session)

        # 3) 侦查指引建议
        guide = self._build_investigation_guide(judgement, session)

        # 4) 重点缺口追问建议（GR-1~GR-3，置顶）
        suggestions = self._build_key_gap_suggestions(session.id, key_gap_elements or [])

        return AnalysisResult(
            session_id=session.id,
            fact_features=fact_features,
            case_type_judgement=judgement,
            investigation_guide=guide,
            suggestions=suggestions,
        )

    def _extract_fact_features(self, context_text: str) -> list[FactFeature]:
        """提取事实特征：扫描全部模板信号词，命中即作为一个事实特征。"""
        from sqlalchemy import select
        from app.models.template import TemplateSignalWord

        # 加载全部信号词及其所属模板案由
        rows = self.db.execute(
            select(TemplateSignalWord.word, Template.category)
            .join(Template, Template.id == TemplateSignalWord.template_id)
        ).all()

        feature_map: dict[str, FactFeature] = {}
        for word, category in rows:
            if word and word in context_text:
                if word not in feature_map:
                    feature_map[word] = FactFeature(
                        feature=f"案情/答复中出现关键特征「{word}」，指向{category}类手法",
                        hit_signal_words=[word],
                    )
                else:
                    feature_map[word].hit_signal_words.append(word)
        return list(feature_map.values())[:20]

    def _judge_case_type(
        self,
        case_brief: str,
        answered_text: str,
        fact_features: list[FactFeature],
        session: RecordSession,
    ) -> CaseTypeJudgement:
        """生成涉诈类型判定与依据支撑链（8.3）。

        采用推荐算法对"案情 + 已答问答"综合打分，取最高分模板案由作为判定结论。
        """
        combined_text = f"{case_brief} {answered_text}".strip()
        result = self.recommend_templates(combined_text, top_n=1)
        if result.recommendations:
            top = result.recommendations[0]
            basis = [f"命中信号词：{'、'.join(top.hit_signal_words)}"] if top.hit_signal_words else []
            basis.extend([ff.feature for ff in fact_features[:3]])
            return CaseTypeJudgement(
                case_type=top.template.category,
                confidence=top.match_score,
                basis=basis or ["基于案情文本综合研判"],
                hit_signal_words=top.hit_signal_words,
            )
        # 无匹配时以录入案由兜底
        return CaseTypeJudgement(
            case_type=session.case.case_category if session.case else "未知类型",
            confidence=0.0,
            basis=["无高置信匹配，暂以录入案由为准"],
        )

    def _build_investigation_guide(self, judgement: CaseTypeJudgement, session: RecordSession) -> InvestigationGuide:
        """生成侦查指引建议（8.3：嫌疑人画像/资金链拦截/后续补充侦查）。"""
        case_type = judgement.case_type
        return InvestigationGuide(
            suspect_profile=f"嫌疑人疑似以「{case_type}」手法实施诈骗，建议围绕其自称为身份、联系方式与作案账号开展画像刻画。",
            fund_interception="建议第一时间对涉案转出/收款卡号发起止付冻结，调取交易流水追踪下游资金去向，固定转账时间与流水号证据。",
            followup_investigation="建议补充询问引流渠道（二维码/网址/APP）、聊天工具账号、屏幕共享记录及登录 IP 设备，完善五流证据链。",
        )

    def _build_key_gap_suggestions(self, session_id: str, key_gap_elements: list[dict]) -> list[SuggestionOut]:
        """生成重点缺口追问建议（5.4 GR-1~GR-3，置顶展示）。

        :param key_gap_elements: 缺口要素清单 [{"code","name","flow_label"}]
        """
        suggestions: list[SuggestionOut] = []
        if not key_gap_elements:
            return suggestions

        # GR-3：针对缺失的具体核心要素生成追问，如"请明确每笔转账的时间、转出银行卡号及对方收款卡号和户名"
        # 按流分组生成追问
        by_flow: dict[str, list[dict]] = {}
        for el in key_gap_elements:
            by_flow.setdefault(el.get("flow_label", "相关"), []).append(el)

        idx = 0
        for flow_label, elements in by_flow.items():
            names = "、".join(e.get("name", e.get("code", "")) for e in elements)
            content = f"请明确{names}等{flow_label}关键信息。"
            # 资金流缺口使用需求文档 GR-3 的标准话术
            if flow_label == "资金流":
                content = "请明确每笔转账的时间、转出银行卡号及对方收款卡号和户名。"
            target_chapter = Chapter.FUND_LOSS.value if flow_label == "资金流" else Chapter.EVIDENCE_SUPPLEMENT.value
            for e in elements:
                suggestions.append(
                    SuggestionOut(
                        id=f"gap_{session_id}_{e.get('code')}",
                        session_id=session_id,
                        suggestion_type=SuggestionType.KEY_GAP_QUESTION,
                        title=f"【重点缺口追问·{flow_label}】",
                        content=content,
                        confidence=1.0,
                        target_chapter=target_chapter,
                        target_element_code=e.get("code"),
                        is_pinned=True,   # GR-2 置顶
                        is_adopted=False,
                        sort_order=idx,
                        created_at=datetime.now(),  # 未持久化的即时建议，取当前时间
                    )
                )
                idx += 1
                # 每个流仅生成一条聚合追问，避免重复
                break
        return suggestions
