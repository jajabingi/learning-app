import hashlib
import hmac
import json
import uuid
from datetime import date, timedelta

import pytest

from app.core.config import get_settings
from tests.conftest import make_staff, make_user
from tests.test_phase3 import enroll, two_lessons

settings = get_settings()
PW = "correct-horse-1"


def paid_course(client, th, policy="full_payment", price=1000, discount=800, days=30):
    cid, _ = two_lessons(client, th)
    body = {"price_amount": price, "enrollment_type": "paid", "payment_policy": policy, "access_days": days, "payment_instructions": "Bit 050-0000000 / בנק 12-345"}
    if discount is not None:
        body["discount_amount"] = discount
    r = client.patch(f"/api/teach/courses/{cid}", json=body, headers=th)
    assert r.status_code == 200, r.text
    return cid


def request(client, sh, cid):
    r = client.post(f"/api/student/courses/{cid}/request-access", headers=sh)
    assert r.status_code == 201, r.text
    return r.json()


def my_order(client, sh):
    return client.get("/api/student/payments", headers=sh).json()["orders"][0]


def enrollment(client, th, cid):
    return client.get(f"/api/teach/courses/{cid}/enrollments", headers=th).json()[0]


def pay_in(client, th, oid, amount, method="cash", **kw):
    return client.post(f"/api/teach/orders/{oid}/payments", json={"amount": amount, "method": method, **kw}, headers=th)


def has_access(client, sh, cid):
    return client.get(f"/api/student/courses/{cid}", headers=sh).status_code == 200


# ---------------------------------------------------------------- orders, balance, access
def test_request_creates_order_with_price_snapshot_and_no_access(client, teacher_auth, student_auth):
    cid = paid_course(client, teacher_auth)
    assert request(client, student_auth, cid)["status"] == "pending"
    o = my_order(client, student_auth)
    assert o["amount_due"] == 800.0 and o["balance"] == 800.0 and o["paid"] == 0 and o["status"] == "open"
    assert "Bit 050" in o["payment_instructions"] and o["can_pay_online"] is False
    assert not has_access(client, student_auth, cid)
    request(client, student_auth, cid)                                              # asking again never duplicates
    assert len(client.get("/api/student/payments", headers=student_auth).json()["orders"]) == 1
    # a later price change does not change what this student owes
    client.patch(f"/api/teach/courses/{cid}", json={"discount_amount": 500}, headers=teacher_auth)
    assert my_order(client, student_auth)["amount_due"] == 800.0


def test_full_payment_policy_unlocks_only_when_fully_paid(client, teacher_auth, student_auth):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    r = pay_in(client, teacher_auth, oid, 300, "bank_transfer", reference="TRX-1")
    assert r.status_code == 201 and r.json()["payment"]["receipt_no"] == "R-000001" and r.json()["order"]["balance"] == 500.0
    assert not has_access(client, student_auth, cid) and enrollment(client, teacher_auth, cid)["status"] == "pending"
    r = pay_in(client, teacher_auth, oid, 500)
    assert r.json()["payment"]["receipt_no"] == "R-000002" and r.json()["order"]["status"] == "paid" and r.json()["order"]["balance"] == 0
    e = enrollment(client, teacher_auth, cid)
    assert e["status"] == "active" and e["source"] == "purchase" and e["expires_at"]                   # access_days applied from payment
    assert has_access(client, student_auth, cid)


def test_any_payment_and_none_policies(client, teacher_auth, student_auth, student2_auth):
    cid = paid_course(client, teacher_auth, policy="any_payment")
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    pay_in(client, teacher_auth, oid, 100)
    assert has_access(client, student_auth, cid)                                                  # first instalment is enough
    cid2 = paid_course(client, teacher_auth, policy="none")
    request(client, student2_auth, cid2)
    assert has_access(client, student2_auth, cid2)                                                # access independent of payment
    assert client.get("/api/student/payments", headers=student2_auth).json()["orders"][0]["balance"] == 800.0


def test_payment_validation(client, teacher_auth, student_auth):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    assert pay_in(client, teacher_auth, oid, 0).status_code == 422
    assert pay_in(client, teacher_auth, oid, -5).status_code == 422
    assert pay_in(client, teacher_auth, oid, 800.01).status_code == 409                          # more than the balance
    assert pay_in(client, teacher_auth, oid, 10, "bitcoin").status_code == 422
    assert pay_in(client, teacher_auth, oid, 10, received_at=(date.today() + timedelta(days=30)).isoformat() + "T00:00:00Z").status_code == 422
    assert pay_in(client, teacher_auth, oid, 10.123).status_code == 422                          # at most 2 decimals
    assert pay_in(client, teacher_auth, oid, 800).status_code == 201
    assert pay_in(client, teacher_auth, oid, 1).status_code == 409                               # already settled


