"""
全局枚举与常量定义

本模块集中定义智能问询笔录平台的所有领域枚举，作为跨层（models/schemas/services/api）
的统一契约。所有枚举值均严格对应需求文档中的术语与标识，避免"魔法字符串"散落各处。

对应需求文档：
- 1.4 术语与缩略语表（四阶段、五流等）
- 2.1 角色定义（办案民警/反诈研判员/系统管理员）
- 5.1 五流各要素明细表
- 7.2 关键实体字段表（stage/chapter/source/status 枚举）
- 8.4 操作审计流水记录字段（op_type 枚举）
"""

from enum import Enum


# ============================================================
# 一、笔录会话四阶段（对应 1.4 术语表 / 4.5 断点续问 / 7.2.1 DE-1）
# ============================================================
class Stage(str, Enum):
    """笔录任务生命周期阶段标识。

    持久化保存于 RecordSession.stage，"继续询问"时据此精准恢复现场（BP-5）。
    """

    INTAKE = "intake"          # 接报录入：恢复接报录入模态框与已录表单
    TEMPLATES = "templates"    # 模板选择：恢复推荐结果与已勾选模板
    INQUIRY = "inquiry"        # 问询进行中：恢复三栏工作台（问答/五流/材料/AI建议）
    COMPLETED = "completed"    # 已完成问询：恢复笔录预览页与导出入口

    @classmethod
    def ordered(cls) -> list["Stage"]:
        """返回阶段的有序推进顺序，用于状态流转合法性校验。"""
        return [cls.INTAKE, cls.TEMPLATES, cls.INQUIRY, cls.COMPLETED]

    def next_stage(self) -> "Stage | None":
        """返回当前阶段的下一个合法阶段；若已是终态则返回 None。"""
        order = self.ordered()
        idx = order.index(self)
        return order[idx + 1] if idx + 1 < len(order) else None

    def can_transit_to(self, target: "Stage") -> bool:
        """判断能否从当前阶段流转到目标阶段。

        规则（对应 4.5 状态机图 / 7.4 状态机）：
        - 允许向前推进一个阶段（intake→templates→inquiry→completed）；
        - 允许停留在当前阶段（暂存/继续询问自环）。
        """
        if target == self:
            return True
        return self.next_stage() == target


# ============================================================
# 二、用户角色（对应 2.1 角色定义 / 2.2 权限矩阵）
# ============================================================
class Role(str, Enum):
    """系统三类内置角色。禁止删除（FR-3.1.2 异常与边界）。"""

    CASE_OFFICER = "case_officer"        # 办案民警：笔录制作主要执行者
    ANTI_FRAUD_ANALYST = "analyst"       # 反诈研判员：笔录质量与线索完整度审查者（只读为主）
    SYSTEM_ADMIN = "admin"               # 系统管理员：账号/组织/模板/审计运维者


# ============================================================
# 三、功能权限项（对应 2.2 权限矩阵，RBAC 授权粒度）
# ============================================================
class Permission(str, Enum):
    """功能权限项标识，采用 `资源:操作` 命名规范。

    前端按权限渲染菜单/按钮，后端接口二次校验（FR-3.1.2 双重防护）。
    """

    # 笔录台账
    RECORD_LIST_VIEW = "record:list:view"          # 查看笔录台账
    # 接报建档
    RECORD_CREATE = "record:create"                # 新增笔录/接报录入
    EXTERNAL_SYNC = "record:external:sync"         # 外部系统一键同步检索
    # 模板
    TEMPLATE_SELECT = "template:select"            # 选定/组合问询模板
    TEMPLATE_MANAGE = "template:manage"            # 配置模板库/标准问题库
    TEMPLATE_VIEW = "template:view"                # 查看模板库（只读）
    # 三栏工作台
    INQUIRY_EDIT = "inquiry:edit"                  # 执行问询（编辑问答）
    AI_ADOPT = "inquiry:ai:adopt"                  # 采纳 AI 推荐问题
    INQUIRY_REVIEW = "inquiry:review"              # 查看解析结果（只读）
    INQUIRY_ANNOTATE = "inquiry:annotate"          # 指导补充问询（批注建议）
    # 五流与材料
    FIVEFLOW_VIEW = "fiveflow:view"                # 查看五流覆盖度与解析结果
    MATERIAL_UPLOAD = "material:upload"            # 上传辅助材料
    MATERIAL_VIEW = "material:view"                # 查看辅助材料（只读）
    # 文书
    DOCUMENT_EXPORT = "document:export"            # 生成/导出 DOCX 笔录
    DOCUMENT_PREVIEW = "document:preview"          # 红头笔录在线预览
    # 历史笔录
    RECORD_IMPORT = "record:import"                # 导入历史笔录
    # 系统管理
    USER_MANAGE = "system:user:manage"             # 维护警员账号/警号/机构
    ORG_MANAGE = "system:org:manage"               # 维护组织机构
    AI_CONFIG = "system:ai:config"                 # 配置 AI 模型参数
    # 审计
    AUDIT_VIEW_SELF = "audit:view:self"            # 查看本人审计
    AUDIT_VIEW_ORG = "audit:view:org"              # 查看本机构审计
    AUDIT_VIEW_ALL = "audit:view:all"              # 查看全量审计


