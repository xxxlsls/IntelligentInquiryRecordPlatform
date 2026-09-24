"""
外部系统集成服务（BE-3）

实现需求文档：
- FR-3.2.2 外部系统案件一键同步与字段回填；
- OOS-1：智研判/智案管仅提供只读检索与映射回填，严禁回写外部系统。

工程化说明：
真实环境中，本服务应对接智研判/智案管的只读检索接口（12.3 Q-2 待确认接口协议）。
当前实现提供可运行的模拟适配器（MockExternalAdapter），返回脱敏演示数据，
并预留了字段映射（外部字段 → 本地字段）与降级处理逻辑。
生产接入时，仅需替换适配器实现，服务层与接口层无需改动（依赖倒置）。
"""

import random
from abc import ABC, abstractmethod

from app.core.enums import ExternalSource
from app.core.exceptions import ExternalSystemError
from app.schemas.external import (
    ExternalBackfillData,
    ExternalCaseCandidate,
    ExternalSearchResult,
)

# 外部系统来源中文名
_SOURCE_LABEL = {
    ExternalSource.ZHIYANPAN: "智研判",
    ExternalSource.ZHIAN_GUAN: "智案管",
}

# 脱敏演示案件数据（NFR-S2：演示数据均脱敏）
_DEMO_CASES: list[dict] = [
    {
        "external_case_id": "ZYP-2026-000123",
        "case_no": "A110105202601001",
        "case_category": "虚假投资理财",
        "brief": "受害人被诱导下载\"国盛智投\"APP炒股，先后转账多笔累计亏损约80万元。",
        "victim_name": "张*明",
        "victim_id_card": "110101199001011234",
        "victim_phone": "13800138001",
        "handling_org": "某市公安局某分局反诈中心",
    },
    {
        "external_case_id": "ZYP-2026-000456",
        "case_no": "A110105202601002",
        "case_category": "冒充电商物流客服",
        "brief": "受害人接到自称快递客服来电，以快递丢失理赔为由诱导转账，损失约2万元。",
        "victim_name": "李*华",
        "victim_id_card": "110101199203054321",
        "victim_phone": "13900139002",
        "handling_org": "某市公安局某分局某派出所",
    },
    {
        "external_case_id": "ZAG-2026-000789",
        "case_no": "A110105202601003",
        "case_category": "刷单返利",
        "brief": "受害人参与网络刷单兼职，前期小额返利后大额充值无法提现，损失约5万元。",
        "victim_name": "王*",
        "victim_id_card": "110101199508087654",
        "victim_phone": "13700137003",
        "handling_org": "某市公安局某分局反诈中心",
    },
    {
        "external_case_id": "ZAG-2026-001011",
        "case_no": "A110105202601004",
        "case_category": "冒充公检法",
        "brief": "受害人接到自称公安局电话，称其涉嫌洗钱要求将资金转入安全账户，损失约30万元。",
        "victim_name": "赵*强",
        "victim_id_card": "110101198812121111",
        "victim_phone": "13600136004",
        "handling_org": "某市公安局某分局某派出所",
    },
]