def test_void_refund_and_access_revocation(client, teacher_auth, student_auth):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    p1 = pay_in(client, teacher_auth, oid, 800).json()["payment"]
    assert has_access(client, student_auth, cid)
    assert client.post(f"/api/teach/payments/{p1['id']}/void", json={"reason": "x"}, headers=teacher_auth).status_code == 422   # a reason is required
    o = client.post(f"/api/teach/payments/{p1['id']}/void", json={"reason": "entered twice by mistake"}, headers=teacher_auth).json()
    assert o["balance"] == 800.0 and o["payments"][0]["status"] == "voided" and o["status"] == "open"
    assert has_access(client, student_auth, cid)                                                 # voiding never silently removes access
    assert client.post(f"/api/teach/payments/{p1['id']}/void", json={"reason": "again again"}, headers=teacher_auth).status_code == 200   # idempotent
    pay_in(client, teacher_auth, oid, 800)
    assert client.post(f"/api/teach/orders/{oid}/refunds", json={"amount": 900, "reason": "too much"}, headers=teacher_auth).status_code == 422
    o = client.post(f"/api/teach/orders/{oid}/refunds", json={"amount": 200, "reason": "partial goodwill"}, headers=teacher_auth).json()
    assert o["paid"] == 600.0 and o["balance"] == 200.0 and has_access(client, student_auth, cid)
    o = client.post(f"/api/teach/orders/{oid}/refunds", json={"amount": 600, "reason": "withdrawn from course"}, headers=teacher_auth).json()
    assert o["paid"] == 0 and enrollment(client, teacher_auth, cid)["status"] == "cancelled"        # full refund revokes
    assert not has_access(client, student_auth, cid)
    refunds = [p for p in o["payments"] if p["kind"] == "refund"]
    assert [p["receipt_no"][0] for p in refunds] == ["C", "C"]                                    # credit notes, same ledger
    # paying again (e.g. re-enrolment) does NOT override the cancellation: that stays the teacher's decision
    pay_in(client, teacher_auth, oid, 800)
    assert not has_access(client, student_auth, cid)


def test_order_adjustment_cancel_and_audit(client, teacher_auth, student_auth, admin_auth):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    o = client.patch(f"/api/teach/orders/{oid}", json={"amount_due": 600, "reason": "scholarship"}, headers=teacher_auth).json()
    assert o["amount_due"] == 600.0 and o["balance"] == 600.0 and o["list_price"] == 1000.0
    pay_in(client, teacher_auth, oid, 400)
    assert client.patch(f"/api/teach/orders/{oid}", json={"amount_due": 300}, headers=teacher_auth).status_code == 409     # below what was paid
    assert client.patch(f"/api/teach/orders/{oid}", json={"status": "cancelled"}, headers=teacher_auth).status_code == 409   # has payments
    acts = [a["action"] for a in client.get("/api/admin/audit?page_size=100", headers=admin_auth).json()["items"]]
    for want in ("order_adjusted", "payment_recorded"):
        assert want in acts


def test_installments_and_overdue(client, teacher_auth, student_auth):
    cid = paid_course(client, teacher_auth, discount=None)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    first = (date.today() - timedelta(days=40)).isoformat()
    o = client.post(f"/api/teach/orders/{oid}/installments", json={"count": 3, "first_due": first}, headers=teacher_auth).json()
    assert [i["amount"] for i in o["installments"]] == [333.33, 333.33, 333.34]                   # the last absorbs rounding
    assert sum(i["amount"] for i in o["installments"]) == 1000.0
    assert o["overdue"] > 0 and o["installments"][0]["overdue"] is True
    assert client.post(f"/api/teach/orders/{oid}/installments", json={"items": [{"amount": 100, "due_date": first}]}, headers=teacher_auth).status_code == 422   # must add up
    o = pay_in(client, teacher_auth, oid, 333.33).json()["order"]
    assert o["installments"][0]["status"] == "paid" and o["installments"][1]["status"] == "unpaid"
    mine = my_order(client, student_auth)
    assert mine["installments"][0]["paid"] == 333.33 and mine["overdue"] == o["overdue"]
    assert client.post(f"/api/teach/orders/{oid}/installments", json={"clear": True}, headers=teacher_auth).json()["installments"] == []


