"""
端到端集成测试脚本（验收自检用，对应需求文档 10 验收标准 / 场景 10.1）。

使用 FastAPI TestClient 真实发起 HTTP 请求，串联验证核心业务闭环：
    登录 → 接报建档 → AI 推荐模板 → 阶段流转 → 选定模板装配大纲 →
    问答录入（联动五流抽取）→ 五流覆盖度 → AI 研判 → 采纳建议 →
    文书预览 → DOCX 导出 → 审计检索。

运行：python e2e_test.py
说明：使用独立的临时 SQLite 库（test_e2e.db），不污染演示数据。
"""

import os
import sys

# 使用独立测试库，避免污染演示数据（须在导入 app 前设置环境变量）
os.environ["DATABASE_URL"] = "sqlite:///./test_e2e.db"
os.environ["SEED_DEMO_DATA"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PREFIX = "/api/v1"
_passed = 0
_failed = 0


def check(name: str, condition: bool, extra: str = "") -> None:
    """断言并打印结果。"""
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {extra}")


def main() -> None:
    # 删除旧测试库，确保干净环境
    if os.path.exists("test_e2e.db"):
        os.remove("test_e2e.db")

    with TestClient(app) as client:
        # ---------- 0. 健康检查与 OpenAPI ----------
        print("0) 基础探活")
        r = client.get("/health")
        check("健康检查 200", r.status_code == 200, r.text)
        openapi = client.get("/openapi.json").json()
        check("OpenAPI 路径数 > 30", len(openapi["paths"]) > 30, f"实际 {len(openapi['paths'])}")

        # ---------- 1. 登录（办案民警）----------
        print("1) 认证登录（BE-1）")
        r = client.post(f"{PREFIX}/auth/login", json={"officer_no": "P10001", "password": "Officer@123"})
        check("民警登录成功", r.status_code == 200 and r.json()["success"], r.text)
        token = r.json()["data"]["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        r = client.get(f"{PREFIX}/auth/me", headers=auth)
        check("会话校验 /me", r.status_code == 200 and r.json()["data"]["officer_no"] == "P10001", r.text)

        # 错误密码
        r = client.post(f"{PREFIX}/auth/login", json={"officer_no": "P10001", "password": "WrongPass@999"})
        check("错误密码返回 401", r.status_code == 401, r.text)

        # ---------- 2. 接报建档（BE-2）----------
        print("2) 接报录入建档（BE-2）")
        session_payload = {
            "case_no": "A110105202609001",
            "case_category": "虚假投资理财",
            "brief": "受害人被诱导下载国盛智投APP炒股，对方自称导师带单，先后转账多笔累计亏损约80万元。",
            "handling_org": "某分局反诈中心",
            "reporter_name": "张小明",
            "reporter_phone": "13800138001",
        }
        r = client.post(f"{PREFIX}/sessions", json=session_payload, headers=auth)
        check("创建笔录会话", r.status_code == 200 and r.json()["success"], r.text)
        session_id = r.json()["data"]["id"]
        check("初始阶段为 intake", r.json()["data"]["stage"] == "intake", r.text)

        # ---------- 3. AI 推荐模板（BE-5）----------
        print("3) AI 智能推荐模板（BE-5）")
        r = client.post(f"{PREFIX}/ai/recommend", json={
            "brief": session_payload["brief"], "case_category": "虚假投资理财", "top_n": 5,
        }, headers=auth)
        check("模板推荐成功", r.status_code == 200 and r.json()["success"], r.text)
        recs = r.json()["data"]["recommendations"]
        check("返回推荐列表非空", len(recs) > 0, r.text)
        top_template_id = recs[0]["template"]["id"] if recs else None
        print(f"       TOP1 匹配度={recs[0]['match_percent']}% 案由={recs[0]['template']['category']}" if recs else "")

        # ---------- 4. 阶段流转 intake→templates ----------
        print("4) 阶段流转与模板选定（BE-2）")
        r = client.post(f"{PREFIX}/sessions/{session_id}/stage",
                        json={"target_stage": "templates"}, headers=auth)
        check("流转至 templates", r.status_code == 200 and r.json()["data"]["stage"] == "templates", r.text)

        # ---------- 5. 选定模板装配大纲 ----------
        r = client.post(f"{PREFIX}/sessions/{session_id}/select-templates",
                        json={"template_ids": [top_template_id]}, headers=auth)
        check("选定模板并进入 inquiry", r.status_code == 200 and r.json()["data"]["stage"] == "inquiry", r.text)

        # 获取装配的问答大纲
        r = client.get(f"{PREFIX}/sessions/{session_id}/qa", headers=auth)
        check("获取章节问答大纲", r.status_code == 200, r.text)

        # ---------- 6. 问答录入（联动五流抽取）----------
        print("5) 问答编排与五流抽取（BE-2/BE-6）")
        qa_payload = {
            "chapter": "fund_loss",
            "question": "请说明每笔转账的时间、金额、转出银行卡号及对方收款卡号。",
            "answer": "2026年1月5日我通过银行卡6222021234567890123转账5万元到对方账户，"
                      "对方收款卡号是6217009876543210987，通过微信联系，对方网址是 www.guosheng-top.com。",
            "source": "manual",
        }
        r = client.post(f"{PREFIX}/sessions/{session_id}/qa", json=qa_payload, headers=auth)
        check("新增问答项", r.status_code == 200 and r.json()["success"], r.text)

        # 触发五流抽取
        r = client.post(f"{PREFIX}/fiveflow/sessions/{session_id}/extract", json={}, headers=auth)
        check("五流要素抽取", r.status_code == 200, r.text)

        # 覆盖度计算
        r = client.get(f"{PREFIX}/fiveflow/sessions/{session_id}/coverage", headers=auth)
        check("五流覆盖度计算", r.status_code == 200 and "flows" in r.json()["data"], r.text)
        if r.status_code == 200:
            print(f"       总体覆盖度={r.json()['data']['overall_coverage']}% 存在重点缺口={r.json()['data']['has_key_gap']}")

        # ---------- 7. AI 研判 ----------
        print("6) AI 侦查研判与建议采纳（BE-5）")
        r = client.post(f"{PREFIX}/ai/sessions/{session_id}/analyze", headers=auth)
        check("AI 研判生成", r.status_code == 200 and r.json()["success"], r.text)
        if r.status_code == 200:
            data = r.json()["data"]
            print(f"       涉诈类型判定={data.get('case_type_judgement', {}).get('case_type') if data.get('case_type_judgement') else 'N/A'}")

        # 获取持久化建议
        r = client.get(f"{PREFIX}/ai/sessions/{session_id}/suggestions", headers=auth)
        check("获取中栏建议", r.status_code == 200, r.text)
        suggestions = r.json()["data"]
        # 采纳首条建议
        if suggestions:
            r = client.post(f"{PREFIX}/ai/sessions/{session_id}/adopt",
                            json={"suggestion_id": suggestions[0]["id"]}, headers=auth)
            check("采纳 AI 建议", r.status_code == 200, r.text)

        # ---------- 8. 文书预览与导出（BE-7）----------
        print("7) 文书预览与 DOCX 导出（BE-7）")
        r = client.get(f"{PREFIX}/documents/sessions/{session_id}/preview", headers=auth)
        check("红头笔录预览", r.status_code == 200 and r.json()["data"]["answered_count"] > 0, r.text)

        r = client.post(f"{PREFIX}/documents/sessions/{session_id}/export",
                        json={"include_five_flow_table": True, "include_analysis_report": True}, headers=auth)
        check("DOCX 导出 200", r.status_code == 200, r.text[:200])
        check("DOCX 内容非空", len(r.content) > 1000, f"size={len(r.content)}")
        check("含版本指纹响应头", "x-document-fingerprint" in {k.lower() for k in r.headers.keys()}, str(r.headers))

        # ---------- 9. 审计检索（BE-8）----------
        print("8) 审计检索（BE-8）")
        r = client.get(f"{PREFIX}/audit/logs", headers=auth)
        check("民警审计检索（本人）", r.status_code == 200 and r.json()["data"]["total"] > 0, r.text)

        # ---------- 10. 权限隔离验证（DR-2/DR-4）----------
        print("9) 数据权限与越权拦截（DR-2/DR-4）")
        # 研判员登录（只读）
        r = client.post(f"{PREFIX}/auth/login", json={"officer_no": "A20001", "password": "Analyst@123"})
        analyst_token = r.json()["data"]["access_token"]
        analyst_auth = {"Authorization": f"Bearer {analyst_token}"}
        # 研判员尝试编辑问答 → 应被拒绝（403）
        r = client.post(f"{PREFIX}/sessions/{session_id}/qa", json=qa_payload, headers=analyst_auth)
        check("研判员编辑问答被拒 403", r.status_code == 403, f"实际 {r.status_code}")

        # 另一所队民警登录，尝试访问非本人笔录 → 403
        r = client.post(f"{PREFIX}/auth/login", json={"officer_no": "P10002", "password": "Officer@123"})
        other_auth = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
        r = client.get(f"{PREFIX}/sessions/{session_id}/restore", headers=other_auth)
        check("他人民警越权访问被拒 403", r.status_code == 403, f"实际 {r.status_code}")

        # ---------- 11. 外部系统检索（BE-3）----------
        print("10) 外部系统集成（BE-3）")
        r = client.post(f"{PREFIX}/external/search",
                        json={"keyword": "投资理财", "source": "zhiyanpan"}, headers=auth)
        check("外部系统检索", r.status_code == 200 and r.json()["success"], r.text)

        # ---------- 12. 历史笔录导入（FR-3.5.3）----------
        print("11) 历史笔录解析导入（BE-6 扩展）")
        r = client.post(f"{PREFIX}/imports/parse-text", json={
            "text": "问：你的姓名和身份证号？\n答：我叫张小明，身份证110101199001011234。\n"
                    "问：对方如何联系你？\n答：通过微信，还发了一个网址www.abc-top.com。\n"
                    "问：转账多少钱？\n答：转了3万元到对方卡号6222029999888877776。",
        }, headers=auth)
        check("历史笔录解析", r.status_code == 200 and r.json()["data"]["qa_count"] >= 3, r.text)

    # ---------- 汇总 ----------
    print("=" * 60)
    print(f"测试完成：通过 {_passed} 项，失败 {_failed} 项")
    # 释放数据库连接池后再清理临时库（SQLite 文件句柄占用会导致 WinError 32）
    from app.core.database import engine
    engine.dispose()
    try:
        if os.path.exists("test_e2e.db"):
            os.remove("test_e2e.db")
    except OSError:
        pass  # 临时库清理失败不影响测试结论
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
