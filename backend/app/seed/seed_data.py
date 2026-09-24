"""
种子数据初始化编排

在应用启动时按需初始化：五流要素定义目录、19 类模板库、组织机构与演示账号。
采用幂等设计：已存在的数据不重复写入，可安全多次调用（NFR-C3 数据一致性）。
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.fiveflow import FlowElementDefinition
from app.models.template import Template, TemplateQuestion, TemplateSignalWord
from app.models.user import Org, User
from app.seed.flow_elements import FLOW_ELEMENT_DEFINITIONS
from app.seed.orgs_users import ORGS, USERS
from app.seed.templates_19 import build_templates

logger = logging.getLogger("seed")


def seed_flow_elements(db: Session) -> int:
    """初始化五流要素定义目录（5.1）。返回新增条数。"""
    existing = {
        d.element_code
        for d in db.execute(select(FlowElementDefinition)).scalars().all()
    }
    added = 0
    for flow_type, code, name, field_type, desc, is_core, sort_order in FLOW_ELEMENT_DEFINITIONS:
        if code in existing:
            continue
        db.add(FlowElementDefinition(
            flow_type=flow_type, element_code=code, element_name=name,
            field_type=field_type, description=desc, is_core=is_core, sort_order=sort_order,
        ))
        added += 1
    db.commit()
    return added


def seed_templates(db: Session) -> int:
    """初始化 19 类模板 + 通用模板（FR-3.3.1 / 12.1）。返回新增模板数。"""
    existing_codes = {t.code for t in db.execute(select(Template)).scalars().all()}
    added = 0
    for tpl in build_templates():
        if tpl["code"] in existing_codes:
            continue
        template = Template(
            name=tpl["name"], code=tpl["code"], category=tpl["category"],
            description=tpl["description"], is_general=tpl["is_general"],
            is_enabled=tpl["is_enabled"], sort_order=tpl["sort_order"],
        )
        for q in tpl["questions"]:
            template.questions.append(TemplateQuestion(
                chapter=q["chapter"], question=q["question"],
                sort_order=q["sort_order"], target_elements=q["target_elements"],
            ))
        for w in tpl["signal_words"]:
            template.signal_words.append(TemplateSignalWord(word=w["word"], weight=w["weight"]))
        db.add(template)
        added += 1
    db.commit()
    return added


def seed_orgs(db: Session) -> int:
    """初始化三级组织机构（2.3.1）。返回新增机构数。"""
    existing_codes = {o.code for o in db.execute(select(Org)).scalars().all()}
    # 先建机构（按父编码顺序），需两次遍历以解析 parent_id
    code_to_org: dict[str, Org] = {o.code: o for o in db.execute(select(Org)).scalars().all()}
    added = 0
    for name, code, level, parent_code, sort_order in ORGS:
        if code in existing_codes:
            continue
        parent = code_to_org.get(parent_code) if parent_code else None
        parent_path = parent.org_path if parent else ""
        org = Org(
            name=name, code=code, level=level,
            parent_id=parent.id if parent else None,
            org_path=f"{parent_path}/{code}",
            sort_order=sort_order,
        )
        db.add(org)
        db.flush()  # 获取 id 供后续子机构引用
        code_to_org[code] = org
        added += 1
    db.commit()
    return added


def seed_users(db: Session) -> int:
    """初始化演示账号（三类角色，AC-1）。返回新增用户数。"""
    existing_nos = {u.officer_no for u in db.execute(select(User)).scalars().all()}
    # 机构编码 → 机构对象映射
    code_to_org = {o.code: o for o in db.execute(select(Org)).scalars().all()}
    added = 0
    for officer_no, name, role, org_code, password, phone in USERS:
        if officer_no in existing_nos:
            continue
        org = code_to_org.get(org_code)
        if org is None:
            logger.warning("跳过用户 %s：机构 %s 不存在", officer_no, org_code)
            continue
        db.add(User(
            officer_no=officer_no, name=name, role=role,
            password_hash=hash_password(password),
            org_id=org.id, phone=phone, is_active=True,
        ))
        added += 1
    db.commit()
    return added


def seed_all(db: Session) -> dict:
    """按依赖顺序初始化全部种子数据（幂等）。

    顺序：五流要素 → 机构 → 用户 → 模板（模板不依赖机构/用户）。
    :return: 各类新增数量统计
    """
    stats = {
        "flow_elements": seed_flow_elements(db),
        "orgs": seed_orgs(db),
        "users": seed_users(db),
        "templates": seed_templates(db),
    }
    logger.info("种子数据初始化完成：%s", stats)
    return stats
