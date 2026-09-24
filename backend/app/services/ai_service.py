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

import json
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
from app.services.llm import LLMService, LLMUnavailableError
from app.services.llm.prompts import build_semantic_fingerprint_text


class AiService:
    """AI 研判推荐服务：模板推荐匹配 + 侦查研判建议生成。"""

    def __init__(self, db: Session):
        self.db = db
        # 大模型能力门面（懒加载单例客户端）；LLM_ENABLED=False 时其调用一律抛降级信号
        self._llm = LLMService(db)

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

        # 语义向量准备（能力一）：若语义开关开启，先单次计算案情向量并批量补齐模板向量；
        # 任一环节不可用（未启用/网络异常）→ case_vector 置空，后续逐模板回落字符 bigram。
        case_vector = self._prepare_semantic_vectors(cleaned_brief, templates)

        # 逐一计算匹配度评分 S(D,T)
        scored: list[TemplateRecommendItem] = []
        for tpl in templates:
            item = self._score_template(cleaned_brief, case_category, tpl, case_vector)
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

    def _score_template(self, brief: str, case_category: str | None, tpl: Template,
                        case_vector: list[float] | None = None) -> TemplateRecommendItem:
        """计算单个模板对案情文本的匹配度评分（FR-3.3.2 加权算法）。

        :param case_vector: 案情文本向量（能力一）；为 None 时 F_sem 回落字符 bigram
        """
        # --- F_sig 信号词命中因子 = Σ(w_i·hit_i)/Σw_i ---
        f_sig, hit_words = self._compute_signal_factor(brief, tpl)
        # --- F_cat 案由类别因子 ---
        f_cat = self._compute_category_factor(case_category, tpl)
        # --- F_sem 语义相似因子（优先向量余弦，不可用时回落 bigram）---
        f_sem = self._compute_semantic_factor(brief, tpl, case_vector)

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

    # ------------------------------------------------------------
    # F_sem 语义相似因子：向量化（能力一）+ 字符 bigram 降级
    # ------------------------------------------------------------
    def _prepare_semantic_vectors(self, brief: str, templates: list[Template]) -> list[float] | None:
        """准备语义匹配所需的向量（能力一）。

        若语义开关开启：单次计算案情文本向量，并批量补齐启用模板的语义指纹向量。
        任一环节不可用（未启用/网络异常）→ 返回 None，调用方逐模板回落字符 bigram。

        :return: 案情文本向量；不可用时返回 None
        """
        if not self._llm.is_semantic_enabled():
            return None
        try:
            case_vector = self._llm.embed_texts([brief])[0]
        except LLMUnavailableError:
            return None
        # best-effort 批量补齐模板向量（失败不阻断，缺失项回落 bigram）
        self._ensure_template_embeddings(templates)
        return case_vector

    def _ensure_template_embeddings(self, templates: list[Template]) -> None:
        """批量计算并回写缺失/过期的模板语义向量（单次 embed 调用，best-effort）。

        过期判定：embedding 为空或 embedding_model 与当前配置不一致。回写后持久化，
        避免后续重复计算；失败时静默降级（相关模板回落 bigram）。
        """
        model = settings.LLM_EMBEDDING_MODEL
        pending = [t for t in templates if not (t.embedding and t.embedding_model == model)]
        if not pending:
            return
        fingerprints = [
            build_semantic_fingerprint_text(
                t.category, t.description, [w.word for w in (t.signal_words or []) if w.word]
            )
            for t in pending
        ]
        try:
            vectors = self._llm.embed_texts(fingerprints)
        except LLMUnavailableError:
            return
        for tpl, vec in zip(pending, vectors):
            tpl.embedding = json.dumps(vec)
            tpl.embedding_model = model
        self.db.commit()

    def _load_template_vector(self, tpl: Template) -> list[float] | None:
        """从 Template.embedding 读取模板向量；缺失/过期/解析失败时即时计算并回写持久化。

        :return: 模板语义向量；无法获得时返回 None（触发 bigram 降级）
        """
        model = settings.LLM_EMBEDDING_MODEL
        # 命中持久化且模型未变更，直接反序列化
        if tpl.embedding and tpl.embedding_model == model:
            try:
                vec = json.loads(tpl.embedding)
                if isinstance(vec, list) and vec:
                    return [float(x) for x in vec]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass  # 脏数据视为缺失，走即时重算
        # 缺失或过期：即时计算单条并回写
        fingerprint = build_semantic_fingerprint_text(
            tpl.category, tpl.description, [w.word for w in (tpl.signal_words or []) if w.word]
        )
        try:
            vec = self._llm.embed_texts([fingerprint])[0]
        except LLMUnavailableError:
            return None
        tpl.embedding = json.dumps(vec)
        tpl.embedding_model = model
        self.db.commit()
        return vec

    @staticmethod
    def _cosine_vectors(a: list[float], b: list[float]) -> float | None:
        """计算两个向量的余弦相似度；维度不一致或零向量时返回 None。"""
        if not a or not b or len(a) != len(b):
            return None
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return None
        return dot / (norm_a * norm_b)

    def _compute_semantic_factor(self, brief: str, tpl: Template,
                                 case_vector: list[float] | None = None) -> float:
        """计算 F_sem 语义相似因子（0~1）。

        优先采用"案情向量 · 模板向量"余弦相似度（能力一）；任一向量缺失或
        语义能力不可用时，回落到基于字符 bigram 的余弦相似度，保证公式
        S(D,T)=α·F_sig+β·F_cat+γ·F_sem 结构与取值范围一致。
        """
        if case_vector is not None:
            tpl_vector = self._load_template_vector(tpl)
            if tpl_vector is not None:
                sim = self._cosine_vectors(case_vector, tpl_vector)
                if sim is not None:
                    # 向量余弦可能为负，语义相似度截断到 [0,1]
                    return max(0.0, min(1.0, sim))
        # 回落：字符 bigram 余弦相似度
        return self._semantic_factor_bigram(brief, tpl)

    @staticmethod
    def _semantic_factor_bigram(brief: str, tpl: Template) -> float:
        """F_sem 降级实现：基于字符 bigram 的余弦相似度（无大模型时的工程化方案）。

        将案情文本与"模板描述 + 案由 + 信号词"构成的模板语义指纹进行相似度度量，
        语义指纹文本与向量化路径同源（build_semantic_fingerprint_text），便于平滑降级。
        """
        tpl_text = build_semantic_fingerprint_text(
            tpl.category, tpl.description, [w.word for w in (tpl.signal_words or []) if w.word]
        )
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

        # 能力二：优先走大模型研判；未启用/超时/异常/校验失败时降级到规则链路。
        gaps = key_gap_elements or []
        try:
            return self._analyze_by_llm(session, context_text, gaps)
        except LLMUnavailableError:
            # 降级：置 is_timeout=True（复用现有标识）并执行规则链路兜底
            result = self._analyze_by_rules(session, case_brief, answered_text, context_text, gaps)
            result.is_timeout = True
            return result

    def _analyze_by_rules(
        self,
        session: RecordSession,
        case_brief: str,
        answered_text: str,
        context_text: str,
        gaps: list[dict],
    ) -> AnalysisResult:
        """规则链路研判（降级兜底，逻辑与接入大模型前保持一致）。

        步骤：事实特征提取 → 涉诈类型判定 → 侦查指引 → 重点缺口追问（置顶）。
        """
        # 1) 事实特征提取（基于信号词命中）
        fact_features = self._extract_fact_features(context_text)
        # 2) 涉诈类型判定 + 依据支撑链
        judgement = self._judge_case_type(case_brief, answered_text, fact_features, session)
        # 3) 侦查指引建议
        guide = self._build_investigation_guide(judgement, session)
        # 4) 重点缺口追问建议（GR-1~GR-3，置顶）
        suggestions = self._build_key_gap_suggestions(session.id, gaps)
        return AnalysisResult(
            session_id=session.id,
            fact_features=fact_features,
            case_type_judgement=judgement,
            investigation_guide=guide,
            suggestions=suggestions,
        )

    def _analyze_by_llm(self, session: RecordSession, context_text: str, gaps: list[dict]) -> AnalysisResult:
        """大模型研判链路（能力二）。

        将 LLM 结构化结果映射为 CaseTypeJudgement（含 basis 支撑链）、InvestigationGuide、
        FactFeature[]，并把 LLM 的 followup_questions 与五流重点缺口追问合并为 SuggestionOut[]
        （缺口追问仍 is_pinned=True 置顶，符合 GR-2）。

        :raises LLMUnavailableError: 未启用/开关关闭/网络异常/校验失败，由调用方降级
        """
        # 全部启用模板案由清单，用于约束 LLM 判定结论取值
        categories = self._list_all_categories()
        judge = self._llm.judge_case(context_text, categories, gaps)

        # 事实特征：优先采用 LLM 输出，空则回落信号词命中特征
        fact_features = [FactFeature(feature=f) for f in judge.fact_features]
        if not fact_features:
            fact_features = self._extract_fact_features(context_text)

        # 涉诈类型判定 + 依据支撑链（LLM 未给出案由时以录入案由兜底）
        case_type = judge.case_type or (session.case.case_category if session.case else "未知类型")
        judgement = CaseTypeJudgement(
            case_type=case_type,
            confidence=judge.confidence,
            basis=judge.basis or ["基于大模型综合研判"],
        )

        # 侦查指引（嫌疑人画像/资金链拦截/后续补充侦查）
        guide = InvestigationGuide(
            suspect_profile=judge.suspect_profile or None,
            fund_interception=judge.fund_interception or None,
            followup_investigation=judge.followup_investigation or None,
        )

        # 追问建议：重点缺口追问置顶（GR-2）+ LLM 补充追问（不置顶）
        suggestions = self._build_key_gap_suggestions(session.id, gaps)
        suggestions.extend(
            self._build_llm_followup_suggestions(session.id, judge.followup_questions, len(suggestions))
        )

        return AnalysisResult(
            session_id=session.id,
            fact_features=fact_features,
            case_type_judgement=judgement,
            investigation_guide=guide,
            suggestions=suggestions,
        )

    def _list_all_categories(self) -> list[str]:
        """列出全部启用模板的案由类别（去重保序），供 LLM 研判约束取值范围。"""
        from sqlalchemy import select

        rows = self.db.execute(
            select(Template.category).where(Template.is_enabled.is_(True))
        ).scalars().all()
        seen: list[str] = []
        for c in rows:
            if c and c not in seen:
                seen.append(c)
        return seen

    def _build_llm_followup_suggestions(
        self, session_id: str, questions: list[str], start_index: int = 0
    ) -> list[SuggestionOut]:
        """将 LLM 输出的补充追问问题封装为中栏建议（不置顶，来源为推荐补充问题）。"""
        suggestions: list[SuggestionOut] = []
        idx = start_index
        for q in questions:
            content = (q or "").strip()
            if not content:
                continue
            suggestions.append(
                SuggestionOut(
                    id=f"llm_{session_id}_{idx}",
                    session_id=session_id,
                    suggestion_type=SuggestionType.FOLLOWUP_QUESTION,
                    title="【AI 推荐补充问题】",
                    content=content,
                    confidence=None,
                    target_chapter=Chapter.EVIDENCE_SUPPLEMENT.value,
                    target_element_code=None,
                    is_pinned=False,   # 非缺口追问，不置顶（GR-2 仅缺口追问置顶）
                    is_adopted=False,
                    sort_order=idx,
                    created_at=datetime.now(),
                )
            )
            idx += 1
        return suggestions

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
