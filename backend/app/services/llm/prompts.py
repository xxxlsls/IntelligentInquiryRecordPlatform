"""
LLM 中文提示词构造器（大模型私有化接入 · 提示词层）

为四类能力构造面向内网大模型的中文提示词，统一内置：
- 角色设定：电信网络诈骗侦查领域的资深研判专家；
- 领域清单：19 类案由、五流要素编号表、大纲章节枚举（均取自现有种子数据与枚举，
  保证提示词与系统字典一致，对应方案"假设"第 3 条）；
- 强制 JSON 输出说明：明确字段结构，要求 response_format=json_object；
- 合规约束："不确定则留空，不得杜撰"，严禁编造案情中不存在的卡号/金额/网址等。

每个构造函数返回 OpenAI messages 结构：[{"role": "system", ...}, {"role": "user", ...}]。
"""

import json

from app.core.enums import CHAPTER_LABEL, Chapter
from app.seed.flow_elements import FLOW_ELEMENT_DEFINITIONS
from app.seed.templates_19 import CATEGORIES

# 角色设定（system 提示词公共前缀）
_ROLE = (
    "你是公安机关电信网络诈骗侦查领域的资深研判专家，熟悉 19 类电诈案由、"
    "五流（人员流/通信流/网络流/资金流/寄递流）要素体系与询问笔录制作规范。"
    "你必须严格依据用户提供的案情与问答内容作答，"
    "对于案情中未出现或无法确定的信息一律留空，严禁杜撰、猜测或补全任何"
    "银行卡号、金额、网址、电话、时间等关键要素。"
    "你的输出必须是合法的 JSON 对象，不得包含任何解释性文字或 Markdown 代码块标记。"
)


def _case_type_list() -> str:
    """构造 19 类案由清单文本（案由名称 + 典型特征信号词），取自种子数据。"""
    lines = []
    for name, _code, signal_words, _desc, _extra in CATEGORIES:
        lines.append(f"- {name}（典型特征：{'、'.join(signal_words)}）")
    lines.append("- 通用（无法归入上述 19 类或跨类组合情形）")
    return "\n".join(lines)


def _element_table() -> str:
    """构造五流要素编号表文本（编号 + 名称 + 说明），取自要素定义种子。"""
    lines = []
    for flow_type, code, name, _field_type, description, is_core, _sort in FLOW_ELEMENT_DEFINITIONS:
        core_tag = "【核心】" if is_core else ""
        lines.append(f"- {code} {name}{core_tag}（{flow_type}）：{description or ''}")
    return "\n".join(lines)


def _chapter_list() -> str:
    """构造大纲章节枚举文本（英文枚举值 + 中文名）。"""
    return "\n".join(f"- {c.value}（{CHAPTER_LABEL[c]}）" for c in Chapter)


# ============================================================
# 能力二：侦查研判建议生成
# ============================================================
_JUDGE_SCHEMA = {
    "case_type": "涉诈类型判定结论，必须取自下方案由清单中的名称之一",
    "confidence": "判定置信度，0~1 之间的小数",
    "basis": "判定依据支撑链，字符串数组，每条为一个客观事实依据",
    "fact_features": "从案情中提取的事实特征描述，字符串数组",
    "suspect_profile": "嫌疑人画像推断，字符串，无法确定则留空字符串",
    "fund_interception": "下游资金链拦截建议，字符串",
    "followup_investigation": "后续补充侦查指引，字符串",
    "followup_questions": "建议向受害人补充追问的问题，字符串数组",
}


