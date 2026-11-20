import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.deps import DB, CurrentUser
from app.services import transfer

router = APIRouter(tags=["import-export"])
MAX_BYTES = 25 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "File too large")
    return raw


@router.get("/export/json")
def export_json(db: DB, user: CurrentUser):
    body = json.dumps(transfer.export_json(db, user), indent=2, ensure_ascii=False)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="recall-export.json"'})


@router.post("/import/json")
async def import_json(db: DB, user: CurrentUser, file: UploadFile = File(...)):
    try:
        data = json.loads((await _read(file)).decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "File is not valid JSON")
    if not isinstance(data, dict):
        raise HTTPException(422, "Not a recognised export file")
    try:
        return transfer.import_json(db, user, data)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(422, "Export file is malformed")


@router.get("/export/questions.csv")
def export_csv(db: DB, user: CurrentUser):
    return Response(transfer.export_csv(db, user), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="questions.csv"'})


@router.post("/import/questions")
async def import_questions(db: DB, user: CurrentUser, file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    importer = transfer.IMPORTERS.get(ext)
    if importer is None:
        raise HTTPException(415, f"Unsupported file type. Supported: {', '.join(sorted(transfer.IMPORTERS))}")
    rows, errors = importer.parse(await _read(file))
    result = transfer.import_question_rows(db, user, rows)
    result["errors"] = errors + result["errors"]
    return result
