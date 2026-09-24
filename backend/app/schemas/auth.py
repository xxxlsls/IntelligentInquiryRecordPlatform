"""
认证与权限相关 Schema（BE-1）

对应需求文档：FR-3.1.1 用户认证登录、FR-3.1.2 角色权限管理、FR-3.1.3 组织机构维护。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import OrgLevel, Role


# ============================================================
# 登录（FR-3.1.1）
# ============================================================
class LoginRequest(BaseModel):
    """登录请求。

    输入项及校验规则（FR-3.1.1）：
    - 账号（警号，必填，格式校验）；
    - 密码（必填，长度≥8）；
    - 验证码（可选，连续失败 3 次后启用）。
    """

    officer_no: str = Field(..., min_length=1, max_length=30, description="警号（登录账号）")
    password: str = Field(..., min_length=8, max_length=72, description="密码（长度≥8，密文传输）")
    captcha: str | None = Field(default=None, description="验证码（连续失败 3 次后必填）")
    captcha_key: str | None = Field(default=None, description="验证码会话标识")

    @field_validator("officer_no")
    @classmethod
    def strip_officer_no(cls, v: str) -> str:
        """去除警号首尾空白，避免误输导致登录失败。"""
        return v.strip()


class UserInfo(BaseModel):
    """登录用户身份信息（含角色、机构与权限清单）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="用户ID")
    officer_no: str = Field(description="警号")
    name: str = Field(description="姓名")
    role: Role = Field(description="角色")
    org_id: str = Field(description="所属机构ID")
    org_name: str | None = Field(default=None, description="所属机构名称")
    org_path: str | None = Field(default=None, description="机构物化路径")
    permissions: list[str] = Field(default_factory=list, description="权限项清单（FR-3.1.2）")


class LoginResponse(BaseModel):
    """登录成功响应（SE-1：签发会话凭证 + 用户身份）。"""

    access_token: str = Field(description="JWT 会话凭证")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="过期时长（秒）")
    user: UserInfo = Field(description="用户身份信息")


class CaptchaResponse(BaseModel):
    """验证码响应（连续失败达阈值后返回）。"""

    captcha_key: str = Field(description="验证码会话标识")
    captcha_image: str = Field(description="验证码图片（Base64 Data URL）")


# ============================================================
# 组织机构维护（FR-3.1.3）
# ============================================================
class OrgBase(BaseModel):
    """机构基础字段。"""

    name: str = Field(..., min_length=1, max_length=100, description="机构名称")
    code: str = Field(..., min_length=1, max_length=50, description="机构编码（唯一）")
    level: OrgLevel = Field(..., description="机构层级")
    parent_id: str | None = Field(default=None, description="上级机构ID（顶级为空）")
    sort_order: int = Field(default=0, description="同级排序号")


class OrgCreate(OrgBase):
    """新增机构请求。"""


class OrgUpdate(BaseModel):
    """更新机构请求（编码不可改，仅可改名称/上级/排序）。"""

    name: str | None = Field(default=None, max_length=100, description="机构名称")
    parent_id: str | None = Field(default=None, description="上级机构ID")
    sort_order: int | None = Field(default=None, description="排序号")


class OrgOut(OrgBase):
    """机构输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="机构ID")
    org_path: str = Field(description="机构物化路径")
    created_at: datetime = Field(description="创建时间")


class OrgTreeNode(BaseModel):
    """机构树节点（用于 FR-3.1.3 树形展示）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    level: OrgLevel
    parent_id: str | None = None
    children: list["OrgTreeNode"] = Field(default_factory=list, description="下级机构")


OrgTreeNode.model_rebuild()


# ============================================================
# 警员账号维护（FR-3.1.3）
# ============================================================
class UserCreate(BaseModel):
    """新增警员请求。

    校验规则（FR-3.1.3）：姓名、警号（唯一）、所属机构、角色、状态。
    """

    officer_no: str = Field(..., min_length=1, max_length=30, description="警号（唯一）")
    name: str = Field(..., min_length=1, max_length=50, description="姓名")
    password: str = Field(..., min_length=8, max_length=72, description="初始密码（长度≥8）")
    role: Role = Field(..., description="角色")
    org_id: str = Field(..., description="所属机构ID")
    phone: str | None = Field(default=None, max_length=20, description="联系电话")
    is_active: bool = Field(default=True, description="账号状态")


class UserUpdate(BaseModel):
    """更新警员请求（警号不可改）。"""

    name: str | None = Field(default=None, max_length=50, description="姓名")
    role: Role | None = Field(default=None, description="角色")
    org_id: str | None = Field(default=None, description="所属机构ID")
    phone: str | None = Field(default=None, max_length=20, description="联系电话")
    is_active: bool | None = Field(default=None, description="账号状态")
    password: str | None = Field(default=None, min_length=8, max_length=72, description="重置密码")


class UserOut(BaseModel):
    """警员输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    officer_no: str
    name: str
    role: Role
    org_id: str
    org_name: str | None = None
    phone: str | None = None
    is_active: bool
    is_locked: bool = Field(default=False, description="是否处于锁定状态")
    last_login_at: datetime | None = None
    created_at: datetime