# ---------------------------------------------------------------- permissions & isolation
def test_isolation_and_permissions(client, teacher_auth, teacher2_auth, student_auth, student2_auth, admin_auth):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    pid = pay_in(client, teacher_auth, oid, 100).json()["payment"]["id"]
    for method, url, kw in (("get", f"/api/teach/orders/{oid}", {}), ("patch", f"/api/teach/orders/{oid}", {"json": {"note": "x"}}),
                            ("post", f"/api/teach/orders/{oid}/payments", {"json": {"amount": 1}}), ("post", f"/api/teach/payments/{pid}/void", {"json": {"reason": "abc"}}),
                            ("post", f"/api/teach/orders/{oid}/refunds", {"json": {"amount": 1, "reason": "abc"}}), ("get", f"/api/teach/courses/{cid}/orders", {}),
                            ("post", f"/api/teach/orders/{oid}/installments", {"json": {"clear": True}})):
        assert getattr(client, method)(url, headers=teacher2_auth, **kw).status_code == 404, url
    sid = client.get("/api/teach/students/lookup", params={"email": "s1@example.com"}, headers=teacher_auth).json()["id"]
    assert client.post("/api/teach/orders", json={"student_id": sid, "course_id": cid}, headers=teacher2_auth).status_code == 404
    assert client.get("/api/teach/finance/summary", headers=teacher2_auth).json()["collected"] == 0       # sees only their own money
    assert client.get("/api/teach/finance/summary", headers=teacher_auth).json()["collected"] == 100.0
    assert client.get("/api/teach/finance/summary", headers=admin_auth).json()["collected"] == 100.0
    # students: no staff endpoints; strictly their own orders
    for url in (f"/api/teach/orders/{oid}", "/api/teach/finance/summary", "/api/teach/finance/ledger.csv", "/api/teach/students-export.csv"):
        assert client.get(url, headers=student_auth).status_code == 403
    assert client.post(f"/api/teach/orders/{oid}/payments", json={"amount": 5}, headers=student_auth).status_code == 403   # a student cannot mark themselves paid
    assert client.get("/api/student/payments", headers=student2_auth).json()["orders"] == []
    assert client.post(f"/api/student/orders/{oid}/checkout", json={}, headers=student2_auth).status_code == 404
    assert client.get(f"/api/student/payments/{pid}/receipt", headers=student2_auth).status_code == 404
    assert client.get(f"/api/student/payments/{pid}/receipt", headers=student_auth).json()["receipt_no"] == "R-000001"
    # fine-grained permission: a teacher without payments.manage / finance.view cannot touch money
    t = next(u for u in client.get("/api/admin/users", headers=admin_auth).json() if u["email"] == "t1@example.com")
    client.patch(f"/api/admin/users/{t['id']}", json={"permissions": ["courses.manage"]}, headers=admin_auth)
    th = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "t1@example.com", "password": PW}).json()["access_token"]}
    assert client.get(f"/api/teach/orders/{oid}", headers=th).status_code == 403
    assert client.get("/api/teach/finance/summary", headers=th).status_code == 403


def test_payment_instructions_are_private_to_the_ordering_student(client, teacher_auth, student_auth, student2_auth):
    cid = paid_course(client, teacher_auth)
    assert "Bit 050" not in client.get(f"/api/public/courses/{cid}").text if client.get(f"/api/public/courses/{cid}").status_code == 200 else True
    assert "Bit 050" not in client.get(f"/api/student/catalog/{cid}", headers=student2_auth).text
    request(client, student_auth, cid)
    assert "Bit 050" in client.get("/api/student/payments", headers=student_auth).text
    assert "Bit 050" not in client.get("/api/student/payments", headers=student2_auth).text


def test_teacher_creates_order_for_a_student_and_balances_show_in_student_list(client, teacher_auth, student_auth):
    cid = paid_course(client, teacher_auth)
    enroll(client, teacher_auth, "s1@example.com", cid)                                               # manual enrollment: free access, no order
    assert client.get("/api/student/payments", headers=student_auth).json()["orders"] == []
    sid = client.get("/api/teach/students/lookup", params={"email": "s1@example.com"}, headers=teacher_auth).json()["id"]
    o = client.post("/api/teach/orders", json={"student_id": sid, "course_id": cid, "amount_due": 500, "note": "friend price"}, headers=teacher_auth)
    assert o.status_code == 201 and o.json()["amount_due"] == 500.0
    assert client.post("/api/teach/orders", json={"student_id": sid, "course_id": cid}, headers=teacher_auth).status_code == 409
    row = client.get("/api/teach/students", headers=teacher_auth).json()[0]
    assert row["balance_due"] == 500.0
    csv = client.get("/api/teach/students-export.csv", headers=teacher_auth)
    assert csv.status_code == 200 and "s1@example.com" in csv.text and "500.0" in csv.text


