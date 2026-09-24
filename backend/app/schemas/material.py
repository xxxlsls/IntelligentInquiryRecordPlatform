"""
辅助材料 Schema（BE-7 / DE-7）

对应需求文档：FR-3.4.4 辅助材料拖拽上传与物理隔离、8.4 审计字段。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import MaterialType


class MaterialOut(BaseModel):
    """辅助材料输出模型（材料抽屉列表项）。

    展示文件名、类型、大小、上传人、时间（FR-3.4.4 输出/结果）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    file_name: str = Field(description="原始文件名")
    material_type: MaterialType = Field(description="材料类型")
    content_type: str | None = None
    file_size: int = Field(description="文件大小（字节）")
    file_hash: str = Field(description="文件 SHA-256 哈希")
    uploader_no: str = Field(description="上传人警号")
    virus_scan_status: str = Field(description="病毒扫描状态")
    virus_scan_passed: bool = Field(description="病毒扫描是否通过")
    created_at: datetime = Field(description="上传时间")


class MaterialUploadResult(BaseModel):
    """材料上传结果。"""

    material: MaterialOut = Field(description="已保存的材料元数据")
    message: str = Field(default="上传成功", description="结果提示")


class MaterialListResult(BaseModel):
    """材料列表结果（含物理隔离声明）。"""

    items: list[MaterialOut] = Field(default_factory=list, description="材料列表")
    total: int = Field(default=0, description="材料总数")
    isolation_notice: str = Field(
        default="辅助材料仅作研判输入，物理隔离于正式问答正文（IR-1）",
        description="物理隔离声明（NFR-S1）",
    )