class ExternalSystemAdapter(ABC):
    """外部系统只读检索适配器抽象接口（依赖倒置，便于替换真实实现）。"""

    @abstractmethod
    def search(self, keyword: str) -> list[dict]:
        """按关键字只读检索案件，返回原始案件字典列表。

        :param keyword: 案件编号或报案人关键字
        :return: 命中的外部案件原始数据列表
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, external_case_id: str) -> dict | None:
        """按外部案件ID获取单条案件（用于确认回填）。"""
        raise NotImplementedError


class MockExternalAdapter(ExternalSystemAdapter):
    """模拟外部系统适配器（演示用，返回脱敏数据）。

    生产环境替换为真实 HTTP/RPC 客户端；接口契约保持不变。
    """

    def __init__(self, source: ExternalSource, available: bool = True):
        self.source = source
        self.available = available

    def search(self, keyword: str) -> list[dict]:
        """模拟检索：按案件编号/受害人姓名/案由模糊匹配脱敏演示数据。"""
        if not self.available:
            # 模拟外部系统不可用（FR-3.2.2 异常与边界：超时/不可用降级）
            raise ExternalSystemError(f"{_SOURCE_LABEL[self.source]} 系统暂不可用，请降级为手工录入")

        kw = keyword.strip().lower()
        # 不同来源返回数据子集，模拟两个独立系统
        pool = _DEMO_CASES if self.source == ExternalSource.ZHIYANPAN else _DEMO_CASES[::-1]
        hits = []
        for c in pool:
            haystack = f"{c['case_no']} {c['victim_name']} {c['case_category']} {c['brief']}".lower()
            if kw in haystack:
                hits.append(c)
        return hits

    def get_by_id(self, external_case_id: str) -> dict | None:
        """按外部案件ID获取单条案件。"""
        for c in _DEMO_CASES:
            if c["external_case_id"] == external_case_id:
                return c
        return None


class ExternalSystemService:
    """外部系统集成服务（BE-3）。

    职责：调用外部系统只读检索接口 → 返回候选列表 → 字段映射回填。
    严禁回写外部系统（OOS-1）。
    """

    # 外部字段 → 本地字段映射表（FR-3.2.2 处理逻辑步骤 4，12.3 Q-2 待确认字段字典）
    FIELD_MAPPING = {
        "case_no": "case_no",
        "case_category": "case_category",
        "brief": "brief",
        "handling_org": "handling_org",
        "victim_name": "reporter_name",
        "victim_id_card": "reporter_id_card",
        "victim_phone": "reporter_phone",
    }

    def search(self, keyword: str, source: ExternalSource) -> ExternalSearchResult:
        """检索外部系统案件（FR-3.2.2 处理逻辑步骤 1~2）。

        :param keyword: 检索关键字（案件编号/报案人，必填其一）
        :param source: 外部系统来源
        :return: 候选案件列表结果（含可用性与降级提示）
        """
        adapter = self._get_adapter(source)
        try:
            raw_hits = adapter.search(keyword)
        except ExternalSystemError as exc:
            # 外部系统超时/不可用：降级为手工录入并提示（FR-3.2.2 异常与边界）
            return ExternalSearchResult(
                candidates=[], total=0, source=source, is_available=False, message=str(exc.message)
            )

        candidates = [self._to_candidate(c, source) for c in raw_hits]

        # 结果提示（无命中/多条命中需单选）
        if not candidates:
            message = "未检索到匹配案件，请调整关键字或手工录入"
        elif len(candidates) == 1:
            message = "命中 1 条案件，请确认回填"
        else:
            message = f"命中 {len(candidates)} 条案件，请单选确认后回填"

        return ExternalSearchResult(
            candidates=candidates,
            total=len(candidates),
            source=source,
            is_available=True,
            message=message,
        )

    def get_backfill_data(self, external_case_id: str, source: ExternalSource) -> ExternalBackfillData:
        """获取字段映射回填数据（FR-3.2.2 处理逻辑步骤 3~4）。

        民警单选确认命中案件后，执行外部字段 → 本地字段映射，返回可回填数据。
        字段映射缺失项留空待补（FR-3.2.2 异常与边界）。
        """
        adapter = self._get_adapter(source)
        raw = adapter.get_by_id(external_case_id)
        if raw is None:
            raise ExternalSystemError("未在外部系统中找到该案件")

        return ExternalBackfillData(
            case_no=raw.get("case_no"),
            case_category=raw.get("case_category"),
            brief=raw.get("brief"),
            handling_org=raw.get("handling_org"),
            reporter_name=raw.get("victim_name"),
            reporter_id_card=raw.get("victim_id_card"),
            reporter_phone=raw.get("victim_phone"),
            external_source=source,
            external_case_id=external_case_id,
        )

    def _get_adapter(self, source: ExternalSource) -> ExternalSystemAdapter:
        """获取外部系统适配器实例。

        演示环境：以较小概率模拟系统不可用，用于验证降级逻辑；
        生产环境：返回真实适配器（HTTP/RPC 客户端）。
        """
        # 模拟偶发不可用（约 5% 概率），演示降级处理
        available = random.random() > 0.05
        return MockExternalAdapter(source, available=available)

    def _to_candidate(self, raw: dict, source: ExternalSource) -> ExternalCaseCandidate:
        """将外部原始数据转换为候选案件模型。"""
        return ExternalCaseCandidate(
            external_case_id=raw["external_case_id"],
            source=source,
            case_no=raw.get("case_no", ""),
            case_category=raw.get("case_category"),
            brief=raw.get("brief"),
            victim_name=raw.get("victim_name"),
            victim_id_card=raw.get("victim_id_card"),
            victim_phone=raw.get("victim_phone"),
            handling_org=raw.get("handling_org"),
            match_hint=f"来源：{_SOURCE_LABEL[source]}",
        )