# ---------------------------------------------------------------- online (sandbox provider) and webhooks
@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(settings, "payment_provider", "sandbox")


def signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    return raw, {"X-Signature": hmac.new(settings.secret_key.encode(), raw, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


def test_online_disabled_by_default(client, teacher_auth, student_auth):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    assert client.get("/api/student/payments", headers=student_auth).json()["online_enabled"] is False
    assert client.post(f"/api/student/orders/{my_order(client, student_auth)['id']}/checkout", json={}, headers=student_auth).status_code == 503


def test_sandbox_checkout_partial_payments_and_idempotency(client, teacher_auth, student_auth, sandbox):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    assert my_order(client, student_auth)["can_pay_online"] is True
    assert client.post(f"/api/student/orders/{oid}/checkout", json={"amount": 900}, headers=student_auth).status_code == 422   # more than owed
    c1 = client.post(f"/api/student/orders/{oid}/checkout", json={"amount": 300}, headers=student_auth).json()
    assert c1["redirect"].startswith("/pay/sandbox/") and my_order(client, student_auth)["paid"] == 0       # pending money is not paid money
    assert not has_access(client, student_auth, cid)
    assert client.post(f"/api/student/payments/{c1['payment_id']}/sandbox-complete", json={"outcome": "success"}, headers=student_auth).json()["status"] == "confirmed"
    assert client.post(f"/api/student/payments/{c1['payment_id']}/sandbox-complete", json={"outcome": "fail"}, headers=student_auth).json()["status"] == "confirmed"   # settled once
    mine = my_order(client, student_auth)
    assert mine["paid"] == 300.0 and mine["balance"] == 500.0
    receipt = client.get(f"/api/student/payments/{c1['payment_id']}/receipt", headers=student_auth).json()
    assert receipt["receipt_no"] == "R-000001" and receipt["balance_after"] == 500.0 and receipt["method"] == "card"
    c2 = client.post(f"/api/student/orders/{oid}/checkout", json={}, headers=student_auth).json()               # default = the whole balance
    assert c2["amount"] == 500.0
    assert client.post(f"/api/student/payments/{c2['payment_id']}/sandbox-complete", json={"outcome": "success"}, headers=student_auth).status_code == 200
    assert has_access(client, student_auth, cid) and my_order(client, student_auth)["status"] == "paid"
    c3 = client.post(f"/api/student/orders/{oid}/checkout", json={"amount": 10}, headers=student_auth)
    assert c3.status_code == 422                                                                        # nothing left to pay


def test_failed_online_payment_changes_nothing(client, teacher_auth, student_auth, sandbox):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    c = client.post(f"/api/student/orders/{oid}/checkout", json={}, headers=student_auth).json()
    assert client.post(f"/api/student/payments/{c['payment_id']}/sandbox-complete", json={"outcome": "fail"}, headers=student_auth).json()["status"] == "failed"
    mine = my_order(client, student_auth)
    assert mine["paid"] == 0 and mine["balance"] == 800.0 and not has_access(client, student_auth, cid)
    assert client.post(f"/api/student/payments/{c['payment_id']}/sandbox-complete", json={"outcome": "bogus"}, headers=student_auth).status_code == 422


def test_webhook_signature_amount_and_replay(client, teacher_auth, student_auth, sandbox):
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    oid = my_order(client, student_auth)["id"]
    c = client.post(f"/api/student/orders/{oid}/checkout", json={"amount": 800}, headers=student_auth).json()
    pend = client.get(f"/api/student/payments/{c['payment_id']}", headers=student_auth).json()
    ref = None
    from app.core.db import SessionLocal
    from app.models.payment import LmsPayment
    db = SessionLocal()
    ref = db.get(LmsPayment, uuid.UUID(c["payment_id"])).provider_ref
    db.close()
    raw, hdr = signed({"provider_ref": ref, "status": "success", "amount": 800})
    assert client.post("/api/payments/webhook/sandbox", content=raw, headers={**hdr, "X-Signature": "0" * 64}).status_code == 401      # forged
    assert client.post("/api/payments/webhook/sandbox", content=raw).status_code == 401                                                  # unsigned
    raw_bad, hdr_bad = signed({"provider_ref": ref, "status": "success", "amount": 1})
    assert client.post("/api/payments/webhook/sandbox", content=raw_bad, headers=hdr_bad).status_code == 409                            # wrong amount
    assert client.post("/api/payments/webhook/other", content=raw, headers=hdr).status_code == 404
    raw_unk, hdr_unk = signed({"provider_ref": "nope", "status": "success", "amount": 800})
    assert client.post("/api/payments/webhook/sandbox", content=raw_unk, headers=hdr_unk).status_code == 404
    assert client.post("/api/payments/webhook/sandbox", content=b"not json", headers={"X-Signature": hmac.new(settings.secret_key.encode(), b"not json", hashlib.sha256).hexdigest()}).status_code == 400
    assert not has_access(client, student_auth, cid) and pend["status"] == "pending"
    assert client.post("/api/payments/webhook/sandbox", content=raw, headers=hdr).json()["status"] == "confirmed"
    assert client.post("/api/payments/webhook/sandbox", content=raw, headers=hdr).json()["status"] == "confirmed"                        # replay: no double count
    assert my_order(client, student_auth)["paid"] == 800.0 and has_access(client, student_auth, cid)


def test_sandbox_is_refused_in_production(client, teacher_auth, student_auth, sandbox, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    cid = paid_course(client, teacher_auth)
    request(client, student_auth, cid)
    assert client.get("/api/student/payments", headers=student_auth).json()["online_enabled"] is False
    assert client.post(f"/api/student/orders/{my_order(client, student_auth)['id']}/checkout", json={}, headers=student_auth).status_code == 503
    raw, hdr = signed({"provider_ref": "x", "status": "success", "amount": 1})
    assert client.post("/api/payments/webhook/sandbox", content=raw, headers=hdr).status_code == 404


# ---------------------------------------------------------------- dashboard & exports
def test_finance_summary_and_ledger_csv(client, teacher_auth, student_auth, student2_auth):
    cid = paid_course(client, teacher_auth, discount=None)
    for sh in (student_auth, student2_auth):
        request(client, sh, cid)
    o1 = client.get("/api/student/payments", headers=student_auth).json()["orders"][0]["id"]
    o2 = client.get("/api/student/payments", headers=student2_auth).json()["orders"][0]["id"]
    pay_in(client, teacher_auth, o1, 1000, "bank_transfer", reference="=HYPERLINK(\"http://evil\")")
    pay_in(client, teacher_auth, o2, 250, "cash")
    client.post(f"/api/teach/orders/{o2}/installments", json={"count": 2, "first_due": (date.today() - timedelta(days=40)).isoformat()}, headers=teacher_auth)
    s = client.get("/api/teach/finance/summary", headers=teacher_auth).json()
    assert s["billed"] == 2000.0 and s["collected"] == 1250.0 and s["outstanding"] == 750.0 and s["currency"] == "ILS"
    assert s["by_method"] == {"bank_transfer": 1000.0, "cash": 250.0} and s["by_course"][0]["collected"] == 1250.0
    assert s["overdue"] == 750.0 and s["overdue_orders"][0]["student_email"] == "s2@example.com"          # both instalments are past due (1000), 250 paid
    csv = client.get(f"/api/teach/finance/ledger.csv?course_id={cid}", headers=teacher_auth)
    assert csv.headers["content-type"].startswith("text/csv") and "R-000001" in csv.text and "'=HYPERLINK" in csv.text   # formula injection neutralised
    assert client.get(f"/api/teach/finance/summary?course_id={uuid.uuid4()}", headers=teacher_auth).status_code == 404


def test_receipt_numbers_are_unique_and_sequential(client, teacher_auth, student_auth, student2_auth):
    cid = paid_course(client, teacher_auth, discount=100)
    nums = []
    for sh in (student_auth, student2_auth):
        request(client, sh, cid)
        oid = client.get("/api/student/payments", headers=sh).json()["orders"][0]["id"]
        for amt in (10, 20):
            nums.append(pay_in(client, teacher_auth, oid, amt).json()["payment"]["receipt_no"])
    assert nums == ["R-000001", "R-000002", "R-000003", "R-000004"]
