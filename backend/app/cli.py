"""Operational commands (run on the server; they act directly on the database).

    python -m app.cli create-admin   --email you@example.com [--name "Your Name"]
    python -m app.cli create-teacher --email teacher@example.com [--name "..."]
    python -m app.cli set-role       --email someone@example.com --role student|teacher|admin
    python -m app.cli reset-password --email someone@example.com
    python -m app.cli suspend|activate --email someone@example.com
    python -m app.cli list-users [--role admin]

Passwords are prompted for (never put them on the command line). For scripts set RECALL_PASSWORD in the environment.
Docker:  docker compose exec api python -m app.cli create-admin --email you@example.com
The database schema is upgraded first, so this also works on a brand-new install before the API has ever started.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.permissions import DEFAULT_TEACHER_PERMISSIONS, set_permissions
from app.core.security import hash_password
from app.models.user import User
from app.services import audit, identity


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(cfg, "head")


def _password(confirm: bool = True) -> str | None:
    pw = os.environ.get("RECALL_PASSWORD") or getpass.getpass("Password (min 8 chars): ")
    if confirm and not os.environ.get("RECALL_PASSWORD") and getpass.getpass("Repeat password: ") != pw:
        print("Passwords do not match.", file=sys.stderr)
        return None
    if len(pw) < 8 or len(pw.encode()) > 72:
        print("Password must be 8-72 bytes.", file=sys.stderr)
        return None
    return pw


def _create(db, email: str, name: str, role: str) -> int:
    if identity.find_by_email(db, email):
        print("User already exists; use set-role.", file=sys.stderr)
        return 1
    pw = _password()
    if pw is None:
        return 1
    u = User(email=email, password_hash=hash_password(pw), display_name=name or email.split("@")[0], role=role, status="active", is_active=True)
    db.add(u)
    db.flush()
    if role == "teacher":
        set_permissions(db, u, list(DEFAULT_TEACHER_PERMISSIONS))
    audit.log_event(db, "user_created", target=u, role=role, via="cli")
    print(f"Created {role} {u.email}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("create-admin", "create-teacher"):
        s = sub.add_parser(name)
        s.add_argument("--email", required=True)
        s.add_argument("--name", default="")
    r = sub.add_parser("set-role")
    r.add_argument("--email", required=True)
    r.add_argument("--role", choices=["student", "teacher", "admin"], required=True)
    for name in ("reset-password", "suspend", "activate"):
        sub.add_parser(name).add_argument("--email", required=True)
    ls = sub.add_parser("list-users")
    ls.add_argument("--role", choices=["student", "teacher", "admin"])
    args = p.parse_args(argv)

    if os.environ.get("RECALL_CLI_SKIP_MIGRATE") != "1":
        _migrate()
    db = SessionLocal()
    try:
        if args.cmd == "list-users":
            stmt = select(User).order_by(User.created_at)
            if args.role:
                stmt = stmt.where(User.role == args.role)
            for u in db.scalars(stmt):
                print(f"{u.role:8} {u.status:20} {u.email}")
            return 0
        email = identity.normalize_email(args.email)
        if args.cmd in ("create-admin", "create-teacher"):
            code = _create(db, email, args.name, "admin" if args.cmd == "create-admin" else "teacher")
            db.commit() if code == 0 else db.rollback()
            return code
        u = identity.find_by_email(db, email)
        if u is None:
            print("No such user.", file=sys.stderr)
            return 1
        admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.status == "active")) or 0
        if args.cmd == "set-role":
            if u.role == "admin" and args.role != "admin" and admins <= 1:
                print("Refusing to remove the last active administrator.", file=sys.stderr)
                return 1
            old, u.role = u.role, args.role
            if args.role == "teacher":
                set_permissions(db, u, list(DEFAULT_TEACHER_PERMISSIONS))
            identity.revoke_sessions(u)
            audit.log_event(db, "role_changed", target=u, from_role=old, to_role=args.role, via="cli")
            print(f"{u.email} is now {args.role}")
        elif args.cmd == "reset-password":
            pw = _password()
            if pw is None:
                return 1
            u.password_hash = hash_password(pw)
            identity.revoke_sessions(u)
            audit.log_event(db, "password_changed", target=u, via="cli")
            print(f"Password updated for {u.email}")
        elif args.cmd == "suspend":
            if u.role == "admin" and admins <= 1:
                print("Refusing to suspend the last active administrator.", file=sys.stderr)
                return 1
            identity.set_status(u, "suspended")
            audit.log_event(db, "user_suspended", target=u, via="cli")
            print(f"{u.email} suspended")
        else:
            identity.set_status(u, "active")
            audit.log_event(db, "user_reactivated", target=u, via="cli")
            print(f"{u.email} activated")
        db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
