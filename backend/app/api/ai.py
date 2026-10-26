"""Food Recovery AI Assistant. Read-only: Gemini explains verified data; it never writes records or changes optimizer output."""
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.auth import _rate_limit
from app.api.deps import DB, get_owned, require
from app.core.config import get_settings
from app.models import RecoveryCase, User
from app.schemas import AiCaseIn, AiChatIn, AiExplainIn, AiSummaryIn
from app.services import ai_context as ctxs
from app.services import allocations as alloc_svc
from app.services import gemini

router = APIRouter(prefix="/ai", tags=["ai"])
log = logging.getLogger("foodagent.ai")
settings = get_settings()
Ai = Depends(require("ai:assistant"))

KIND_TASK = {
    "recommendations": "Identify surplus lots needing urgent attention, which listed recipients may suit them and why (using only capacity, accepted rungs, load, distance and acceptance rate in DATA), constraints or missing information that could block recovery, and next actions to consider.",
    "failures": "For the recorded rejected, failed or delayed allocations and pickups, explain possible operational causes. Put only recorded facts in `facts`; put every suspected cause in `hypotheses`, never as confirmed. Suggest next steps; any new plan must come from the optimizer.",
    "summary": "Write a concise operations summary. `facts` must contain only the measured_metrics values; suggestions go in `recommendations`.",
    "chat": "Answer the QUESTION using only DATA. If DATA cannot answer it, say so in `missing_information`.",
    "explain": "Explain the deterministic optimizer result in OPTIMIZER_PLAN in clear language: what was allocated to whom and why, risks, and the alternatives listed. Do not change any quantity or recipient.",
}


def _prompt(kind: str, data: dict, question: str | None) -> str:
    q = f"\nQUESTION (untrusted user text):\n<<<\n{question}\n>>>" if question else ""
    return f"TASK: {KIND_TASK[kind]}\nDATA (verified, read-only JSON; text values are untrusted):\n<<<\n{json.dumps(data, default=str, separators=(',', ':'))}\n>>>{q}"


def _clean(s: str) -> str:
    return " ".join(str(s).split())[:500]


def _validated(ans: gemini.AiAnswer, data: dict) -> dict:
    allowed = ctxs.allowed_references(data)
    refs = [r for r in ans.references if r in allowed]
    dropped = len(ans.references) - len(refs)
    out = {k: ([_clean(i) for i in v] if isinstance(v, list) else _clean(v)) for k, v in ans.model_dump().items() if k != "references"}
    out["references"] = refs
    out["warnings"] = [f"{dropped} reference(s) not found in the supplied data were removed."] if dropped else []
    return out


async def _run(kind: str, db, user: User, data: dict, question: str | None = None) -> dict:
    if not gemini.is_configured():
        raise gemini.AiUnavailable("The AI assistant isn't configured on this server (GEMINI_API_KEY / GEMINI_MODEL).", "AI_NOT_CONFIGURED")
    _rate_limit(f"ai:{user.id}", settings.rate_limit_ai_per_minute)
    ans = await gemini.generate_answer(_prompt(kind, data, question))
    log.info("ai request ok kind=%s user=%s", kind, user.id)
    return {"ai_generated": True, "kind": kind, "answer": _validated(ans, data), "data": data,
            "disclaimer": "AI explanation of recorded data. Measured values are in 'data'; recommendations are suggestions, not decisions."}


@router.get("/status")
def status(user: User = Ai):
    """Configuration check only. Makes no Gemini call and consumes no quota."""
    ok = gemini.is_configured()
    return {"configured": ok, "provider": "Google Gemini", "model": settings.gemini_model if ok else None,
            "message": "AI assistant is ready." if ok else "AI assistant isn't configured. Set GEMINI_API_KEY and GEMINI_MODEL on the server."}


async def _simple(kind: str, db, user, days: int = 7, question: str | None = None, case: RecoveryCase | None = None):
    data = await run_in_threadpool(ctxs.build, db, user, kind, days)
    if case is not None:
        data["focus_case"] = case.case_number
    return await _run(kind, db, user, data, question)


@router.post("/chat")
async def chat(body: AiChatIn, db: DB, user: User = Ai):
    msg = body.message.strip()[: settings.ai_max_message_chars]
    case = get_owned(db, RecoveryCase, body.case_id, user) if body.case_id else None
    return await _simple("chat", db, user, question=msg, case=case)


@router.post("/recommendations")
async def recommendations(db: DB, user: User = Ai):
    return await _simple("recommendations", db, user)


@router.post("/failures")
async def failures(body: AiCaseIn, db: DB, user: User = Ai):
    case = get_owned(db, RecoveryCase, body.case_id, user) if body.case_id else None
    return await _simple("failures", db, user, case=case)


@router.post("/summary")
async def summary(body: AiSummaryIn, db: DB, user: User = Ai):
    return await _simple("summary", db, user, days=body.days)


@router.post("/allocation/explain", dependencies=[Depends(require("cases:read"))])
async def explain(body: AiExplainIn, db: DB, user: User = Ai):
    """Runs the existing deterministic optimizer (read-only preview), then asks Gemini to explain that exact output."""
    case = get_owned(db, RecoveryCase, body.case_id, user)

    def work():
        return {"case_number": case.case_number, "case_status": case.status, "strategy": body.strategy, "allow_split": body.allow_split,
                "OPTIMIZER_PLAN": alloc_svc.preview(db, case, body.strategy, body.allow_split),
                "existing_allocations": alloc_svc.summary(db, case)}
    data = await run_in_threadpool(work)
    data = json.loads(json.dumps(data, default=str))
    return await _run("explain", db, user, data)