def build_judge_case_prompt(context: str, categories: list[str] | None = None,
                            key_gaps: list[dict] | None = None) -> list[dict]:
    """构造侦查研判提示词（能力二）。

    :param context: 案情 + 已答问答拼接的上下文文本
    :param categories: 可选案由清单（默认使用内置 19 类）
    :param key_gaps: 五流重点缺口要素清单 [{"code","name","flow_label"}]，用于引导追问
    """
    case_list = _case_type_list()
    if categories:
        case_list = "\n".join(f"- {c}" for c in categories)

    gap_text = "无"
    if key_gaps:
        gap_text = "\n".join(
            f"- {g.get('flow_label', '')} · {g.get('name', g.get('code', ''))}（{g.get('code', '')}）缺失"
            for g in key_gaps
        )

    user_prompt = (
        f"【可选案由清单】\n{case_list}\n\n"
        f"【当前五流重点缺口】\n{gap_text}\n\n"
        f"【案情与问答上下文】\n{context}\n\n"
        "请基于上述上下文完成侦查研判，严格按照以下 JSON 结构输出（字段含义见下），"
        "case_type 必须取自案由清单，缺口相关问题请纳入 followup_questions：\n"
        f"{json.dumps(_JUDGE_SCHEMA, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": "system", "content": _ROLE},
        {"role": "user", "content": user_prompt},
    ]


# ============================================================
# 能力三：五流要素抽取
# ============================================================
_EXTRACT_SCHEMA = {
    "items": [
        {
            "element_code": "五流要素编号，必须取自下方要素编号表",
            "value": "从文本中抽取到的要素值，必须为原文出现的内容",
            "evidence_snippet": "该值在原文中的证据片段（原文摘录）",
            "confidence": "抽取置信度，0~1 之间的小数",
        }
    ]
}


def build_extract_elements_prompt(qa_text: str, candidate_codes: list[str] | None = None) -> list[dict]:
    """构造五流要素抽取提示词（能力三）。

    :param qa_text: 待抽取的问答文本
    :param candidate_codes: 候选要素编号（缩小抽取范围、提升精度）；为空时给出完整编号表
    """
    element_table = _element_table()
    scope_hint = ""
    if candidate_codes:
        scope_hint = f"\n【本次重点关注的候选要素编号】\n{', '.join(candidate_codes)}\n"

    user_prompt = (
        f"【五流要素编号表】\n{element_table}\n"
        f"{scope_hint}\n"
        f"【待抽取文本】\n{qa_text}\n\n"
        "请从文本中抽取五流要素值，element_code 必须取自要素编号表，"
        "value 必须是原文真实出现的内容，无法确定的要素请勿输出（宁缺毋滥，不得杜撰）。"
        "严格按照以下 JSON 结构输出：\n"
        f"{json.dumps(_EXTRACT_SCHEMA, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": "system", "content": _ROLE},
        {"role": "user", "content": user_prompt},
    ]


# ============================================================
# 能力四：历史笔录解析导入
# ============================================================
_PARSE_SCHEMA = {
    "qa": [
        {
            "question": "问题内容",
            "answer": "答案内容，无答案则留空字符串",
            "chapter": "归类的大纲章节，必须取自下方章节枚举的英文值",
        }
    ],
    "followup_draft": "针对缺失五流信息的继续问询草稿问题，字符串数组",
}


def build_parse_record_prompt(text: str) -> list[dict]:
    """构造历史笔录解析提示词（能力四）。

    :param text: 历史笔录原始文本（可能为"问：...答：..."结构或非标准格式）
    """
    chapter_list = _chapter_list()
    user_prompt = (
        f"【大纲章节枚举】\n{chapter_list}\n\n"
        f"【历史笔录文本】\n{text}\n\n"
        "请将上述笔录解析为问答对，并为每组问答归类到最合适的章节（chapter 取英文枚举值）；"
        "同时针对缺失的五流关键信息给出继续问询草稿问题。"
        "严格保留原文内容，不得改写或杜撰问答。按照以下 JSON 结构输出：\n"
        f"{json.dumps(_PARSE_SCHEMA, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": "system", "content": _ROLE},
        {"role": "user", "content": user_prompt},
    ]


# ============================================================
# 能力一：语义匹配（向量化模板语义指纹的说明性提示，实际走 embeddings 接口）
# ============================================================
def build_semantic_fingerprint_text(category: str | None, description: str | None,
                                    signal_words: list[str] | None = None) -> str:
    """构造用于向量化的模板语义指纹文本（能力一）。

    与规则算法 _compute_semantic_factor 中的模板侧语义文本构造保持一致，
    保证向量化与字符 bigram 两种路径的语义输入同源，便于平滑降级。
    """
    parts = [category or "", description or ""]
    parts.extend([w for w in (signal_words or []) if w])
    return " ".join(p for p in parts if p)
