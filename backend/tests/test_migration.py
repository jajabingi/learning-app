"""Upgrading a pre-LMS database (revision 0001) must keep all data and make existing users administrators."""
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1]


def test_upgrade_from_0001_preserves_data():
    tmp = Path(tempfile.mkdtemp()) / "old.db"
    url = f"sqlite:///{tmp.as_posix()}"
    # build a 0001 database with some personal data using a subprocess (env var is read at import time)
    script = f"""
import os; os.environ['DATABASE_URL']={url!r}; os.environ['AUTO_MIGRATE']='false'
from alembic import command; from alembic.config import Config
cfg=Config({str(BACKEND / 'alembic.ini')!r}); cfg.set_main_option('script_location', {str(BACKEND / 'migrations')!r})
command.upgrade(cfg,'0001')
import sqlite3; c=sqlite3.connect({str(tmp)!r})
c.execute("insert into users(id,email,password_hash,display_name,is_active,desired_retention,daily_new_limit,daily_review_goal,timezone,created_at,updated_at) values('11111111111111111111111111111111','old@x.com','h','Old',1,0.9,20,30,'UTC','2026-01-01','2026-01-01')")
c.execute("insert into users(id,email,password_hash,display_name,is_active,desired_retention,daily_new_limit,daily_review_goal,timezone,created_at,updated_at) values('33333333333333333333333333333333','off@x.com','h','Off',0,0.9,20,30,'UTC','2026-01-01','2026-01-01')")
c.execute("insert into subjects(id,user_id,name,description,color,icon,position,created_at,updated_at) values('22222222222222222222222222222222','11111111111111111111111111111111','Finance','','#fff','book',0,'2026-01-01','2026-01-01')")
c.commit()
command.upgrade(cfg,'head')
"""
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=BACKEND)
    assert r.returncode == 0, r.stderr[-2000:]
    c = sqlite3.connect(tmp)
    assert c.execute("select role from users order by email").fetchall() == [("admin",), ("admin",)]
    assert dict(c.execute("select email, status from users").fetchall()) == {"old@x.com": "active", "off@x.com": "suspended"}   # 0007 backfill
    assert c.execute("select token_version from users").fetchall() == [(0,), (0,)]
    for t in ("user_identities", "audit_logs", "auth_tokens", "lms_exams", "lms_orders", "lms_payments", "lms_installments"):
        assert c.execute(f"select count(*) from {t}").fetchone()[0] == 0
    assert c.execute("select name from subjects").fetchall() == [("Finance",)]
    for t in ("lms_courses", "lms_modules", "lms_lessons", "lms_blocks", "lms_enrollments", "user_permissions"):
        assert c.execute(f"select count(*) from {t}").fetchone()[0] == 0