# 角色 → 权限清单映射（对应 2.2 权限矩阵的"操作"项）
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.CASE_OFFICER: {
        Permission.RECORD_LIST_VIEW,
        Permission.RECORD_CREATE,
        Permission.EXTERNAL_SYNC,
        Permission.TEMPLATE_SELECT,
        Permission.INQUIRY_EDIT,
        Permission.AI_ADOPT,
        Permission.FIVEFLOW_VIEW,
        Permission.MATERIAL_UPLOAD,
        Permission.MATERIAL_VIEW,
        Permission.DOCUMENT_EXPORT,
        Permission.DOCUMENT_PREVIEW,
        Permission.RECORD_IMPORT,
        Permission.AUDIT_VIEW_SELF,
    },
    Role.ANTI_FRAUD_ANALYST: {
        Permission.RECORD_LIST_VIEW,
        Permission.INQUIRY_REVIEW,
        Permission.INQUIRY_ANNOTATE,
        Permission.FIVEFLOW_VIEW,
        Permission.MATERIAL_VIEW,
        Permission.TEMPLATE_VIEW,
        Permission.DOCUMENT_PREVIEW,
        Permission.AUDIT_VIEW_ORG,
    },
    Role.SYSTEM_ADMIN: {
        Permission.RECORD_LIST_VIEW,
        Permission.TEMPLATE_MANAGE,
        Permission.TEMPLATE_VIEW,
        Permission.FIVEFLOW_VIEW,
        Permission.USER_MANAGE,
        Permission.ORG_MANAGE,
        Permission.AI_CONFIG,
        Permission.AUDIT_VIEW_ALL,
    },
}


# ============================================================
# 四、组织机构层级（对应 2.3.1 组织机构模型）
# ============================================================
class OrgLevel(str, Enum):
    """市局 → 分局 → 所队 三级组织架构。"""

    CITY_BUREAU = "city_bureau"    # 市局：顶级机构，可授权查看下辖全部数据
    SUB_BUREAU = "sub_bureau"      # 分局：中间机构，可查看本分局及下辖所队
    STATION = "station"            # 所队：基层机构，仅本所队数据


# ============================================================
# 五、五流类型（对应 1.4 术语表 / 5.1 五流各要素明细表）
# ============================================================
class FlowType(str, Enum):
    """五流：人员流、通信流、网络流、资金流、寄递流。"""

    PERSON = "person"              # 人员流
    COMMUNICATION = "communication"  # 通信流
    NETWORK = "network"            # 网络流
    FUND = "fund"                  # 资金流
    DELIVERY = "delivery"          # 寄递流


# 五流类型中文显示名（用于右栏卡片标题与文书导出）
FLOW_TYPE_LABEL: dict[FlowType, str] = {
    FlowType.PERSON: "人员流",
    FlowType.COMMUNICATION: "通信流",
    FlowType.NETWORK: "网络流",
    FlowType.FUND: "资金流",
    FlowType.DELIVERY: "寄递流",
}


# ============================================================
# 六、五流要素状态（对应 5.3 覆盖度计算与状态判定规则）
# ============================================================
class ElementStatus(str, Enum):
    """五流要素/流的四状态标识。"""

    COLLECTED = "collected"        # 已收集：Cov = 100%
    NEED_SUPPLEMENT = "need_supplement"  # 需补充：0 < Cov < 100% 且非核心要素缺失
    KEY_GAP = "key_gap"            # 重点缺口：核心要素未满足，最高优先级
    NOT_INVOLVED = "not_involved"  # 不涉及：该流与当前案由无关（N_required=0）


