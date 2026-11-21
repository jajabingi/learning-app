"""First-run bootstrap (see config: BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD)."""
import logging

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.services import audit, identity

log = logging.getLogger("recall.bootstrap")


def ensure_first_admin() -> bool:
    """Creates the first administrator only when none exists. Never changes or overwrites an existing account."""
    s = get_settings()
    email, password = identity.normalize_email(s.bootstrap_admin_email), s.bootstrap_admin_password
    if not email or not password:
        return False
    if len(password) < 8 or len(password.encode()) > 72:
        log.error("BOOTSTRAP_ADMIN_PASSWORD must be 8-72 bytes; no admin was created")
        return False
    db = SessionLocal()
    try:
        if db.scalar(select(func.count()).select_from(User).where(User.role == "admin")):
            return False
        if identity.find_by_email(db, email):
            log.error("bootstrap admin e-mail already belongs to a non-admin account; use the CLI set-role command")
            return False
        u = User(email=email, password_hash=hash_password(password), display_name=email.split("@")[0], role="admin", status="active", is_active=True)
        db.add(u)
        db.flush()
        audit.log_event(db, "user_created", target=u, role="admin", via="bootstrap")
        db.commit()
        log.info("created first administrator %s", email)
        return True
    finally:
        db.close()
