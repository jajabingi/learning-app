"""Operational commands. Usage:
    python -m app.cli create-admin --email you@example.com [--name "Your Name"]   (prompts for the password)
    python -m app.cli set-role --email someone@example.com --role teacher
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.permissions import DEFAULT_TEACHER_PERMISSIONS, set_permissions
from app.core.security import hash_password
from app.models.user import User


def main(argv=None):
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--name", default="")
    r = sub.add_parser("set-role")
    r.add_argument("--email", required=True)
    r.add_argument("--role", choices=["student", "teacher", "admin"], required=True)
    args = p.parse_args(argv)

    db = SessionLocal()
    try:
        email = args.email.lower()
        existing = db.scalar(select(User).where(User.email == email))
        if args.cmd == "create-admin":
            if existing:
                print("User already exists; use set-role.", file=sys.stderr)
                return 1
            pw = getpass.getpass("Password (min 8 chars): ")
            if len(pw) < 8 or len(pw.encode()) > 72:
                print("Password must be 8-72 bytes.", file=sys.stderr)
                return 1
            db.add(User(email=email, password_hash=hash_password(pw), display_name=args.name or email.split("@")[0], role="admin"))
            print(f"Created administrator {email}")
        else:
            if not existing:
                print("No such user.", file=sys.stderr)
                return 1
            existing.role = args.role
            if args.role == "teacher":
                set_permissions(db, existing, list(DEFAULT_TEACHER_PERMISSIONS))
            print(f"{email} is now {args.role}")
        db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