# ============================================================
# 七、问询大纲章节（对应 7.2.2 DE-5 / 6.4 左栏卡片流）
# ============================================================
class Chapter(str, Enum):
    """标准大纲章节，多模板装配时按此顺序归并（FR-3.3.3）。"""

    FIXED_OPENING = "fixed_opening"    # 固定开头
    CONTACT_LURE = "contact_lure"      # 接触引流
    FRAUD_PROCESS = "fraud_process"    # 被骗经过
    FUND_LOSS = "fund_loss"            # 资金损失
    EVIDENCE_SUPPLEMENT = "evidence_supplement"  # 证据补充


# 章节中文显示名与标准排序（用于文书排版与卡片流顺序）
CHAPTER_LABEL: dict[Chapter, str] = {
    Chapter.FIXED_OPENING: "固定开头",
    Chapter.CONTACT_LURE: "接触引流",
    Chapter.FRAUD_PROCESS: "被骗经过",
    Chapter.FUND_LOSS: "资金损失",
    Chapter.EVIDENCE_SUPPLEMENT: "证据补充",
}

# 章节标准顺序（FR-3.3.3：章节冲突按标准章节顺序归并）
CHAPTER_ORDER: list[Chapter] = [
    Chapter.FIXED_OPENING,
    Chapter.CONTACT_LURE,
    Chapter.FRAUD_PROCESS,
    Chapter.FUND_LOSS,
    Chapter.EVIDENCE_SUPPLEMENT,
]


# ============================================================
# 八、问答项来源标识（对应 7.2.2 DE-5 source 字段）
# ============================================================
class QASource(str, Enum):
    """问答项来源，用于左栏来源标记与审计追溯。"""

    TEMPLATE = "template"      # 模板预置
    AI_RECOMMEND = "ai_recommend"  # AI 推荐（采纳后转正式问答）
    MANUAL = "manual"          # 手动新增


# ============================================================
# 九、审计操作类型（对应 2.4.2 / 8.4 op_type）
# ============================================================
class AuditOpType(str, Enum):
    """敏感操作审计类型。审计日志只增不删不改（NFR-S5/NFR-C3）。"""

    LOGIN = "login"                    # 登录
    LOGOUT = "logout"                  # 登出
    CASE_ACCESS = "case_access"        # 案件访问
    EXTERNAL_SYNC = "external_sync"    # 外部系统同步
    QA_MODIFY = "qa_modify"            # 问答修改（含变更前后指纹）
    AI_ADOPT = "ai_adopt"              # 采纳 AI 建议
    MATERIAL_UPLOAD = "material_upload"  # 上传材料
    DOCUMENT_EXPORT = "document_export"  # 文书导出
    PERMISSION_DENIED = "permission_denied"  # 越权拦截
    CONFIG_CHANGE = "config_change"    # 配置变更（模板/AI参数/账号机构）
    RECORD_CREATE = "record_create"    # 创建笔录
    STAGE_CHANGE = "stage_change"      # 阶段流转
    RECORD_IMPORT = "record_import"    # 历史笔录导入


# ============================================================
# 十、AI 建议类型（对应 10 DE-10 / FR-3.4.2）
# ============================================================
class SuggestionType(str, Enum):
    """中栏 AI 侦查研判建议类型。"""

    CASE_TYPE_JUDGE = "case_type_judge"    # 涉诈类型判定
    INVESTIGATION_GUIDE = "investigation_guide"  # 侦查指引建议
    FOLLOWUP_QUESTION = "followup_question"      # 推荐补充问题
    KEY_GAP_QUESTION = "key_gap_question"        # 重点缺口追问（置顶）


# ============================================================
# 十一、外部系统来源（对应 1.4 术语表 / BE-3）
# ============================================================
class ExternalSource(str, Enum):
    """外部业务系统标识，仅提供只读检索（OOS-1：严禁回写）。"""

    ZHIYANPAN = "zhiyanpan"    # 智研判
    ZHIAN_GUAN = "zhianguan"   # 智案管


# ============================================================
# 十二、材料类型白名单（对应 FR-3.4.4 / BE-7）
# ============================================================
class MaterialType(str, Enum):
    """辅助材料类型。材料仅作研判输入，物理隔离于问答正文（IR-1）。"""

    CALL_RECORD = "call_record"      # 通话记录
    TRANSFER_FLOW = "transfer_flow"  # 转账流水
    CHAT_SCREENSHOT = "chat_screenshot"  # 聊天截图
    IMAGE = "image"                  # 图片
    PDF = "pdf"                      # PDF 文档
    DOCUMENT = "document"            # 其他文档


# 允许上传的文件扩展名白名单（可通过配置覆盖）
ALLOWED_FILE_EXTENSIONS: set[str] = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
}
