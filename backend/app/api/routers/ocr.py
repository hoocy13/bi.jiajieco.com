"""Owner-scoped OCR queue. Workers pull over HTTPS; no inbound PC port is needed."""
from datetime import datetime, timedelta
import hmac
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, permission_codes, require_permission
from app.core.config import settings
from app.db.session import get_db
from app.models.ocr import OcrJob, OcrWorker
from app.models.user import User
from app.schemas.common import ok

router = APIRouter(prefix="/tools/ocr", tags=["ocr"])
MAX_BYTES = 20 * 1024 * 1024
LEASE_SECONDS = 120
user_access = require_permission("dashboard.view")


def worker_access(x_ocr_worker_key: str = Header(default="")) -> None:
    if not settings.OCR_WORKER_KEY or not hmac.compare_digest(x_ocr_worker_key, settings.OCR_WORKER_KEY):
        raise HTTPException(401, "识别工作节点认证失败")


def expire_jobs(db: Session) -> None:
    now = datetime.utcnow()
    db.execute(update(OcrJob).where(OcrJob.expires_at <= now, OcrJob.status != "expired").values(
        status="expired", source=b"", result="", prompt="", fields="", question="", error="文件与结果已过期", lease="", lease_until=None))
    db.execute(update(OcrJob).where(OcrJob.status == "running", OcrJob.lease_until < now, OcrJob.attempts >= 3).values(
        status="failed", error="识别节点多次中断，请重新提交", lease="", lease_until=None))
    db.commit()


def job_data(job: OcrJob, include_result: bool = True) -> dict:
    data = {key: getattr(job, key) for key in (
        "id", "filename", "task", "mode", "status", "error", "pages_done", "pages_total", "regions_done", "regions_total", "created_at", "expires_at")}
    if include_result:
        data["result"] = job.result
        data.update({key: getattr(job, key) for key in ("prompt", "fields", "question", "max_tokens")})
    return data


def owned_job(db: Session, job_id: str, user: User) -> OcrJob:
    job = db.scalar(select(OcrJob).where(OcrJob.id == job_id, OcrJob.user_id == user.id))
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@router.get("/status")
def status(user: User = Depends(user_access), db: Session = Depends(get_db)) -> dict:
    worker = db.get(OcrWorker, 1)
    online = bool(worker and worker.ready and worker.seen_at > datetime.utcnow() - timedelta(seconds=75))
    return ok({"online": online, "region_ready": bool(online and worker.region_ready), "configured": bool(settings.OCR_WORKER_KEY), "max_mb": 20, "max_pages": 20})


@router.post("/export")
def export_result(content: str = Form(..., min_length=1, max_length=2_000_000),
                  format: Literal["md", "json"] = Form("md"), token: str = Form(...),
                  db: Session = Depends(get_db)) -> Response:
    # A normal browser form navigation reliably downloads from an embedded UI.
    # Authenticate the POST body; no credential is placed in the URL or iframe.
    user = get_current_user(token=token, db=db)
    if "dashboard.view" not in permission_codes(user):
        raise HTTPException(403, "当前账号没有访问该功能的权限")
    return Response(content.encode("utf-8"), media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="xiaomi-ocr-result.{format}"',
        "Cache-Control": "no-store",
    })


@router.get("/jobs")
def list_jobs(user: User = Depends(user_access), db: Session = Depends(get_db)) -> dict:
    expire_jobs(db)
    jobs = db.scalars(select(OcrJob).where(OcrJob.user_id == user.id).order_by(OcrJob.created_at.desc()).limit(20))
    return ok([job_data(job, include_result=False) for job in jobs])


@router.post("/jobs")
async def submit_job(file: UploadFile = File(...), task: Literal["document", "kie", "vqa"] = Form("document"),
                     mode: Literal["page", "region"] = Form("page"),
                     prompt: str = Form("", max_length=4000), fields: str = Form("", max_length=2000),
                     question: str = Form("", max_length=2000), user: User = Depends(user_access),
                     max_tokens: int = Form(4096, ge=1, le=16384),
                     db: Session = Depends(get_db)) -> dict:
    if not settings.OCR_WORKER_KEY:
        raise HTTPException(503, "识别服务尚未配置")
    if task == "vqa" and not question.strip():
        raise HTTPException(422, "请输入问题")
    if mode == "region" and task != "document":
        raise HTTPException(422, "区域模式仅支持文档解析")
    source = await file.read(MAX_BYTES + 1)
    if not source or len(source) > MAX_BYTES:
        raise HTTPException(413, "文件不能为空，且不能超过 20 MB")
    if source.startswith(b"%PDF-"):
        mime = "application/pdf"
    elif source.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif source.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif source[:4] == b"RIFF" and source[8:12] == b"WEBP":
        mime = "image/webp"
    elif source.startswith(b"BM"):
        mime = "image/bmp"
    else:
        raise HTTPException(415, "仅支持 PNG、JPG、WEBP、BMP 和 PDF")
    if mime == "application/pdf" and task != "document":
        raise HTTPException(422, "字段提取和图像问答请上传图片")
    expire_jobs(db)
    active = db.scalar(select(func.count()).select_from(OcrJob).where(OcrJob.user_id == user.id, OcrJob.status.in_(["queued", "running"])))
    if active >= 3:
        raise HTTPException(429, "最多同时保留 3 个未完成任务，请稍后再试")
    total = db.scalar(select(func.count()).select_from(OcrJob).where(OcrJob.status.in_(["queued", "running"])))
    if total >= 30:
        raise HTTPException(429, "识别队列已满，请稍后再试")
    now = datetime.utcnow()
    job = OcrJob(id=str(uuid4()), user_id=user.id, filename=(file.filename or "document").replace("\\", "/").split("/")[-1][:255],
                 mime=mime, source=source, task=task, mode=mode, max_tokens=max_tokens, prompt=prompt, fields=fields, question=question,
                 expires_at=now + timedelta(hours=24))
    db.add(job)
    db.commit()
    db.refresh(job)
    return ok(job_data(job))


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(user_access), db: Session = Depends(get_db)) -> dict:
    expire_jobs(db)
    return ok(job_data(owned_job(db, job_id, user)))


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, user: User = Depends(user_access), db: Session = Depends(get_db)) -> dict:
    job = owned_job(db, job_id, user)
    db.delete(job)
    db.commit()
    return ok({"deleted": True})


