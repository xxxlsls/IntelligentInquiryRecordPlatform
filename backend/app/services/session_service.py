"""
笔录生命周期服务（BE-2）

实现需求文档：
- FR-3.2.1 案件接报录入与草稿保存（会话新增、阶段标记）；
- FR-3.3.3 多模板组合选定与大纲装配（templates→inquiry）；
- FR-3.4.1 结构化大纲章节问答编排（行内编辑、新增/删除、来源标记）；
- 4.5 四阶段断点续问（intake/templates/inquiry/completed 现场恢复）；
- 6.1 笔录台账检索（复合多条件、状态筛选、分页）；
- DR-2/DR-3/DR-4 数据权限与机构隔离。

编排关系：本服务是核心编排层，问答变更后联动调用五流引擎（BE-6）与 AI 研判（BE-5），
并写入操作审计（BE-8）。
"""

import json
from datetime import datetime

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.dependencies import DataScope
from app.core.enums import (
    CHAPTER_LABEL,
    CHAPTER_ORDER,
    AuditOpType,
    Chapter,
    QASource,
    Role,
    Stage,
    SuggestionType,
)
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.models.case import Case, Reporter
from app.models.record import AiSuggestion, QAItem, RecordSession, SessionTemplate
from app.models.template import Template
from app.models.user import User
from app.schemas.session import (
    QACreate,
    QAUpdate,
    SessionCreate,
    SessionListItem,
    SessionUpdate,
)
from app.services.audit_service import AuditService
from app.services.fiveflow_service import FiveFlowService
from app.services.template_service import TemplateService


