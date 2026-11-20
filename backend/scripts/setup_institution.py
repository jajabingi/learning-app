"""Creates a sample institution for the seeded course and marks two lessons as free previews (idempotent).
Usage (from backend/):  .venv/Scripts/python scripts/setup_institution.py --owner you@example.com
Rename or replace the sample institution later from Teaching -> Institutions."""
import argparse
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.lms import LmsCourse, LmsInstitution, LmsLesson, LmsModule  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.question import Attachment  # noqa: E402
from app.services import storage  # noqa: E402
from app.services.lms import slugify  # noqa: E402

NAME = "מכון למימון והשקעות (דוגמה)"


def gradient_png(w=640, h=320) -> bytes:
    """A simple navy-to-blue gradient cover (pure Python, no imaging library needed). Replace it with a real cover image."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            t = (x / w * 0.6 + y / h * 0.4)
            raw += bytes((int(11 + 20 * t), int(27 + 90 * t), int(77 + 120 * t)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    sig = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    return sig + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        owner = db.scalar(select(User).where(User.email == args.owner.lower()))
        if owner is None:
            sys.exit("owner not found")
        inst = db.scalar(select(LmsInstitution).where(LmsInstitution.owner_id == owner.id, LmsInstitution.name == NAME))
        if inst is None:
            inst = LmsInstitution(owner_id=owner.id, name=NAME, slug=slugify("finance-institute"), is_published=True,
                                  description="מוסד לדוגמה להצגת עמוד הבית. אפשר לשנות את השם והתיאור או ליצור מוסדות נוספים בתפריט ״Institutions״.")
            db.add(inst)
            db.flush()
        n = 0
        for course in db.scalars(select(LmsCourse).where(LmsCourse.status == "published", LmsCourse.title.like("מימון והשקעות%"))):
            course.institution_id = inst.id
            if course.cover_attachment_id is None:
                png = gradient_png()
                att = Attachment(user_id=course.owner_id, filename="cover.png", content_type="image/png", size_bytes=len(png),
                                 storage_key=storage.save(course.owner_id, png, "cover.png"))
                db.add(att)
                db.flush()
                course.cover_attachment_id = att.id
            for mi, mod in enumerate(db.scalars(select(LmsModule).where(LmsModule.course_id == course.id).order_by(LmsModule.position))):
                first = db.scalar(select(LmsLesson).where(LmsLesson.module_id == mod.id).order_by(LmsLesson.position))
                if mi < 2 and first is not None:
                    first.is_free_preview = True
                    n += 1
        db.commit()
        print(f"institution ready; {n} free-preview lessons set")
    finally:
        db.close()


if __name__ == "__main__":
    main()
