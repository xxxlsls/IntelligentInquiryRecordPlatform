"""
模板配置服务（BE-4）

实现需求文档 FR-3.3.1 19 类电诈模板库与通用模板管理：
- 模板元数据 CRUD；
- 问题集与信号词维护；
- 启用/停用控制；
- 变更实时生效供推荐与问询调用；
- 多模板大纲装配（FR-3.3.3：合并问题集、章节归类去重）。

异常与边界：
- 停用模板不出现在推荐结果；
- 删除模板需校验是否被进行中会话引用（引用中不可删，仅可停用）。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import (
    CHAPTER_LABEL,
    CHAPTER_ORDER,
    AuditOpType,
    Chapter,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.record import RecordSession, SessionTemplate
from app.models.template import Template, TemplateQuestion, TemplateSignalWord
from app.models.user import User
from app.schemas.template import TemplateCreate, TemplateUpdate
from app.services.audit_service import AuditService


class TemplateService:
    """模板配置服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    # ============================================================
    # 查询
    # ============================================================
    def get_template(self, template_id: str) -> Template:
        """获取模板详情（含问题集与信号词， eagerly loaded）。"""
        template = self.db.execute(
            select(Template)
            .options(selectinload(Template.questions), selectinload(Template.signal_words))
            .where(Template.id == template_id)
        ).scalar_one_or_none()
        if template is None:
            raise NotFoundError("模板不存在")
        return template

    def list_templates(self, *, only_enabled: bool = False, keyword: str | None = None) -> list[Template]:
        """列出模板（供管理员维护 / 全量库检索兜底）。

        :param only_enabled: 仅返回启用模板（推荐时使用，停用模板不出现在推荐结果）
        :param keyword: 名称/案由模糊检索关键字（6.3 全量模板库检索）
        """
        stmt = select(Template).options(selectinload(Template.signal_words))
        if only_enabled:
            stmt = stmt.where(Template.is_enabled.is_(True))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where((Template.name.like(like)) | (Template.category.like(like)))
        stmt = stmt.order_by(Template.sort_order, Template.code)
        return list(self.db.execute(stmt).scalars().all())

    def get_general_template(self) -> Template | None:
        """获取通用兜底模板（12.1：通用询问模板作为兜底）。"""
        return self.db.execute(
            select(Template).where(Template.is_general.is_(True), Template.is_enabled.is_(True))
        ).scalars().first()

    # ============================================================
    # 增删改（管理员，FR-3.3.1）
    # ============================================================
    def create_template(self, data: TemplateCreate, operator: User, request=None) -> Template:
        """新增模板（含问题集与信号词）。模板编码唯一性校验。"""
        exists = self.db.execute(select(Template).where(Template.code == data.code)).scalar_one_or_none()
        if exists:
            raise ConflictError(f"模板编码 {data.code} 已存在")

        template = Template(
            name=data.name,
            code=data.code,
            category=data.category,
            description=data.description,
            is_general=data.is_general,
            is_enabled=data.is_enabled,
            sort_order=data.sort_order,
        )
        # 关联问题集
        for q in data.questions:
            template.questions.append(
                TemplateQuestion(
                    chapter=q.chapter.value,
                    question=q.question,
                    sort_order=q.sort_order,
                    target_elements=q.target_elements,
                )
            )
        # 关联信号词
        for w in data.signal_words:
            template.signal_words.append(TemplateSignalWord(word=w.word, weight=w.weight))

        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)

        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"新增模板 {template.name}({template.code})",
            detail={"action": "create_template", "template_id": template.id},
        )
        return template

    def update_template(self, template_id: str, data: TemplateUpdate, operator: User, request=None) -> Template:
        """更新模板元数据（编码/案由不可改）。"""
        template = self.db.get(Template, template_id)
        if template is None:
            raise NotFoundError("模板不存在")

        if data.name is not None:
            template.name = data.name
        if data.description is not None:
            template.description = data.description
        if data.is_general is not None:
            template.is_general = data.is_general
        if data.is_enabled is not None:
            template.is_enabled = data.is_enabled
        if data.sort_order is not None:
            template.sort_order = data.sort_order

        self.db.commit()
        self.db.refresh(template)
        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"更新模板 {template.name}({template.code})",
            detail={"action": "update_template", "template_id": template.id},
        )
        return template

    def delete_template(self, template_id: str, operator: User, request=None) -> None:
        """删除模板（FR-3.3.1 异常与边界：被进行中会话引用不可删，仅可停用）。"""
        template = self.db.get(Template, template_id)
        if template is None:
            raise NotFoundError("模板不存在")

        # 校验是否被进行中（非归档）会话引用
        ref_count = self.db.execute(
            select(SessionTemplate.session_id)
            .join(RecordSession, RecordSession.id == SessionTemplate.session_id)
            .where(SessionTemplate.template_id == template_id, RecordSession.is_archived.is_(False))
        ).all()
        if ref_count:
            raise ConflictError("该模板被进行中的笔录会话引用，不可删除，请改为停用")

        self.db.delete(template)
        self.db.commit()
        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"删除模板 {template.name}({template.code})",
            detail={"action": "delete_template", "template_id": template_id},
        )

    # ============================================================
    # 问题集与信号词维护（FR-3.3.1）
    # ============================================================
    def add_question(self, template_id: str, chapter: Chapter, question: str,
                     sort_order: int = 0, target_elements: str | None = None) -> TemplateQuestion:
        """为模板新增标准问题。"""
        template = self.db.get(Template, template_id)
        if template is None:
            raise NotFoundError("模板不存在")
        tq = TemplateQuestion(
            template_id=template_id, chapter=chapter.value, question=question,
            sort_order=sort_order, target_elements=target_elements,
        )
        self.db.add(tq)
        self.db.commit()
        self.db.refresh(tq)
        return tq

    def delete_question(self, question_id: str) -> None:
        """删除模板标准问题。"""
        tq = self.db.get(TemplateQuestion, question_id)
        if tq is None:
            raise NotFoundError("模板问题不存在")
        self.db.delete(tq)
        self.db.commit()

    # ============================================================
    # 多模板大纲装配（FR-3.3.3）
    # ============================================================
    def assemble_outline(self, template_ids: list[str]) -> list[dict]:
        """合并多模板问题集并装配问询大纲（FR-3.3.3 处理逻辑）。

        步骤：
        1) 多选模板问题集合并；
        2) 按标准大纲章节（固定开头、接触引流、被骗经过、资金损失、证据补充）归类去重；
        3) 章节冲突按标准章节顺序归并；重复问题保留首次。

        :param template_ids: 选中的模板ID集合（≥1）
        :return: 装配后的大纲，形如
                 [{"chapter": "fixed_opening", "chapter_label": "固定开头",
                   "questions": [{"question":..., "target_elements":..., "template_question_id":...}]}]
        :raises ValidationError: 未选模板或模板不存在
        """
        if not template_ids:
            raise ValidationError("请至少选择一个模板")

        # 加载全部选中模板（含问题集）
        templates = self.db.execute(
            select(Template)
            .options(selectinload(Template.questions))
            .where(Template.id.in_(template_ids))
        ).scalars().all()
        if not templates:
            raise NotFoundError("选中的模板均不存在")

        # 按章节归集，使用有序字典保持标准章节顺序
        chapters: dict[Chapter, list[dict]] = {ch: [] for ch in CHAPTER_ORDER}
        seen_questions: set[str] = set()  # 去重：重复问题保留首次（FR-3.3.3 异常与边界）

        for template in templates:
            for q in template.questions:
                try:
                    chapter = Chapter(q.chapter)
                except ValueError:
                    # 未知章节归入证据补充
                    chapter = Chapter.EVIDENCE_SUPPLEMENT
                # 去重键：问题文本标准化
                dedup_key = q.question.strip()
                if dedup_key in seen_questions:
                    continue
                seen_questions.add(dedup_key)
                chapters[chapter].append({
                    "question": q.question,
                    "target_elements": q.target_elements,
                    "template_question_id": q.id,
                })

        # 按标准章节顺序输出（仅保留非空章节，但保持顺序）
        outline = []
        for chapter in CHAPTER_ORDER:
            outline.append({
                "chapter": chapter.value,
                "chapter_label": CHAPTER_LABEL[chapter],
                "questions": chapters[chapter],
            })
        return outline
