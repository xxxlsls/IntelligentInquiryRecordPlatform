"""
演示业务数据种子脚本

在基础目录种子（机构/账号/模板/五流要素定义）之外，生成覆盖四阶段的演示笔录会话：
案件 + 报案人 + 会话 + 模板关联 + 问答项 + 五流要素抽取结果 + AI 研判建议，
使工作台首页统计、台账检索、三栏工作台与笔录预览均有真实数据可演示。

采用幂等设计：按演示案件编号前缀（A3201042026 09xxxx）去重，可安全多次调用。

运行方式（backend 目录下）：
    python -m app.seed.seed_demo           # 生成演示数据（幂等）
    python -m app.seed.seed_demo --reset   # 清除旧演示数据后重新生成
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ElementStatus, QASource, SuggestionType
from app.models.case import Case, Reporter
from app.models.fiveflow import FiveFlowElement
from app.models.material import Material
from app.models.record import AiSuggestion, QAItem, RecordSession, SessionTemplate
from app.models.template import Template
from app.models.user import Org, User

logger = logging.getLogger("seed")

# 演示案件编号前缀（幂等去重标识）
DEMO_PREFIX = "A3201042026"


def _answered(qa_items: list[QAItem]) -> int:
    """统计已作答问答数（progress 计算）。"""
    return sum(1 for q in qa_items if q.answer and q.answer.strip())


def reset_demo_sessions(db: Session) -> int:
    """清除演示会话数据（按演示案号前缀，显式清理无级联的关联表后删除会话）。"""
    from sqlalchemy import delete

    session_ids = (
        db.execute(
            select(RecordSession.id).where(
                RecordSession.case_id.in_(select(Case.id).where(Case.case_no.startswith(DEMO_PREFIX)))
            )
        )
        .scalars()
        .all()
    )
    if session_ids:
        # 无 ORM 级联的关联表需显式删除：五流要素/材料/会话-模板关联
        db.execute(delete(FiveFlowElement).where(FiveFlowElement.session_id.in_(session_ids)))
        db.execute(delete(Material).where(Material.session_id.in_(session_ids)))
        db.execute(delete(SessionTemplate).where(SessionTemplate.session_id.in_(session_ids)))
        # 会话删除时由 ORM cascade 同步删除问答/AI建议
        for s in db.execute(select(RecordSession).where(RecordSession.id.in_(session_ids))).scalars().all():
            db.delete(s)
        db.flush()
    # 案件/报案人需显式删除（cascade 方向为 Case→Session，反向不级联）
    case_ids = db.execute(select(Case.id).where(Case.case_no.startswith(DEMO_PREFIX))).scalars().all()
    if case_ids:
        db.execute(delete(Reporter).where(Reporter.case_id.in_(case_ids)))
        db.execute(delete(Case).where(Case.id.in_(case_ids)))
    db.commit()
    logger.info("已清除演示会话 %d 条、案件 %d 条", len(session_ids), len(case_ids))
    return len(session_ids)


def _build_qa_from_template(session: RecordSession, template: Template, answer_map: dict[int, str]) -> list[QAItem]:
    """按模板标准问题集生成问答项（source=template，章节/排序沿用模板定义）。

    :param answer_map: 模板问题 sort_order → 答案文本（缺省表示未作答）
    """
    qa_items: list[QAItem] = []
    for tq in sorted(template.questions, key=lambda q: (q.chapter, q.sort_order)):
        qa_items.append(QAItem(
            session=session,
            chapter=tq.chapter,
            question=tq.question,
            answer=answer_map.get(tq.sort_order),
            source=QASource.TEMPLATE.value,
            sort_order=tq.sort_order,
            template_question_id=tq.id,
        ))
    return qa_items


def seed_demo_sessions(db: Session) -> dict:
    """生成演示会话数据（幂等）。返回各类新增数量统计。"""
    # 幂等：已存在演示案号则跳过
    existing = db.execute(select(Case.case_no).where(Case.case_no.startswith(DEMO_PREFIX))).scalars().all()
    if existing:
        logger.info("演示会话数据已存在（%d 条案件），跳过生成", len(existing))
        return {"cases": 0, "sessions": 0, "qa_items": 0, "five_flow_elements": 0, "ai_suggestions": 0}

    # 依赖数据：机构 / 民警 / 模板
    org1 = db.execute(select(Org).where(Org.code == "ORG_STATION_01")).scalar_one_or_none()
    org2 = db.execute(select(Org).where(Org.code == "ORG_STATION_02")).scalar_one_or_none()
    officer1 = db.execute(select(User).where(User.officer_no == "P10001")).scalar_one_or_none()
    officer2 = db.execute(select(User).where(User.officer_no == "P10002")).scalar_one_or_none()
    tpl = db.execute(select(Template).where(Template.code == "TPL_01")).scalar_one_or_none()
    if not all([org1, org2, officer1, officer2, tpl]):
        logger.error("依赖种子数据缺失（机构/账号/模板 TPL_01），请先启动应用完成基础种子")
        return {"cases": 0, "sessions": 0, "qa_items": 0, "five_flow_elements": 0, "ai_suggestions": 0}

    now = datetime.now()
    stats = {"cases": 0, "sessions": 0, "qa_items": 0, "five_flow_elements": 0, "ai_suggestions": 0}

    # FiveFlowElement 仅有 session_id 外键（无 relationship），需先 flush 获取会话主键
    db.flush()

    def _make_session(
        case_no: str, category: str, brief: str, reporter_name: str,
        reporter_phone: str, org: Org, officer: User, stage: str,
        report_days_ago: int, with_template: bool,
    ) -> tuple[RecordSession, Case]:
        """构建案件 + 报案人 + 会话（含机构归属与时间回溯）。"""
        report_time = now - timedelta(days=report_days_ago, hours=2)
        case = Case(
            case_no=case_no, case_category=category, brief=brief,
            handling_org=org.name, handling_org_code=org.code,
            report_time=report_time,
            owner_org_id=org.id, owner_org_path=org.org_path,
            creator_no=officer.officer_no,
            created_at=report_time, updated_at=report_time,
        )
        case.reporter = Reporter(
            name=reporter_name, phone=reporter_phone,
            created_at=report_time, updated_at=report_time,
        )
        session = RecordSession(
            case=case, stage=stage,
            creator_org_id=org.id, creator_org_path=org.org_path,
            creator_no=officer.officer_no, progress=0,
            created_at=report_time, updated_at=now - timedelta(days=report_days_ago),
        )
        if with_template:
            session.selected_templates.append(tpl)
        db.add(session)
        db.flush()  # 立即获取会话主键，供五流要素等仅含外键的实体引用
        stats["cases"] += 1
        stats["sessions"] += 1
        return session, case

    # ============================================================
    # 会话 1：已完成问询（刷单返利，全部作答，五流覆盖高）
    # ============================================================
    s1, _ = _make_session(
        case_no=f"{DEMO_PREFIX}090001", category="刷单返利诈骗",
        brief="受害人张某收到'点赞兼职'短信，按指引进群完成小额任务并成功返现，随后被诱导下载 APP 充值做大额任务，"
              "累计转账 5.2 万元后平台无法提现，客服失联，发现被骗报警。",
        reporter_name="张某", reporter_phone="13912345678",
        org=org1, officer=officer1, stage="completed", report_days_ago=2, with_template=True,
    )
    s1.stage_snapshot = json.dumps({"elapsed_seconds": 1860, "saved_at": now.isoformat()})
    # 答案映射：TPL_01 模板问题 sort_order(0~15) → 答案（全部作答，progress=100）
    answers1 = {
        0: "我叫张某，女，1990 年 1 月出生，身份证号 320102199001011234，现住南京市鼓楼区 XX 路 XX 小区 3 栋 502 室，在一家私企做会计。",
        1: "知晓，我愿意如实陈述。",
        2: "不需要回避，也不需要翻译。",
        3: "9 月 24 日下午 3 点左右，我收到一条短信，说给店铺点赞每单酬劳 5 到 10 元，短信里带了一个链接。",
        4: "我点了短信里的链接，跳转后让我填了手机号，随后被拉进一个微信群，群名叫'兼职福利 3 群'，群管理员昵称是'派单员-小美'。",
        5: "点过。按群管理员要求下载了一个叫'汇联商城'的 APP，安装包是群里发的链接，不是应用商店下载的。",
        6: "进群后管理员先让我做 3 个小任务，给指定店铺点赞后截图发群里，每个任务返了 8 元红包，都真实到账了。之后让我在'汇联商城'APP 里做大额任务，说佣金更高。我先后充值了 4 单，最后一单完成后系统提示'操作失误，账户冻结'，要求再充 10 万元解冻，我没有再转，发现被骗就报警了。",
        7: "对方自称是'汇联商城'的兼职派单客服，理由是完成商户充值任务可以赚取佣金返利。",
        8: "没有进行屏幕共享或远程控制，全程是通过微信群和 APP 内客服对话操作的。",
        9: "共 4 笔：9 月 25 日转 3000 元、9 月 25 日转 8000 元、9 月 26 日转 15000 元、9 月 26 日转 26000 元，都是手机银行转账，累计 5.2 万元。",
        10: "我的转出卡是工商银行 6222020200112233445；对方收款账户 6228480012345678901，户名显示'某商贸有限公司'，开户行农业银行。",
        11: "每笔转账回单上都有流水号，我已打印提交；累计损失 5.2 万元。",
        12: "保留了全部转账回单、微信群聊记录截图、与客服的聊天记录和 APP 安装包，都交给民警了。",
        13: "不涉及快递包裹往来。",
        14: "没有了，希望警方尽快止付冻结对方账户，帮我追回损失。",
    }
    qa1 = _build_qa_from_template(s1, tpl, answers1)
    s1.qa_items.extend(qa1)
    s1.progress = round(_answered(qa1) / max(len(qa1), 1) * 100)
    stats["qa_items"] += len(qa1)

    # 五流要素抽取结果（已完成：覆盖度高，寄递流不涉及）
    ff1 = [
        ("person", "P-01", "张某（受害人），女，1990 年生", ElementStatus.COLLECTED, "问答：固定开头-身份信息"),
        ("communication", "C-01", "13912345678（受害人手机号）", ElementStatus.COLLECTED, "问答：固定开头-联系方式"),
        ("communication", "C-03", "'点赞兼职'引流短信 + 微信群", ElementStatus.COLLECTED, "问答：接触引流-短信链接进群"),
        ("network", "N-03", "'汇联商城'APP（安装包已提取）", ElementStatus.COLLECTED, "问答：接触引流-下载 APP"),
        ("fund", "F-01", "累计损失 5.2 万元（4 笔转账）", ElementStatus.COLLECTED, "问答：资金损失-转账明细"),
        ("fund", "F-04", "6228480012345678901（农行，户名某商贸有限公司）", ElementStatus.COLLECTED, "问答：证据补充-收款账户"),
        ("delivery", "D-01", None, ElementStatus.NOT_INVOLVED, "本案无实物寄递环节"),
    ]
    for ft, ec, v, st, es in ff1:
        db.add(FiveFlowElement(session_id=s1.id, flow_type=ft, element_code=ec, value=v, status=st.value, evidence_snippet=es, confidence=0.9))
    stats["five_flow_elements"] += len(ff1)

    db.add(AiSuggestion(
        session=s1, suggestion_type=SuggestionType.CASE_TYPE_JUDGE.value,
        title="刷单返利诈骗", content="以点赞兼职小额返现建立信任，诱导下载 APP 大额充值后以'操作失误'拒返，符合刷单返利诈骗典型手法。",
        basis=json.dumps({"signal_words": ["点赞兼职", "返佣", "操作失误", "解冻金"], "facts": ["小额返现引流", "大额充值无法提现"]}, ensure_ascii=False),
        confidence=0.92, sort_order=1,
    ))
    stats["ai_suggestions"] += 1

    # ============================================================
    # 会话 2：问询进行中（冒充电商客服理赔，部分作答，存在重点缺口）
    # ============================================================
    s2, _ = _make_session(
        case_no=f"{DEMO_PREFIX}090002", category="冒充电商客服诈骗",
        brief="李某接到自称'电商客服'电话，称其购买的化妆品检测不合格可双倍理赔，诱导其开启屏幕共享并'验证流水'，"
              "转账 1.8 万元后对方失联。",
        reporter_name="李某", reporter_phone="18612345678",
        org=org1, officer=officer1, stage="inquiry", report_days_ago=1, with_template=True,
    )
    s2.stage_snapshot = json.dumps({"elapsed_seconds": 720, "saved_at": now.isoformat()})
    # 答案映射：仅回答前 9 题（sort_order 0~8），后续留白 → progress≈56%，体现问询进行中
    answers2 = {
        0: "我叫李某，男，1985 年 5 月出生，身份证号 320102198505055678，住南京市秦淮区 XX 村 XX 号，电话 18612345678。",
        1: "知晓，我如实陈述。",
        2: "不需要。",
        3: "9 月 26 日上午 10 点左右，我接到一个 00852 开头的电话，对方自称是某电商平台客服。",
        4: "对方用的是 00852 开头的网络电话，能准确说出我 9 月中旬购买化妆品的订单信息，之后让我添加了一个 QQ 号继续沟通。",
        5: "没有点链接，但按对方要求下载了一款屏幕共享软件。",
        6: "对方说该批次化妆品检测不合格可以双倍理赔，需要先'验证银行流水'才能放款，让我开启屏幕共享跟着他操作，我按提示分了 4 笔转账共 1.8 万元，转完后对方就失联了。",
        7: "对方自称电商平台客服工号 8823，以'商品理赔'为由让我配合操作。",
        8: "进行了屏幕共享，软件名字我记得叫'云视讯'，对方全程能看到我的手机操作。",
    }
    qa2 = _build_qa_from_template(s2, tpl, answers2)
    s2.qa_items.extend(qa2)
    s2.progress = round(_answered(qa2) / max(len(qa2), 1) * 100)
    stats["qa_items"] += len(qa2)

    # 五流要素（进行中：资金流收款账户为核心缺口，触发重点缺口追问 GR-2）
    ff2 = [
        ("person", "P-01", "李某（受害人），男，1985 年生", ElementStatus.COLLECTED, "问答：固定开头-身份信息"),
        ("communication", "C-01", "00852 开头境外来电（自称客服）", ElementStatus.COLLECTED, "问答：接触引流-来电号码"),
        ("communication", "C-04", "QQ 号（屏幕共享联络账号，待补充）", ElementStatus.NEED_SUPPLEMENT, "问答提及添加 QQ，具体号码未采集"),
        ("network", "N-04", "屏幕共享软件（名称待确认）", ElementStatus.NEED_SUPPLEMENT, "问答：被骗经过-屏幕共享"),
        ("fund", "F-01", "转账 1.8 万元", ElementStatus.COLLECTED, "问答：资金损失-转账金额"),
        ("fund", "F-04", None, ElementStatus.KEY_GAP, "收款账户/卡号尚未采集（核心要素缺失）"),
    ]
    for ft, ec, v, st, es in ff2:
        db.add(FiveFlowElement(session_id=s2.id, flow_type=ft, element_code=ec, value=v, status=st.value, evidence_snippet=es, confidence=0.8))
    stats["five_flow_elements"] += len(ff2)

    db.add_all([
        AiSuggestion(
            session=s2, suggestion_type=SuggestionType.CASE_TYPE_JUDGE.value,
            title="冒充电商客服诈骗", content="冒充客服以'商品理赔'为名，利用屏幕共享诱导转账，符合冒充电商客服诈骗特征。",
            basis=json.dumps({"signal_words": ["双倍理赔", "屏幕共享", "验证流水"], "facts": ["准确报出订单信息", "境外来电"]}, ensure_ascii=False),
            confidence=0.88, sort_order=1,
        ),
        AiSuggestion(
            session=s2, suggestion_type=SuggestionType.KEY_GAP_QUESTION.value,
            title="重点缺口：收款账户", content="请提供对方收款账户的完整卡号、户名和开户行，以及每笔转账的具体时间和金额。",
            target_chapter="fund_loss", target_element_code="F-04",
            is_pinned=True, confidence=0.9, sort_order=2,
        ),
        AiSuggestion(
            session=s2, suggestion_type=SuggestionType.FOLLOWUP_QUESTION.value,
            title=None, content="对方使用的屏幕共享软件叫什么名字？是否记得 QQ 号？",
            target_chapter="fraud_process", sort_order=3,
        ),
        AiSuggestion(
            session=s2, suggestion_type=SuggestionType.INVESTIGATION_GUIDE.value,
            title="侦查指引", content="建议紧急止付收款账户，调取 QQ 账号注册信息与屏幕共享软件落地 IP，串并同类 00852 号段警情。",
            confidence=0.8, sort_order=4,
        ),
    ])
    stats["ai_suggestions"] += 4

    # ============================================================
    # 会话 3：模板选择阶段（已建档，待选定模板）
    # ============================================================
    s3, _ = _make_session(
        case_no=f"{DEMO_PREFIX}090003", category="冒充公检法诈骗",
        brief="王某接到自称'上海市公安局'电话，称其名下银行卡涉嫌洗钱案件，要求配合调查并将资金转入'安全账户'，"
              "王某起疑后挂断电话并报警。",
        reporter_name="王某", reporter_phone="13812345679",
        org=org2, officer=officer2, stage="templates", report_days_ago=1, with_template=False,
    )
    s3.progress = 0

    # ============================================================
    # 会话 4：接报录入草稿（仅案件信息，未进入模板选择）
    # ============================================================
    s4, _ = _make_session(
        case_no=f"{DEMO_PREFIX}090004", category="虚假投资理财诈骗",
        brief="赵某被网友拉入'股票交流群'，群内'老师'推荐在某平台购买虚拟货币理财，充值 3 万元后平台无法提现。",
        reporter_name="赵某", reporter_phone="13712345680",
        org=org1, officer=officer1, stage="intake", report_days_ago=0, with_template=False,
    )
    s4.progress = 0

    # ============================================================
    # 会话 5：已完成并归档（杀猪盘，供台账下载/回溯演示）
    # ============================================================
    s5, _ = _make_session(
        case_no=f"{DEMO_PREFIX}090005", category="网络交友诈骗",
        brief="周某在婚恋网站结识'刘某'，对方以'内部渠道稳赚'诱导其在虚假平台投资，先后充值 12 万元，"
              "提现失败且对方失联后报警。",
        reporter_name="周某", reporter_phone="13612345681",
        org=org1, officer=officer1, stage="completed", report_days_ago=5, with_template=True,
    )
    s5.is_archived = True
    s5.stage_snapshot = json.dumps({"elapsed_seconds": 2400, "saved_at": now.isoformat()})
    # 答案映射：全部作答（progress=100，已归档）
    answers5 = {
        0: "我叫周某，男，1992 年 2 月出生，身份证号 320102199202023456，住南京市建邺区 XX 花园 XX 栋，电话 13612345681。",
        1: "知晓，我愿意如实陈述。",
        2: "不需要回避和翻译。",
        3: "8 月底我在某婚恋网站上认识了自称'刘某'的人，是对方先给我发的消息。",
        4: "通过婚恋网站的站内信和后来加的微信联系，对方微信号是 liu_invest888，昵称'刘某-资深操盘手'。",
        5: "点过对方发的链接，注册了一个投资平台，没有下载 APP，是在网页上操作的。",
        6: "聊了两周后确定恋爱关系，'刘某'说他有某投资平台的内部渠道稳赚不赔，让我注册他发的链接。我先投了 1 万元，一周后账户显示赚了 2000 元并成功提现。之后他劝我加大投入，我分 3 次共充值 12 万元。9 月中旬想提现时系统提示需缴纳 20% 保证金，我察觉不对没再转，随后平台打不开、'刘某'也把我拉黑了。",
        7: "对方自称是证券公司资深操盘手，以'内部渠道稳赚不赔'为由让我投资。",
        8: "没有屏幕共享或远程控制，都是通过微信语音沟通。",
        9: "共 4 笔：8 月底 1 万元，9 月初 3 万元、4 万元，9 月中 5 万元，都是银行卡转账，累计充值 12 万元（含首次 1 万元）。",
        10: "我的转出卡是建设银行 6217001210012345678；对方收款是平台提供的 3 个不同个人账户，卡号和户名我都在转账记录里截图保存了。",
        11: "转账流水号已在银行打印提交；累计损失 12 万元。",
        12: "保留了转账记录、平台账户截图、全部微信聊天记录和对方微信号，平台网址也还在手机里。",
        13: "不涉及快递往来。",
        14: "希望警方尽快冻结那几个收款账户，我不想让其他人再上当。",
    }
    qa5 = _build_qa_from_template(s5, tpl, answers5)
    s5.qa_items.extend(qa5)
    s5.progress = round(_answered(qa5) / max(len(qa5), 1) * 100)
    stats["qa_items"] += len(qa5)

    ff5 = [
        ("person", "P-01", "周某（受害人），男，1992 年生", ElementStatus.COLLECTED, "问答：固定开头-身份信息"),
        ("person", "P-03", "'刘某'（婚恋网站虚假身份）", ElementStatus.NEED_SUPPLEMENT, "真实身份待核查"),
        ("communication", "C-01", "13612345681（受害人手机号）", ElementStatus.COLLECTED, "问答：固定开头-联系方式"),
        ("network", "N-01", "某婚恋网站（引流渠道）", ElementStatus.COLLECTED, "问答：接触引流-婚恋网站"),
        ("network", "N-03", "虚假投资平台（链接已提取）", ElementStatus.COLLECTED, "问答：被骗经过-平台链接"),
        ("fund", "F-01", "累计充值 12 万元（4 笔）", ElementStatus.COLLECTED, "问答：资金损失-充值明细"),
        ("fund", "F-04", "3 个个人账户收款（卡号已登记）", ElementStatus.COLLECTED, "问答：证据补充-转账记录"),
    ]
    for ft, ec, v, st, es in ff5:
        db.add(FiveFlowElement(session_id=s5.id, flow_type=ft, element_code=ec, value=v, status=st.value, evidence_snippet=es, confidence=0.85))
    stats["five_flow_elements"] += len(ff5)

    db.add(AiSuggestion(
        session=s5, suggestion_type=SuggestionType.CASE_TYPE_JUDGE.value,
        title="网络交友诈骗（杀猪盘）", content="婚恋网站建立恋爱关系后诱导虚假平台投资，符合'杀猪盘'典型链路：寻猪-养猪-杀猪。",
        basis=json.dumps({"signal_words": ["婚恋网站", "内部渠道", "稳赚不赔", "保证金"], "facts": ["小额提现建立信任", "大额充值后失联"]}, ensure_ascii=False),
        confidence=0.95, sort_order=1,
    ))
    stats["ai_suggestions"] += 1

    db.commit()
    logger.info("演示会话数据生成完成：%s", stats)
    return stats


if __name__ == "__main__":
    import sys

    from app.core.database import SessionLocal

    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        if "--reset" in sys.argv:
            reset_demo_sessions(db)
        result = seed_demo_sessions(db)
        print("演示数据生成完成:", result)
    finally:
        db.close()
