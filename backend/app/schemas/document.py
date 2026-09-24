"""
文书导出 Schema（FR-3.5.1 预览 / FR-3.5.2 DOCX 导出）

对应需求文档：
- 8.1 标准询问笔录文书（DOCX）排版规格；
- IR-2 空白过滤、IR-3 红头排版、IR-4 版本指纹。
"""

from pydantic import BaseModel, Field


class DocumentPreviewItem(BaseModel):
    """预览文档流中的问答段落（已过滤未作答空白项，IR-2）。"""

    chapter_label: str | None = Field(default=None, description="章节标题（可选分组）")
    question: str = Field(description="问题内容")
    answer: str = Field(description="答案内容")


class DocumentPreview(BaseModel):
    """红头笔录在线预览数据（FR-3.5.1）。"""

    session_id: str
    red_header_title: str = Field(description="红头标题（如 XX公安局询问笔录）")
    case_no: str = Field(description="案件编号")
    case_category: str | None = Field(default=None, description="案件类别")
    inquiry_time: str | None = Field(default=None, description="询问时间")
    inquiry_place: str | None = Field(default=None, description="询问地点")
    inquirer: str | None = Field(default=None, description="询问人（办案民警）")
    interviewee: str | None = Field(default=None, description="被询问人（报案人）")
    qa_paragraphs: list[DocumentPreviewItem] = Field(default_factory=list, description="问答正文（已过滤空白项）")
    answered_count: int = Field(default=0, description="已作答问答数")
    signature_area: dict = Field(default_factory=dict, description="落款信息（签名区预留）")


class DocumentExportRequest(BaseModel):
    """DOCX 导出请求（FR-3.5.2 导出选项）。"""

    include_five_flow_table: bool = Field(default=False, description="是否附带五流覆盖表（8.2）")
    include_analysis_report: bool = Field(default=False, description="是否附带 AI 研判报告（8.3）")


class DocumentExportResult(BaseModel):
    """DOCX 导出结果（IR-4 版本指纹写入审计）。"""

    file_name: str = Field(description="下载文件名")
    version_fingerprint: str = Field(description="文书版本指纹（写入审计）")
    answered_count: int = Field(default=0, description="导出的已作答问答数")
    message: str = Field(default="生成成功", description="结果提示")
