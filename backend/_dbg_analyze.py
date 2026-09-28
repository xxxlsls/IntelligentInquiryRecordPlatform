"""临时排查脚本：复现 AI 研判链路，定位中栏推荐补充问题为空的原因。"""
import traceback

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.record import QAItem, RecordSession
from app.services.ai_service import AiService
from app.services.fiveflow_service import FiveFlowService

db = SessionLocal()
sessions = db.execute(
    select(RecordSession).order_by(RecordSession.created_at.desc())
).scalars().all()
print("sessions:", [(s.id, s.stage) for s in sessions[:5]])
if not sessions:
    raise SystemExit("no session")
s = sessions[0]

ff = FiveFlowService(db)
cov = ff.compute_coverage(s)
print("overall:", cov.overall_coverage, "has_key_gap:", cov.has_key_gap)
for f in cov.flows:
    print("  flow:", f.flow_label, f.status.value, f.collected_count, "/", f.required_count,
          "key_gaps:", f.key_gaps)
gaps = ff.collect_key_gap_elements(cov)
print("key gap elements:", gaps)

qa_items = list(db.execute(select(QAItem).where(QAItem.session_id == s.id)).scalars().all())
print("qa count:", len(qa_items), "answered:", sum(1 for q in qa_items if q.is_answered))

try:
    res = AiService(db).analyze(s, qa_items, gaps)
    print("ANALYZE OK")
    print("  insufficient:", res.is_insufficient_context, "timeout:", res.is_timeout)
    print("  judgement:", res.case_type_judgement.case_type if res.case_type_judgement else None)
    print("  suggestions:", len(res.suggestions))
    for sg in res.suggestions:
        print("   -", "pinned" if sg.is_pinned else "normal", "|", sg.content)
except Exception:
    traceback.print_exc()
