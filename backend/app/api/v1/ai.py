"""
AI 研判推荐路由（BE-5）

对应需求文档：
- FR-3.3.2 基于案情文本的 AI 智能推荐匹配（匹配度加权算法 S(D,T)）；
- FR-3.4.2 AI 特征提取与侦查研判建议（问答变更后触发）；
- 5.4 重点缺口追问建议生成规则（GR-1~GR-4）；
- 6.4 中栏 AI 侦查研判区、6.3 模板匹配页推荐卡片。

接口能力：
1) POST /ai/recommend                    基于案情文本推荐模板（返回匹配度/命中信号词/推荐理由）；
2) POST /ai/sessions/{id}/analyze        触发会话级研判（五流缺口 + 涉诈类型判定 + 侦查指引 + 追问建议）；
3) GET  /ai/sessions/{id}/suggestions    获取已持久化的中栏建议（断点恢复用）；
4) POST /ai/sessions/{id}/adopt          一键采纳推荐问题（转左栏问答，去重，GR-4）。
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.core.enums import Permission
from app.core.exceptions import ConflictError
from app.models.record import AiSuggestion, QAItem
from app.schemas.ai import (
    AdoptSuggestionRequest,
    AdoptSuggestionResult,
    AnalysisResult,
    SuggestionOut,
)
from app.schemas.common import ApiResponse
from app.schemas.template import TemplateRecommendRequest, TemplateRecommendResult
from app.services.ai_service import AiService
from app.services.fiveflow_service import FiveFlowService
from app.services.session_service import SessionService

router = APIRouter(prefix="/ai", tags=["BE-5 AI 研判推荐"])


# ============================================================
# 一、模板智能推荐（FR-3.3.2 / 6.3）
# ============================================================
@router.post("/recommend", response_model=ApiResponse[TemplateRecommendResult], summary="AI 智能推荐模板")
def recommend_templates(
    payload: TemplateRecommendRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[TemplateRecommendResult]:
    """基于案情文本推荐模板（FR-3.3.2 处理逻辑）。

    计算 S(D,T)=α·F_sig+β·F_cat+γ·F_sem，按评分降序返回 TOP N；
    无高置信匹配时降级（is_degraded=True），前端转为全量模板库检索。
    """
    result = AiService(db).recommend_templates(
        brief=payload.brief,
        case_category=payload.case_category,
        top_n=payload.top_n,
    )
    return ApiResponse.ok(result)


# ============================================================
# 二、AI 侦查研判（FR-3.4.2 / 5.4 / 6.4 中栏）
# ============================================================
@router.post("/sessions/{session_id}/analyze", response_model=ApiResponse[AnalysisResult],
             summary="触发会话级 AI 研判")
def analyze_session(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[AnalysisResult]:
    """问答变更后触发 AI 研判（FR-3.4.2）。

    编排流程：
    1) 读取会话与问答上下文；
    2) 五流引擎计算覆盖度并收集重点缺口要素（GR-1）；
    3) AI 生成事实特征、涉诈类型判定、侦查指引与缺口追问建议；
    4) 建议持久化至中栏（DE-10，供断点恢复），重点缺口追问置顶（GR-2）。
    """
    service = SessionService(db)
    # 触发读取权限校验（DR-4）
    session = service._get_session_with_case(session_id)
    service._assert_read_access(session, current_user)

    # 加载问答上下文
    qa_items = list(db.execute(
        select(QAItem).where(QAItem.session_id == session_id).order_by(QAItem.sort_order)
    ).scalars().all())

    # 五流覆盖度 → 重点缺口要素清单（GR-1）
    fiveflow = FiveFlowService(db)
    coverage = fiveflow.compute_coverage(session)
    key_gaps = fiveflow.collect_key_gap_elements(coverage)

    # AI 研判生成
    analysis = AiService(db).analyze(session, qa_items, key_gaps)

    # 持久化建议到中栏（先清旧未采纳建议，重点缺口置顶）
    suggestions_payload = [s.model_dump(mode="json") for s in analysis.suggestions]
    service.persist_ai_suggestions(session_id, suggestions_payload)

    return ApiResponse.ok(analysis, message="AI 研判完成")


@router.get("/sessions/{session_id}/suggestions", response_model=ApiResponse[list[SuggestionOut]],
            summary="获取中栏 AI 建议")
def list_suggestions(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[list[SuggestionOut]]:
    """获取会话已持久化的中栏 AI 建议（6.4 中栏卡片流，断点恢复用）。

    置顶优先（重点缺口追问 GR-2），未采纳在前。
    """
    service = SessionService(db)
    session = service._get_session(session_id)
    service._assert_read_access(session, current_user)
    suggestions = service._list_suggestions(session_id)
    return ApiResponse.ok([SuggestionOut.model_validate(s) for s in suggestions])


@router.post("/sessions/{session_id}/adopt", response_model=ApiResponse[AdoptSuggestionResult],
             summary="一键采纳 AI 推荐问题",
             dependencies=[Depends(require_permission(Permission.AI_ADOPT))])
def adopt_suggestion(
    session_id: str,
    payload: AdoptSuggestionRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[AdoptSuggestionResult]:
    """采纳 AI 推荐问题，追加至左栏对应章节（GR-4，来源=AI 推荐，去重处理）。

    重复问题不重复添加（FR-3.4.2 异常与边界），返回 is_duplicate 标识。
    """
    service = SessionService(db)
    # 读取建议内容（仅已持久化建议可采纳；即时缺口建议需先经 analyze 落库）
    suggestion = db.get(AiSuggestion, payload.suggestion_id)
    if suggestion is not None:
        question_text = suggestion.content
        target_chapter = suggestion.target_chapter or "evidence_supplement"
    else:
        # 即时建议（未持久化的重点缺口追问）：从请求无法还原内容时拒绝
        raise ConflictError("建议不存在或已失效，请重新触发 AI 研判")

    try:
        qa = service.adopt_suggestion(
            session_id, payload.suggestion_id, question_text, target_chapter, current_user, request
        )
    except ConflictError as exc:
        # 去重：重复问题不新增（GR-4）
        return ApiResponse.ok(AdoptSuggestionResult(
            success=False, qa_id=None, is_duplicate=True, message=str(exc.message)
        ))

    return ApiResponse.ok(AdoptSuggestionResult(
        success=True, qa_id=qa.id, is_duplicate=False, message="推荐问题已采纳并追加至问询列表"
    ))
