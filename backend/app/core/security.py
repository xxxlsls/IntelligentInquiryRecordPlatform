"""
安全工具：密码哈希与 JWT 会话凭证

实现需求文档的安全要求：
- FR-3.1.1 密码加盐哈希比对（bcrypt），密文传输；
- SE-1 登录成功签发 Cookie/Token 会话凭证；
- NFR-S4 会话凭证防篡改（JWT 签名）；
- 8.4 变更指纹（前后值哈希）生成工具。

对应需求文档：FR-3.1.1、FR-3.1.5、SE-1~SE-4、NFR-S4、2.4.2。
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


# ============================================================
# 一、密码哈希（bcrypt 加盐哈希，FR-3.1.1）
# ============================================================
def hash_password(plain_password: str) -> str:
    """对明文密码进行加盐哈希。

    使用 bcrypt 自动生成随机盐并哈希，结果可直接持久化到用户表。
    :param plain_password: 明文密码（长度≥8 由 schema 层校验）
    :return: bcrypt 哈希字符串（形如 $2b$12$...）
    """
    # bcrypt 要求输入为字节串；password 上限 72 字节由业务层约束
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配（FR-3.1.1 处理逻辑步骤 2）。

    :param plain_password: 用户输入的明文密码
    :param hashed_password: 数据库中存储的哈希
    :return: 匹配返回 True，否则 False
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # 哈希格式非法时视为校验失败，不抛异常中断登录流程
        return False


# ============================================================
# 二、JWT 会话凭证（SE-1 / FR-3.1.5）
# ============================================================
def create_access_token(
    subject: str,
    extra_claims: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    """签发 JWT 会话凭证（Access Token）。

    :param subject: 令牌主体，通常为用户警号（officer_no）
    :param extra_claims: 附加声明（如 user_id、role、org_code）
    :param expires_minutes: 过期时长（分钟），默认取配置 SESSION_TIMEOUT_MINUTES
    :return: 编码后的 JWT 字符串
    """
    expire_minutes = expires_minutes or settings.SESSION_TIMEOUT_MINUTES
    now = datetime.now(timezone.utc)
    expire_at = now + timedelta(minutes=expire_minutes)

    payload: dict[str, Any] = {
        "sub": subject,                 # 主体：警号
        "iat": int(now.timestamp()),    # 签发时间
        "exp": int(expire_at.timestamp()),  # 过期时间（SE-3 超时策略）
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码并校验 JWT 会话凭证。

    :param token: JWT 字符串
    :return: 校验通过返回 payload 字典；过期/篡改/非法返回 None（触发 401 重定向，SE-2）
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        # 凭证过期（SE-2：会话失效重定向登录页）
        return None
    except jwt.InvalidTokenError:
        # 凭证被篡改或格式非法（NFR-S4 防篡改）
        return None


# ============================================================
# 三、变更指纹（8.4 change_fingerprint / FR-3.1.4）
# ============================================================
def compute_fingerprint(*values: Any) -> str:
    """计算变更指纹：对前后值序列化后取 SHA-256 哈希。

    用于审计日志记录问答修改、文书导出等操作的变更留痕（2.4.2）。
    :param values: 任意数量的值（如变更前值、变更后值）
    :return: 16 进制哈希字符串（截取前 32 位以节省存储）
    """
    # ensure_ascii=False 保证中文内容参与哈希；sort_keys 保证字典序列化稳定
    serialized = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:32]


def compute_file_hash(content: bytes) -> str:
    """计算文件内容哈希（SHA-256），用于文件校验与版本指纹。

    对应 FR-3.4.4（文件校验哈希）、IR-4（文书版本指纹）、8.4 审计上传材料哈希。
    :param content: 文件二进制内容
    :return: 完整 16 进制哈希字符串
    """
    return hashlib.sha256(content).hexdigest()


def mask_sensitive(value: str | None, keep_head: int = 3, keep_tail: int = 4) -> str:
    """敏感字段脱敏展示（NFR-S2）。

    默认保留头 3 位与尾 4 位，中间以 * 遮蔽，适用于证件号、卡号、手机号等。
    :param value: 原始敏感值
    :param keep_head: 头部保留位数
    :param keep_tail: 尾部保留位数
    :return: 脱敏后字符串；空值返回空串
    """
    if not value:
        return ""
    length = len(value)
    if length <= keep_head + keep_tail:
        # 过短则整体遮蔽，仅保留首尾各一位
        return value[0] + "*" * max(length - 1, 0)
    masked_len = length - keep_head - keep_tail
    return f"{value[:keep_head]}{'*' * masked_len}{value[-keep_tail:]}"