@router.get("/jobs/{job_id}/file")
def source_file(job_id: str, user: User = Depends(user_access), db: Session = Depends(get_db)) -> Response:
    expire_jobs(db)
    job = owned_job(db, job_id, user)
    if job.status == "expired":
        raise HTTPException(410, "文件已过期")
    return Response(job.source, media_type=job.mime, headers={"Cache-Control": "no-store"})


class PollBody(BaseModel):
    ready: bool = False
    region_ready: bool = False


@router.post("/worker/poll", dependencies=[Depends(worker_access)])
def poll(body: PollBody, db: Session = Depends(get_db)) -> dict:
    expire_jobs(db)
    worker = db.get(OcrWorker, 1)
    if not worker:
        worker = OcrWorker(id=1)
        db.add(worker)
    worker.seen_at, worker.ready = datetime.utcnow(), body.ready
    worker.region_ready = body.ready and body.region_ready
    db.commit()
    if not body.ready:
        return ok(None)
    now = datetime.utcnow()
    eligible = or_(OcrJob.status == "queued", and_(OcrJob.status == "running", OcrJob.lease_until < now, OcrJob.attempts < 3))
    capability = True if body.region_ready else OcrJob.mode == "page"
    job_id = db.scalar(select(OcrJob.id).where(eligible, capability, OcrJob.expires_at > now).order_by(OcrJob.created_at).limit(1))
    if not job_id:
        return ok(None)
    lease = secrets.token_hex(24)
    changed = db.execute(update(OcrJob).where(OcrJob.id == job_id, eligible).values(
        status="running", lease=lease, lease_until=now + timedelta(seconds=LEASE_SECONDS),
        attempts=OcrJob.attempts + 1, pages_done=0, pages_total=0, regions_done=0, regions_total=0))
    db.commit()
    if changed.rowcount != 1:
        return ok(None)
    job = db.get(OcrJob, job_id)
    return ok({"id": job.id, "lease": lease, "mime": job.mime, "task": job.task, "mode": job.mode,
               "max_tokens": job.max_tokens,
               "prompt": job.prompt, "fields": job.fields, "question": job.question})


def lease_filter(job_id: str, lease: str):
    return and_(OcrJob.id == job_id, OcrJob.lease == lease, OcrJob.status == "running",
                OcrJob.lease_until > datetime.utcnow(), OcrJob.expires_at > datetime.utcnow())


@router.get("/worker/jobs/{job_id}/file", dependencies=[Depends(worker_access)])
def worker_file(job_id: str, x_ocr_lease: str = Header(), db: Session = Depends(get_db)) -> Response:
    job = db.scalar(select(OcrJob).where(lease_filter(job_id, x_ocr_lease)))
    if not job:
        raise HTTPException(409, "任务已失效")
    return Response(job.source, media_type=job.mime, headers={"Cache-Control": "no-store"})


class HeartbeatBody(BaseModel):
    pages_done: int = Field(default=0, ge=0, le=20)
    pages_total: int = Field(default=0, ge=0, le=20)
    regions_done: int = Field(default=0, ge=0, le=100)
    regions_total: int = Field(default=0, ge=0, le=100)


@router.post("/worker/jobs/{job_id}/heartbeat", dependencies=[Depends(worker_access)])
def heartbeat(job_id: str, body: HeartbeatBody, x_ocr_lease: str = Header(), db: Session = Depends(get_db)) -> dict:
    now = datetime.utcnow()
    changed = db.execute(update(OcrJob).where(lease_filter(job_id, x_ocr_lease)).values(
        lease_until=now + timedelta(seconds=LEASE_SECONDS), pages_done=body.pages_done, pages_total=body.pages_total,
        regions_done=body.regions_done, regions_total=body.regions_total))
    db.execute(update(OcrWorker).where(OcrWorker.id == 1).values(seen_at=now, ready=True))
    db.commit()
    if changed.rowcount != 1:
        raise HTTPException(409, "任务已失效")
    return ok(None)


class FinishBody(BaseModel):
    result: str = Field(default="", max_length=2_000_000)
    error: str = Field(default="", max_length=255)


@router.post("/worker/jobs/{job_id}/finish", dependencies=[Depends(worker_access)])
def finish(job_id: str, body: FinishBody, x_ocr_lease: str = Header(), db: Session = Depends(get_db)) -> dict:
    if not body.result.strip() and not body.error:
        raise HTTPException(422, "识别结果为空")
    changed = db.execute(update(OcrJob).where(lease_filter(job_id, x_ocr_lease)).values(
        status="failed" if body.error else "succeeded", result=body.result if not body.error else "",
        error=body.error, lease="", lease_until=None))
    db.commit()
    if changed.rowcount != 1:
        raise HTTPException(409, "任务已失效")
    return ok(None)