class SessionService:
    """笔录生命周期服务（BE-2 核心编排）。"""

    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.template_service = TemplateService(db)
        self.fiveflow_service = FiveFlowService(db)

    # ============================================================
    # 一、接报录入与草稿保存（FR-3.2.1）
    # ============================================================
    def create_session(self, data: SessionCreate, user: User, request: Request | None = None) -> RecordSession:
        """新增笔录会话：一次性创建 Case + Reporter + RecordSession，阶段=intake。

        处理逻辑（FR-3.2.1）：
        1) 案件编号唯一性校验；
        2) 创建案件与报案人主数据；
        3) 创建笔录会话，机构归属绑定当前用户机构（DR-1 不可篡改）。

        :raises ConflictError: 案件编号重复
        """
        # 案件编号唯一性校验（异常与边界：案件编号重复拒绝）
        exists = self.db.execute(select(Case).where(Case.case_no == data.case_no)).scalar_one_or_none()
        if exists:
            raise ConflictError(f"案件编号 {data.case_no} 已存在")

        org = user.org
        org_path = org.org_path if org else ""
        handling_org = data.handling_org or (org.name if org else "")

        # 创建案件（DE-2）
        case = Case(
            case_no=data.case_no,
            case_category=data.case_category,
            brief=data.brief,
            handling_org=handling_org,
            handling_org_code=org.code if org else None,
            report_time=data.report_time or datetime.now(),
            owner_org_id=user.org_id,       # DR-1 机构归属，不可篡改
            owner_org_path=org_path,
            creator_no=user.officer_no,
        )
        # 创建报案人（DE-3）
        case.reporter = Reporter(
            name=data.reporter_name,
            id_card=data.reporter_id_card,
            phone=data.reporter_phone,
        )
        self.db.add(case)
        self.db.flush()  # 获取 case.id

        # 创建笔录会话（DE-1），初始阶段 intake
        session = RecordSession(
            case_id=case.id,
            stage=Stage.INTAKE.value,
            creator_org_id=user.org_id,
            creator_org_path=org_path,
            creator_no=user.officer_no,
            progress=0,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        # 创建审计（2.4.2）
        self.audit.log(
            op_type=AuditOpType.RECORD_CREATE,
            officer_no=user.officer_no,
            case_no=case.case_no,
            session_id=session.id,
            request=request,
            description=f"新增笔录会话，案件编号 {case.case_no}",
        )
        return session

    def update_draft(self, session_id: str, data: SessionUpdate, user: User,
                     request: Request | None = None) -> RecordSession:
        """更新草稿（intake 阶段可修改案件与报案人信息）。"""
        session = self._get_session_with_case(session_id)
        self._assert_write_access(session, user)
        if session.stage not in (Stage.INTAKE.value, Stage.TEMPLATES.value):
            raise ValidationError("仅接报录入/模板选择阶段可修改案件信息")

        case = session.case
        if data.case_category is not None:
            case.case_category = data.case_category
        if data.brief is not None:
            case.brief = data.brief
        if data.handling_org is not None:
            case.handling_org = data.handling_org
        if data.report_time is not None:
            case.report_time = data.report_time
        if case.reporter:
            if data.reporter_name is not None:
                case.reporter.name = data.reporter_name
            if data.reporter_id_card is not None:
                case.reporter.id_card = data.reporter_id_card
            if data.reporter_phone is not None:
                case.reporter.phone = data.reporter_phone

        self.db.commit()
        self.db.refresh(session)
        return session

    def apply_external_backfill(self, session_id: str, backfill: dict, user: User,
                                request: Request | None = None) -> RecordSession:
        """应用外部系统回填数据到案件（FR-3.2.2 字段映射回填）。

        :param backfill: 外部系统映射后的字段字典
        """
        session = self._get_session_with_case(session_id)
        self._assert_write_access(session, user)
        case = session.case

        # 字段映射回填（缺失项留空待补，FR-3.2.2 异常与边界）
        if backfill.get("case_category"):
            case.case_category = backfill["case_category"]
        if backfill.get("brief"):
            case.brief = backfill["brief"]
        if backfill.get("handling_org"):
            case.handling_org = backfill["handling_org"]
        case.external_source = backfill.get("external_source")
        case.external_case_id = backfill.get("external_case_id")
        if case.reporter:
            if backfill.get("reporter_name"):
                case.reporter.name = backfill["reporter_name"]
            if backfill.get("reporter_id_card"):
                case.reporter.id_card = backfill["reporter_id_card"]
            if backfill.get("reporter_phone"):
                case.reporter.phone = backfill["reporter_phone"]

        self.db.commit()
        self.db.refresh(session)

        # 外部系统同步审计（2.4.2：检索关键字、命中案件、回填动作）
        self.audit.log(
            op_type=AuditOpType.EXTERNAL_SYNC,
            officer_no=user.officer_no,
            case_no=case.case_no,
            session_id=session.id,
            request=request,
            description=f"外部系统回填：来源 {case.external_source}，案件 {case.external_case_id}",
            detail={"external_source": case.external_source, "external_case_id": case.external_case_id},
        )
        return session

    # ============================================================
    # 二、阶段流转与断点续问（4.5 / BP-5）
    # ============================================================
    def transit_stage(self, session_id: str, target: Stage, user: User,
                      request: Request | None = None) -> RecordSession:
        """阶段流转（4.5 状态机）。仅允许向前推进一个阶段或停留当前阶段。

        :raises ValidationError: 非法流转
        """
        session = self._get_session(session_id)
        self._assert_write_access(session, user)

        current = Stage(session.stage)
        if not current.can_transit_to(target):
            raise ValidationError(f"非法阶段流转：{current.value} → {target.value}")

        # 流转前置校验：进入 templates 需案件必填完整；进入 inquiry 需已选模板
        if target == Stage.TEMPLATES:
            self._validate_intake_complete(session)
        if target == Stage.INQUIRY:
            if not session.selected_templates:
                raise ValidationError("请先选定问询模板再开始问询")

        old_stage = session.stage
        session.stage = target.value
        if target == Stage.COMPLETED:
            session.progress = 100
        self.db.commit()
        self.db.refresh(session)

        # 阶段流转审计
        self.audit.log(
            op_type=AuditOpType.STAGE_CHANGE,
            officer_no=user.officer_no,
            case_no=session.case.case_no if session.case else None,
            session_id=session.id,
            request=request,
            description=f"阶段流转 {old_stage} → {target.value}",
            detail={"from": old_stage, "to": target.value},
        )
        return session

    def _validate_intake_complete(self, session: RecordSession) -> None:
        """校验接报录入必填完整（FR-3.2.1：必填缺失阻止流转）。"""
        case = session.case
        if case is None:
            raise ValidationError("案件信息缺失")
        missing = []
        if not case.case_no:
            missing.append("案件编号")
        if not case.case_category:
            missing.append("案件类别")
        if not case.brief or len(case.brief.strip()) < 10:
            missing.append("简要案情(≥10字)")
        if not case.handling_org:
            missing.append("办案单位")
        if not case.reporter or not case.reporter.name:
            missing.append("报案人姓名")
        if missing:
            raise ValidationError(f"以下必填项缺失，无法进入模板选择：{'、'.join(missing)}")

    def select_templates_and_start(self, session_id: str, template_ids: list[str], user: User,
                                   request: Request | None = None) -> RecordSession:
        """多模板组合选定并装配大纲，流转 templates→inquiry（FR-3.3.3）。

        处理逻辑：
        1) 校验模板存在且启用；
        2) 记录已选模板；
        3) 合并问题集、章节归类去重装配大纲，生成 QAItem（来源=模板预置）；
        4) 阶段流转至 inquiry。
        """
        session = self._get_session(session_id)
        self._assert_write_access(session, user)
        if not template_ids:
            raise ValidationError("请至少选择一个模板")

        # 校验模板存在且启用
        templates = self.db.execute(
            select(Template).where(Template.id.in_(template_ids))
        ).scalars().all()
        if len(templates) != len(set(template_ids)):
            raise NotFoundError("部分选中模板不存在")
        for tpl in templates:
            if not tpl.is_enabled:
                raise ValidationError(f"模板「{tpl.name}」已停用，不可选用")

        # 清空旧的模板选择与问答（重新装配）
        self.db.query(SessionTemplate).filter(SessionTemplate.session_id == session_id).delete()
        self.db.query(QAItem).filter(QAItem.session_id == session_id).delete()

        # 记录已选模板（保留选定顺序）
        for idx, tid in enumerate(template_ids):
            self.db.add(SessionTemplate(session_id=session_id, template_id=tid, sort_order=idx))

        # 装配大纲（FR-3.3.3：合并问题集、章节归类去重）
        outline = self.template_service.assemble_outline(template_ids)
        sort_counter = 0
        for chapter_block in outline:
            for q in chapter_block["questions"]:
                self.db.add(QAItem(
                    session_id=session_id,
                    chapter=chapter_block["chapter"],
                    question=q["question"],
                    answer=None,
                    source=QASource.TEMPLATE.value,
                    sort_order=sort_counter,
                    template_question_id=q.get("template_question_id"),
                ))
                sort_counter += 1

        session.stage = Stage.INQUIRY.value
        session.progress = 0
        self.db.commit()
        self.db.refresh(session)

        self.audit.log(
            op_type=AuditOpType.STAGE_CHANGE,
            officer_no=user.officer_no,
            case_no=session.case.case_no if session.case else None,
            session_id=session.id,
            request=request,
            description=f"选定 {len(template_ids)} 个模板并装配大纲，进入问询",
            detail={"template_ids": template_ids, "qa_count": sort_counter},
        )
        return session

    def archive_session(self, session_id: str, user: User, request: Request | None = None) -> RecordSession:
        """归档已完成会话（completed → 归档）。"""
        session = self._get_session(session_id)
        self._assert_write_access(session, user)
        if session.stage != Stage.COMPLETED.value:
            raise ValidationError("仅已完成问询的笔录可归档")
        session.is_archived = True
        self.db.commit()
        self.db.refresh(session)
        return session

    def restore(self, session_id: str, user: User, request: Request | None = None) -> dict:
        """断点续问现场恢复（4.5 / BP-5）。

        根据持久化阶段标识识别恢复目标界面，返回恢复内容：
        - intake    → 接报录入模态框：案件/报案人表单
        - templates → 模板匹配页：已勾选模板
        - inquiry   → 三栏工作台：问答、五流、材料、AI建议
        - completed → 笔录预览页：封存笔录全文

        :return: {stage, target_view, restore_data}
        """
        session = self._get_session_with_case(session_id)
        self._assert_read_access(session, user, request)

        stage = Stage(session.stage)
        target_view_map = {
            Stage.INTAKE: "intake_modal",
            Stage.TEMPLATES: "template_page",
            Stage.INQUIRY: "workbench",
            Stage.COMPLETED: "preview_page",
        }
        restore_data: dict = {"session_id": session.id}

        # 通用：案件与报案人表单
        case = session.case
        if case:
            restore_data["case"] = {
                "case_no": case.case_no,
                "case_category": case.case_category,
                "brief": case.brief,
                "handling_org": case.handling_org,
                "report_time": case.report_time.isoformat() if case.report_time else None,
                "external_source": case.external_source,
            }
            if case.reporter:
                restore_data["reporter"] = {
                    "name": case.reporter.name,
                    "id_card": case.reporter.id_card,
                    "phone": case.reporter.phone,
                }

        # 已选模板
        restore_data["selected_template_ids"] = [t.id for t in session.selected_templates]

        if stage in (Stage.INQUIRY, Stage.COMPLETED):
            # 三栏工作台/预览：恢复问答、五流覆盖、AI建议
            restore_data["qa_chapters"] = self.get_qa_by_chapter(session_id)
            analysis = self.fiveflow_service.compute_coverage(session)
            restore_data["five_flow"] = analysis.model_dump()
            restore_data["ai_suggestions"] = [
                {
                    "id": s.id, "type": s.suggestion_type, "title": s.title,
                    "content": s.content, "is_pinned": s.is_pinned, "is_adopted": s.is_adopted,
                    "target_chapter": s.target_chapter,
                }
                for s in self._list_suggestions(session_id)
            ]

        # 合并阶段快照中的额外上下文
        if session.stage_snapshot:
            try:
                restore_data["snapshot"] = json.loads(session.stage_snapshot)
            except (json.JSONDecodeError, TypeError):
                restore_data["snapshot"] = {}

        # 案件访问审计（2.4.2：打开/查看笔录详情）
        self.audit.log(
            op_type=AuditOpType.CASE_ACCESS,
            officer_no=user.officer_no,
            case_no=case.case_no if case else None,
            session_id=session_id,
            request=request,
            description=f"恢复断点现场，阶段 {stage.value}",
        )

        return {
            "session_id": session.id,
            "stage": stage.value,
            "target_view": target_view_map[stage],
            "restore_data": restore_data,
        }

    def save_snapshot(self, session_id: str, snapshot: dict, user: User) -> None:
        """保存断点现场快照（暂时保存，SE-4/BP-5）。"""
        session = self._get_session(session_id)
        self._assert_write_access(session, user)
        session.stage_snapshot = json.dumps(snapshot, ensure_ascii=False)
        self.db.commit()

    # ============================================================
    # 三、问答编排（FR-3.4.1）
    # ============================================================
    def get_qa_by_chapter(self, session_id: str) -> list[dict]:
        """按大纲章节归类返回问答项（6.4 左栏卡片流）。"""
        items = self.db.execute(
            select(QAItem).where(QAItem.session_id == session_id).order_by(QAItem.sort_order)
        ).scalars().all()

        groups: dict[Chapter, list[dict]] = {ch: [] for ch in CHAPTER_ORDER}
        for it in items:
            try:
                ch = Chapter(it.chapter)
            except ValueError:
                ch = Chapter.EVIDENCE_SUPPLEMENT
            groups[ch].append({
                "id": it.id,
                "question": it.question,
                "answer": it.answer,
                "source": it.source,
                "sort_order": it.sort_order,
                "is_answered": it.is_answered,
            })

        return [
            {"chapter": ch.value, "chapter_label": CHAPTER_LABEL[ch], "items": groups[ch]}
            for ch in CHAPTER_ORDER
        ]

    def create_qa(self, session_id: str, data: QACreate, user: User,
                  request: Request | None = None) -> QAItem:
        """新增问答项（FR-3.4.1：新增问答插入指定章节）。"""
        session = self._get_session(session_id)
        self._assert_write_access(session, user)
        if session.stage not in (Stage.INQUIRY.value, Stage.COMPLETED.value):
            raise ValidationError("仅问询阶段可编排问答")

        # 排序号：未指定则追加到该章节末尾
        if data.sort_order is None:
            max_order = self.db.execute(
                select(func.max(QAItem.sort_order)).where(QAItem.session_id == session_id)
            ).scalar() or 0
            sort_order = max_order + 1
        else:
            sort_order = data.sort_order

        qa = QAItem(
            session_id=session_id,
            chapter=data.chapter.value,
            question=data.question.strip(),
            answer=data.answer,
            source=data.source.value,
            sort_order=sort_order,
        )
        self.db.add(qa)
        self.db.commit()
        self.db.refresh(qa)

        # 问答修改审计（2.4.2）
        self.audit.log_qa_change(
            officer_no=user.officer_no, session_id=session_id,
            case_no=session.case.case_no if session.case else None,
            action="新增", qa_id=qa.id, before=None,
            after={"question": qa.question, "answer": qa.answer, "chapter": qa.chapter},
            request=request,
        )
        # 联动五流抽取（ER-1）
        if qa.is_answered:
            self.fiveflow_service.extract_from_qa(session_id, [qa])
        return qa

    def update_qa(self, session_id: str, qa_id: str, data: QAUpdate, user: User,
                  request: Request | None = None) -> QAItem:
        """行内编辑问答项（FR-3.4.1：问答双向绑定实时保存）。"""
        session = self._get_session(session_id)
        self._assert_write_access(session, user)
        qa = self.db.get(QAItem, qa_id)
        if qa is None or qa.session_id != session_id:
            raise NotFoundError("问答项不存在")

        before = {"question": qa.question, "answer": qa.answer, "chapter": qa.chapter}
        if data.question is not None:
            qa.question = data.question.strip()
        if data.answer is not None:
            qa.answer = data.answer
        if data.chapter is not None:
            qa.chapter = data.chapter.value
        if data.sort_order is not None:
            qa.sort_order = data.sort_order

        self.db.commit()
        self.db.refresh(qa)

        # 问答修改审计（含变更前后指纹，2.4.2）
        after = {"question": qa.question, "answer": qa.answer, "chapter": qa.chapter}
        self.audit.log_qa_change(
            officer_no=user.officer_no, session_id=session_id,
            case_no=session.case.case_no if session.case else None,
            action="编辑", qa_id=qa.id, before=before, after=after, request=request,
        )
        # 联动五流增量抽取（ER-3：仅重新抽取变更项）
        if qa.is_answered:
            self.fiveflow_service.extract_from_qa(session_id, [qa])
        # 更新进度
        self._update_progress(session)
        return qa

    def delete_qa(self, session_id: str, qa_id: str, user: User,
                  request: Request | None = None) -> None:
        """删除问答项（FR-3.4.1：删除需二次确认，由前端保障）。"""
        session = self._get_session(session_id)
        self._assert_write_access(session, user)
        qa = self.db.get(QAItem, qa_id)
        if qa is None or qa.session_id != session_id:
            raise NotFoundError("问答项不存在")

        before = {"question": qa.question, "answer": qa.answer, "source": qa.source}
        self.db.delete(qa)
        self.db.commit()

        self.audit.log_qa_change(
            officer_no=user.officer_no, session_id=session_id,
            case_no=session.case.case_no if session.case else None,
            action="删除", qa_id=qa_id, before=before, after=None, request=request,
        )
        self._update_progress(session)

    def adopt_suggestion(self, session_id: str, suggestion_id: str, question_text: str,
                         target_chapter: str, user: User, request: Request | None = None) -> QAItem:
        """采纳 AI 推荐问题，追加至左栏对应章节（GR-4：来源=AI 推荐，去重）。

        :param question_text: 推荐问题内容
        :param target_chapter: 目标章节
        :raises ConflictError: 问题重复（去重处理）
        """
        session = self._get_session(session_id)
        self._assert_write_access(session, user)

        # 去重：同章节下相同问题不重复添加（FR-3.4.2 异常与边界）
        dup = self.db.execute(
            select(QAItem).where(
                QAItem.session_id == session_id,
                QAItem.question == question_text.strip(),
            )
        ).scalar_one_or_none()
        if dup:
            raise ConflictError("该推荐问题已存在于问询列表（已去重）")

        max_order = self.db.execute(
            select(func.max(QAItem.sort_order)).where(QAItem.session_id == session_id)
        ).scalar() or 0
        qa = QAItem(
            session_id=session_id,
            chapter=target_chapter,
            question=question_text.strip(),
            answer=None,
            source=QASource.AI_RECOMMEND.value,
            sort_order=max_order + 1,
        )
        self.db.add(qa)

        # 标记建议已采纳
        suggestion = self.db.get(AiSuggestion, suggestion_id)
        if suggestion:
            suggestion.is_adopted = True
            self.db.flush()
            suggestion.adopted_qa_id = qa.id

        self.db.commit()
        self.db.refresh(qa)

        # 采纳 AI 建议审计（2.4.2：采纳的推荐问题内容）
        self.audit.log(
            op_type=AuditOpType.AI_ADOPT,
            officer_no=user.officer_no,
            case_no=session.case.case_no if session.case else None,
            session_id=session_id,
            request=request,
            description=f"采纳 AI 推荐问题：{question_text[:50]}",
            detail={"suggestion_id": suggestion_id, "question": question_text, "chapter": target_chapter},
        )
        return qa

    def persist_ai_suggestions(self, session_id: str, suggestions: list[dict]) -> None:
        """持久化 AI 研判建议到中栏（供断点恢复，DE-10）。

        先清除旧的未采纳建议，再写入新建议（重点缺口追问置顶 GR-2）。
        """
        # 删除旧的未采纳建议（保留已采纳的追溯记录）
        old = self.db.execute(
            select(AiSuggestion).where(
                AiSuggestion.session_id == session_id,
                AiSuggestion.is_adopted.is_(False),
            )
        ).scalars().all()
        for s in old:
            self.db.delete(s)

        for idx, sg in enumerate(suggestions):
            self.db.add(AiSuggestion(
                session_id=session_id,
                suggestion_type=sg["suggestion_type"],
                title=sg.get("title"),
                content=sg["content"],
                basis=json.dumps(sg.get("basis"), ensure_ascii=False) if sg.get("basis") else None,
                confidence=sg.get("confidence"),
                target_chapter=sg.get("target_chapter"),
                target_element_code=sg.get("target_element_code"),
                is_pinned=sg.get("is_pinned", False),
                sort_order=idx,
            ))
        self.db.commit()

    def _list_suggestions(self, session_id: str) -> list[AiSuggestion]:
        """列出会话的 AI 建议（置顶优先，未采纳在前）。"""
        return list(self.db.execute(
            select(AiSuggestion)
            .where(AiSuggestion.session_id == session_id)
            .order_by(AiSuggestion.is_pinned.desc(), AiSuggestion.sort_order)
        ).scalars().all())

    def _update_progress(self, session: RecordSession) -> None:
        """更新问询进度：已作答问答数 / 总问答数 × 100。"""
        total = self.db.execute(
            select(func.count()).select_from(QAItem).where(QAItem.session_id == session.id)
        ).scalar() or 0
        if total == 0:
            session.progress = 0
        else:
            answered = self.db.execute(
                select(func.count()).select_from(QAItem).where(
                    QAItem.session_id == session.id,
                    QAItem.answer.isnot(None),
                    QAItem.answer != "",
                )
            ).scalar() or 0
            session.progress = int(round(answered / total * 100))
        self.db.commit()

    # ============================================================
    # 四、笔录台账检索（6.1）
    # ============================================================
    def list_sessions(
        self,
        scope: DataScope,
        *,
        keyword: str | None = None,
        stage: Stage | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SessionListItem], int]:
        """笔录台账复合多条件检索（6.1 检索区 + 状态筛选 + 分页）。

        数据权限（DR-2/DR-3）：
        - 办案民警：本机构范围内自己创建的笔录；
        - 反诈研判员/管理员：机构范围内全部笔录。

        :param keyword: 关键字（案件编号/案情/报案人）
        :param stage: 状态筛选（未问询/问询中/已问询 → 阶段）
        """
        stmt = (
            select(RecordSession)
            .options(
                selectinload(RecordSession.case).selectinload(Case.reporter),
            )
        )
        # 机构数据范围过滤（DR-2/DR-3：org_path 前缀匹配）
        if not scope.is_admin:
            stmt = stmt.where(RecordSession.creator_org_path.like(f"{scope.org_path_prefix}%"))
            # 办案民警仅可见自己创建的笔录（DR-2）
            if scope.is_officer:
                stmt = stmt.where(RecordSession.creator_no == scope.user.officer_no)

        # 状态筛选
        if stage:
            stmt = stmt.where(RecordSession.stage == stage.value)

        # 关键字检索（案件编号/案情/报案人）
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.join(Case, Case.id == RecordSession.case_id).outerjoin(
                Reporter, Reporter.case_id == Case.id
            ).where(
                or_(
                    Case.case_no.like(like),
                    Case.brief.like(like),
                    Reporter.name.like(like),
                )
            )

        # 统计总数（在分页前）
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.execute(count_stmt).scalar() or 0

        # 排序 + 分页
        stmt = stmt.order_by(RecordSession.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        sessions = self.db.execute(stmt).scalars().unique().all()

        # 组装列表项
        items: list[SessionListItem] = []
        for s in sessions:
            case = s.case
            creator_name = self._get_user_name(s.creator_no)
            items.append(SessionListItem(
                id=s.id,
                case_no=case.case_no if case else "",
                case_category=case.case_category if case else "",
                brief=case.brief if case else "",
                reporter_name=case.reporter.name if (case and case.reporter) else None,
                creator_no=s.creator_no,
                creator_name=creator_name,
                stage=Stage(s.stage),
                progress=s.progress,
                updated_at=s.updated_at,
            ))
        return items, total

    def get_statistics(self, scope: DataScope) -> dict:
        """笔录统计计数（6.1 顶部统计区：总数/各状态数）。"""
        base = select(func.count()).select_from(RecordSession)
        if not scope.is_admin:
            base = base.where(RecordSession.creator_org_path.like(f"{scope.org_path_prefix}%"))
            if scope.is_officer:
                base = base.where(RecordSession.creator_no == scope.user.officer_no)
        total = self.db.execute(base).scalar() or 0

        stats = {"total": total}
        for stage in Stage:
            stmt = base.where(RecordSession.stage == stage.value)
            stats[stage.value] = self.db.execute(stmt).scalar() or 0
        return stats

    def _get_user_name(self, officer_no: str) -> str | None:
        """按警号查询姓名（用于列表展示办案民警姓名）。"""
        user = self.db.execute(select(User).where(User.officer_no == officer_no)).scalar_one_or_none()
        return user.name if user else None

    # ============================================================
    # 内部工具：查询与权限校验
    # ============================================================
    def _get_session(self, session_id: str) -> RecordSession:
        """获取会话（含已选模板）。"""
        session = self.db.execute(
            select(RecordSession)
            .options(selectinload(RecordSession.selected_templates))
            .where(RecordSession.id == session_id)
        ).scalar_one_or_none()
        if session is None:
            raise NotFoundError("笔录会话不存在")
        return session

    def _get_session_with_case(self, session_id: str) -> RecordSession:
        """获取会话（含案件与报案人）。"""
        session = self.db.execute(
            select(RecordSession)
            .options(
                selectinload(RecordSession.case).selectinload(Case.reporter),
                selectinload(RecordSession.selected_templates),
            )
            .where(RecordSession.id == session_id)
        ).scalar_one_or_none()
        if session is None:
            raise NotFoundError("笔录会话不存在")
        return session

    def _assert_read_access(self, session: RecordSession, user: User, request: Request | None = None) -> None:
        """校验读取权限（DR-4：越权拦截返回 403 并记录审计）。"""
        # 管理员全量可读
        if user.role_enum == Role.SYSTEM_ADMIN:
            return
        # 机构范围校验（DR-3：org_path 前缀匹配）
        if not session.creator_org_path.startswith(user.org.org_path if user.org else ""):
            self.audit.log_permission_denied(
                officer_no=user.officer_no, request=request,
                resource=f"session:{session.id}", reason="超出机构数据范围（读取）",
            )
            raise ForbiddenError("无权访问该笔录（超出机构数据范围）")
        # 办案民警仅可见自己创建的（DR-2）
        if user.role_enum == Role.CASE_OFFICER and session.creator_no != user.officer_no:
            self.audit.log_permission_denied(
                officer_no=user.officer_no, request=request,
                resource=f"session:{session.id}", reason="非本人创建的笔录（读取）",
            )
            raise ForbiddenError("无权访问该笔录（仅可见本人创建的笔录）")

    def _assert_write_access(self, session: RecordSession, user: User, request: Request | None = None) -> None:
        """校验写入权限（仅办案民警且为本人创建，反诈研判员只读）。"""
        # 反诈研判员与管理员不可编辑正式问答（2.2 权限矩阵）
        if user.role_enum != Role.CASE_OFFICER:
            self.audit.log_permission_denied(
                officer_no=user.officer_no, request=request,
                resource=f"session:{session.id}", reason="非办案民警无编辑权（写入）",
            )
            raise ForbiddenError("仅办案民警可编辑笔录")
        if session.creator_no != user.officer_no:
            self.audit.log_permission_denied(
                officer_no=user.officer_no, request=request,
                resource=f"session:{session.id}", reason="非本人创建的笔录（写入）",
            )
            raise ForbiddenError("无权编辑他人创建的笔录")
