# Payments, orders and access

Three separate things, on purpose:

| Concept | Table | Question it answers |
|---|---|---|
| **User** | `users` | Who is this person? role, status |
| **Enrollment / access** | `lms_enrollments` | Which course may they open, until when? |
| **Order + payments** | `lms_orders`, `lms_payments`, `lms_installments` | What do they owe for a course, and what has been paid? |

A student can be enrolled and still owe money, get a course free, or pay in instalments. Payment never *is* the permission; it is only one
of the ways access is granted (see rules below).

## The flow (offline payment: works today)
1. The teacher sets the course to **Paid**, price, optional discount, *"Grant access when…"*, access duration and **How to pay** text
   (bank details, Bit/PayBox number...). *Teaching -> course -> Pricing & access.*
2. The student presses *Request access* on the course page. The server creates a **pending enrollment** (no access) and an **order** with
   the price **snapshot** (later price changes do not change what this student owes).
3. The student sees amount, balance, schedule and the instructions under **My payments** (`/payments`) and pays outside the system.
4. The teacher records it: course -> **Payments** tab -> *Manage* -> *Record a payment* (cash / bank transfer / cheque / Bit-PayBox / other,
   reference). A numbered receipt is issued. When the course's rule is satisfied the enrollment becomes **active** (with the access
   duration) automatically.
5. Partial payments, an **instalment plan** (split evenly or explicit), price adjustments (scholarship), **void** (mistake) and
   **refund** (credit note) are all available on the order. Overdue instalments are flagged for teacher and student.

## Access rules (`payment_policy`)
* `full_payment` - the order balance must reach 0.
* `any_payment` - the first confirmed payment unlocks it.
* `none` - access does not depend on payment (you collect separately; the balance is still tracked).
Payment only ever **activates a pending** enrollment. It never overrides a teacher who suspended/cancelled access. A **full refund**
cancels access that a purchase granted (can be switched off per refund). Voiding a payment does not silently remove access.

## Ledger integrity
Rows are append-only. Only `confirmed` rows count toward the balance (pending/failed/voided do not). Mistakes are voided with a required
reason; every payment, void, refund, price adjustment and instalment plan is written to the audit log. Receipt numbers are sequential
(`R-000001`; refunds are credit notes `C-...`). The CSV export neutralises spreadsheet-formula injection.

## Who can do what
* Teachers: only orders of **their own courses**; recording/voiding/refunding needs `payments.manage`, the finance dashboard and ledger
  export need `finance.view`. Admins see all.
* Students: only their own orders, receipts and payments. A student can never mark anything paid.
* The course's *How to pay* text is shown only to the student who ordered (not in the public catalog).

## Online card payments (provider plug-in)
Cards are never handled by this server: a **hosted gateway page** takes the card and calls our webhook. The server side is built and tested:
* `POST /api/student/orders/{id}/checkout {amount?}` creates a *pending* payment (any amount up to the balance, so instalments work).
* `POST /api/payments/webhook/{provider}` accepts a gateway event only with a valid signature, checks the amount, is idempotent
  (replays change nothing) and then confirms the payment, issues the receipt and unlocks access.
* Set `PAYMENT_PROVIDER=sandbox` to try the whole flow with a **simulated** gateway page (refused when `ENVIRONMENT=production`).
* **To go live with a real gateway** (Tranzila, PayPlus, Cardcom, PayPal, Stripe...): add one adapter in `app/services/payments.py`
  (`create hosted-checkout URL` + `verify/parse webhook`) for the chosen provider, set its keys in `.env`. Nothing else changes.
  This needs a merchant account with that provider, which only the business owner can open.

## Not built yet
Automatic reminder e-mails for overdue instalments, tax invoices (חשבונית מס) / accounting-software integration (these are legal documents
in Israel: use a certified invoicing service), multi-currency conversion, coupon codes.
