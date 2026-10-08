"""
Health records endpoints:
  GET    /api/records       – list user's records
  POST   /api/records       – upload a new record (multipart)
  GET    /api/records/{id}  – get one record with extracted fields
  DELETE /api/records/{id}  – remove a record

Records are stored as a lightweight DB table. File blobs are saved to
local disk under /data/records/<user_id>/ — swap for S3 later.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from ..auth import CurrentUser
from ..database import Base, get_db

router = APIRouter(prefix="/api/records", tags=["records"])

UPLOAD_DIR = os.environ.get("RECORDS_DIR", "/data/records")
os.makedirs(UPLOAD_DIR, exist_ok=True)

RecordType = Literal["lab", "prescription", "letter", "imaging", "other"]


# ── DB model ───────────────────────────────────────────────────────────────────

class HealthRecord(Base):
    __tablename__ = "health_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)  # RecordType
    record_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size_kb: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ready")  # processing | ready
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class HealthRecordOut(BaseModel):
    id: str
    title: str
    type: str
    date: str
    fileName: str
    mime: str
    sizeKb: int
    status: str

    @classmethod
    def from_orm(cls, r: HealthRecord) -> "HealthRecordOut":
        return cls(
            id=str(r.id),
            title=r.title,
            type=r.record_type,
            date=r.record_date,
            fileName=r.file_name,
            mime=r.mime,
            sizeKb=r.size_kb,
            status=r.status,
        )


class ExtractedField(BaseModel):
    label: str
    value: str
    confidence: float


class RecordDetailOut(HealthRecordOut):
    extracted: list[ExtractedField] = []
    pages: int = 1


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[HealthRecordOut])
def list_records(current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    rows = (
        db.query(HealthRecord)
        .filter(HealthRecord.user_id == current_user.id)
        .order_by(HealthRecord.created_at.desc())
        .all()
    )
    return [HealthRecordOut.from_orm(r) for r in rows]


@router.get("/{record_id}", response_model=RecordDetailOut)
def get_record(record_id: int, current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    r = db.query(HealthRecord).filter(
        HealthRecord.id == record_id,
        HealthRecord.user_id == current_user.id,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Record not found")
    return RecordDetailOut(**HealthRecordOut.from_orm(r).model_dump(), extracted=[], pages=1)


@router.post("", response_model=HealthRecordOut, status_code=201)
async def upload_record(
    file: UploadFile = File(...),
    type: str = Form("other"),
    current_user: CurrentUser = ...,
    db: Session = Depends(get_db),
):
    content = await file.read()
    size_kb = max(1, len(content) // 1024)

    # Save file to disk
    user_dir = os.path.join(UPLOAD_DIR, str(current_user.id))
    os.makedirs(user_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file.filename or 'upload'}"
    file_path = os.path.join(user_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = (file.filename or "document").rsplit(".", 1)[0].replace("-", " ").replace("_", " ")

    rec = HealthRecord(
        user_id=current_user.id,
        title=title,
        record_type=type if type in ("lab", "prescription", "letter", "imaging", "other") else "other",
        record_date=today,
        file_name=file.filename or safe_name,
        file_path=file_path,
        mime=file.content_type or "application/octet-stream",
        size_kb=size_kb,
        status="ready",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return HealthRecordOut.from_orm(rec)


@router.delete("/{record_id}", status_code=204)
def delete_record(record_id: int, current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    r = db.query(HealthRecord).filter(
        HealthRecord.id == record_id,
        HealthRecord.user_id == current_user.id,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Record not found")
    # Remove file from disk
    try:
        if os.path.exists(r.file_path):
            os.remove(r.file_path)
    except OSError:
        pass
    db.delete(r)
    db.commit()
    return None
