"""Seeds a complete Hebrew course: NPV, IRR, investment appraisal and loan amortization schedules.

Usage (from backend/):  .venv/Scripts/python scripts/seed_npv_course.py --owner you@example.com [--student student@example.com]

All numbers in tables, examples and answers are computed here, so they are always internally consistent.
Re-running replaces the previous copy of this course (and its question-bank entries, tagged `kurs-npv`).
Formulas and acronyms (NPV, IRR, PMT, WACC ...) stay in English; everything else is Hebrew.
"""
import argparse
import csv
import io
import math
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.knowledge import Subject, Tag, Topic  # noqa: E402
from app.models.lms import LmsBlock, LmsCourse, LmsEnrollment, LmsLesson, LmsModule, LmsPracticeItem, LmsPracticeSet  # noqa: E402
from app.models.question import Attachment, Question  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.question import AnswerIn, OptionIn, QuestionCreate  # noqa: E402
from app.services import storage  # noqa: E402
from app.services.lms import slugify  # noqa: E402
from app.services.lms_blocks import clean_block  # noqa: E402
from app.services.questions import create_question  # noqa: E402

COURSE_TITLE = "מימון והשקעות: NPV, IRR ולוחות סילוקין"
SEED_TAG = "kurs-npv"
SAMPLE_VIDEO = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"
VIDEO_TITLE = "הרצאת וידאו (סרטון דוגמה לתצוגה — ניתן להחליף בסרטון שלך על ידי העלאה מהמחשב)"


# ---------------------------------------------------------------- finance helpers
def npv(r, cf):
    return sum(c / (1 + r) ** t for t, c in enumerate(cf))


def irr(cf):
    lo, hi = -0.99, 10.0
    for _ in range(300):
        mid = (lo + hi) / 2
        if npv(mid, cf) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pmt(rate, n, loan):
    return loan * rate / (1 - (1 + rate) ** -n)


def m(x, d=2):
    return f"{x:,.{d}f}"


def p(x, d=2):
    return f"{x * 100:.{d}f}%"


def tbl(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def spitzer(L, r, n):
    pay, bal, rows = pmt(r, n, L), L, []
    for t in range(1, n + 1):
        i = bal * r
        pr = pay - i
        rows.append((t, bal, pay, i, pr, bal - pr))
        bal -= pr
    return rows


def equal_principal(L, r, n):
    pr, bal, rows = L / n, L, []
    for t in range(1, n + 1):
        i = bal * r
        rows.append((t, bal, pr + i, i, pr, bal - pr))
        bal -= pr
    return rows


def balloon(L, r, n):
    rows = []
    for t in range(1, n + 1):
        last = t == n
        rows.append((t, L, L * r + (L if last else 0), L * r, L if last else 0, 0 if last else L))
    return rows


def sched_md(rows):
    body = [(t, m(b0), m(pay), m(i), m(pr), m(b1)) for t, b0, pay, i, pr, b1 in rows]
    body.append(("**סה״כ**", "", f"**{m(sum(r[2] for r in rows))}**", f"**{m(sum(r[3] for r in rows))}**", f"**{m(sum(r[4] for r in rows))}**", ""))
    return tbl(["תקופה (שנה)", "יתרת פתיחה", "תשלום כולל", "ריבית", "החזר קרן", "יתרת סגירה"], body)


# ---------------------------------------------------------------- numbers used in the text
r10 = 0.10
P_I0, P_CF = 100_000, [25_000, 30_000, 35_000, 40_000, 30_000]
P_FLOW = [-P_I0] + P_CF
P_NPV, P_IRR = npv(r10, P_FLOW), irr(P_FLOW)
A, B = [-100_000, 90_000, 30_000, 10_000], [-100_000, 10_000, 40_000, 110_000]
A_NPV, B_NPV, A_IRR, B_IRR = npv(r10, A), npv(r10, B), irr(A), irr(B)
CROSS = irr([b - a for a, b in zip(A, B)])
assert A_IRR > B_IRR and B_NPV > A_NPV and 0.10 < CROSS < min(A_IRR, B_IRR)
L, R, N = 100_000, 0.06, 5
SP, EQ, BL = spitzer(L, R, N), equal_principal(L, R, N), balloon(L, R, N)
SP_PAY = pmt(R, N, L)
for rows in (SP, EQ, BL):  # every method repays exactly L and its payments discount to L at the loan rate
    assert abs(sum(x[4] for x in rows) - L) < 1e-6 and abs(npv(R, [0] + [x[2] for x in rows]) - L) < 1e-6
TOT = {k: sum(x[3] for x in rows) for k, rows in (("sp", SP), ("eq", EQ), ("bl", BL))}
assert TOT["sp"] < TOT["eq"] < TOT["bl"] or TOT["eq"] < TOT["sp"] < TOT["bl"]
EQ_LESS = TOT["eq"] < TOT["sp"]
MPMT = pmt(0.04 / 12, 300, 500_000)
CASE_I, CASE_CF, CASE_SALV, CASE_R = 250_000, 80_000, 20_000, 0.09
CASE_FLOW = [-CASE_I] + [CASE_CF] * 4 + [CASE_CF + CASE_SALV]
CASE_NPV, CASE_IRR = npv(CASE_R, CASE_FLOW), irr(CASE_FLOW)
cum, PAYBACK, DPAYBACK = 0, None, None
for t, c in enumerate(P_FLOW):
    prev = cum
    cum += c
    if t > 0 and PAYBACK is None and cum >= 0:
        PAYBACK = (t - 1) + (-prev) / c
dcum = 0
for t, c in enumerate(P_FLOW):
    prev = dcum
    dcum += c / (1 + r10) ** t
    if t > 0 and DPAYBACK is None and dcum >= 0:
        DPAYBACK = (t - 1) + (-prev) / (c / (1 + r10) ** t)
PI = sum(c / (1 + r10) ** (t + 1) for t, c in enumerate(P_CF)) / P_I0
mirr_fin, mirr_re = 0.08, 0.10
MIRR = (sum(c * (1 + mirr_re) ** (5 - (t + 1)) for t, c in enumerate(P_CF)) / P_I0) ** (1 / 5) - 1


def video():
    return ("video", {"url": SAMPLE_VIDEO, "title": VIDEO_TITLE, "description": "זהו סרטון דוגמה בלבד, כדי להציג את נגן הווידאו. בעורך השיעור אפשר להחליף אותו בסרטון משלך (העלאה מהמחשב או קישור YouTube / Vimeo)."})


def T(md, title=""):
    return ("text", {"title": title, "markdown": md})


def C(md, variant="info"):
    return ("callout", {"variant": variant, "markdown": md})


def F(title, latex, desc=""):
    return ("formula", {"title": title, "latex": latex, "description": desc})


def EX(title, md):
    return ("example", {"title": title, "markdown": md})


def S(md, title="סיכום"):
    return ("summary", {"title": title, "markdown": md})


# ---------------------------------------------------------------- question bank
def fx(template, **vals):
    """Fill «name» placeholders (keeps LaTeX braces untouched)."""
    for k, v in vals.items():
        template = template.replace(f"«{k}»", str(v))
    return template


def steps(*items, final=None):
    out = [f"**שלב {i} —** {t}" for i, t in enumerate(items, 1)]
    if final:
        out.append(f"**תשובה סופית:** {final}")
    return "\n\n".join(out)


def build_questions():
    q = []

    def add(key, qtype, title, content, answer, explanation="", difficulty="medium", options=None, topic=None):
        q.append(dict(key=key, qtype=qtype, title=title, content=content, answer=answer, explanation=explanation,
                      difficulty=difficulty, options=options or [], topic=topic))

    # ======================= ערך הזמן של כסף =======================
    v = 50000 / 1.08 ** 3
    add("pv", "calculation", "ערך נוכחי של סכום עתידי",
        r"מה הערך הנוכחי של $50{,}000$ ₪ שיתקבלו בעוד 3 שנים, בשיעור היוון של $8\%$ בשנה?",
        fx(r"$PV \approx «v»$ ₪", v=m(v)),
        steps(r"כותבים את הנוסחה: $PV = \dfrac{FV}{(1+r)^n}$.", r"מציבים: $FV=50{,}000$, $r=0.08$, $n=3$ ⇒ $PV = \dfrac{50{,}000}{1.08^3}$.",
              fx(r"מחשבים את גורם ההיוון: $1.08^3 = «f»$.", f=f"{1.08 ** 3:.6f}"), fx(r"מחלקים: $50{,}000 / «f» = «v»$.", f=f"{1.08 ** 3:.6f}", v=m(v)),
              final=fx(r"$«v»$ ₪ — פחות מ-$50{,}000$, כי כסף עתידי שווה פחות מכסף היום.", v=m(v))), "easy", topic="tvm")
    v = 20000 * 1.05 ** 10
    add("fv", "calculation", "ערך עתידי עם ריבית דריבית", r"הפקדת $20{,}000$ ₪ בריבית שנתית של $5\%$ (ריבית דריבית). מה יהיה הסכום אחרי 10 שנים?",
        fx(r"$FV \approx «v»$ ₪", v=m(v)),
        steps(r"הנוסחה: $FV = PV\,(1+r)^n$.", r"מציבים: $FV = 20{,}000 \cdot 1.05^{10}$.", fx(r"גורם הצמיחה: $1.05^{10} = «f»$.", f=f"{1.05 ** 10:.6f}"),
              fx(r"מכפילים: $20{,}000 \cdot «f» = «v»$.", f=f"{1.05 ** 10:.6f}", v=m(v)), final=fx(r"$«v»$ ₪", v=m(v))), "easy", topic="tvm")
    fva = 5000 * ((1.06 ** 8 - 1) / .06)
    add("fv_annuity", "calculation", "ערך עתידי של סדרת הפקדות", r"מפקידים $5{,}000$ ₪ בסוף כל שנה במשך 8 שנים בריבית של $6\%$ בשנה. כמה כסף יהיה בחשבון מיד אחרי ההפקדה האחרונה?",
        fx(r"$FV \approx «v»$ ₪", v=m(fva)),
        steps(r"זו סדרת תשלומים שווים (Annuity), ולכן משתמשים בנוסחה: $FV = C \cdot \dfrac{(1+r)^n - 1}{r}$.", r"מציבים: $C=5{,}000$, $r=0.06$, $n=8$.",
              fx(r"$1.06^8 = «a»$, ולכן $(1.06^8-1)/0.06 = «b»$.", a=f"{1.06 ** 8:.6f}", b=f"{(1.06 ** 8 - 1) / .06:.4f}"),
              fx(r"$FV = 5{,}000 \cdot «b» = «v»$.", b=f"{(1.06 ** 8 - 1) / .06:.4f}", v=m(fva)),
              final=fx(r"$«v»$ ₪ (מתוכם $40{,}000$ הפקדות והשאר ריבית).", v=m(fva))), "medium", topic="tvm")
    av = 12000 * (1 - 1.08 ** -5) / .08
    add("annuity", "calculation", "ערך נוכחי של אנונה", r"מהו הערך הנוכחי של תשלום שנתי של $12{,}000$ ₪ למשך 5 שנים (בסוף כל שנה), בשיעור היוון של $8\%$?",
        fx(r"$PV \approx «v»$ ₪", v=m(av)),
        steps(r"סדרת תשלומים שווים — נוסחת ה-Annuity: $PV = C \cdot \dfrac{1-(1+r)^{-n}}{r}$.", r"מציבים: $C=12{,}000$, $r=0.08$, $n=5$.",
              fx(r"$1.08^{-5} = «a»$, ולכן $\dfrac{1-«a»}{0.08} = «b»$.", a=f"{1.08 ** -5:.6f}", b=f"{(1 - 1.08 ** -5) / .08:.4f}"),
              fx(r"$PV = 12{,}000 \cdot «b» = «v»$.", b=f"{(1 - 1.08 ** -5) / .08:.4f}", v=m(av)), final=fx(r"$«v»$ ₪", v=m(av))), "medium", topic="tvm")
    add("perp", "calculation", "Perpetuity", r"נכס מניב $6{,}000$ ₪ בסוף כל שנה לנצח. מה שוויו בשיעור היוון של $5\%$?", fx(r"$PV = «v»$ ₪", v=m(6000 / .05, 0)),
        steps(r"סדרה אינסופית של תשלומים שווים — Perpetuity: $PV = \dfrac{C}{r}$.", r"מציבים: $C = 6{,}000$, $r = 0.05$.", fx(r"$PV = 6{,}000 / 0.05 = «v»$.", v=m(6000 / .05, 0)),
              final=fx(r"$«v»$ ₪", v=m(6000 / .05, 0))), "easy", topic="tvm")
    add("growing_perp", "calculation", "Growing Perpetuity", r"מניה תשלם דיבידנד של $5$ ₪ בעוד שנה, והדיבידנד צפוי לגדול ב-$3\%$ בשנה לנצח. שיעור ההיוון הוא $10\%$. מהו שווי המניה לפי מודל זה?",
        fx(r"$PV \approx «v»$ ₪", v=m(5 / .07)),
        steps(r"דיבידנד שגדל בקצב קבוע — Growing Perpetuity: $PV = \dfrac{C_1}{r-g}$ (בתנאי ש-$r>g$).", r"מציבים: $C_1=5$, $r=0.10$, $g=0.03$.", fx(r"$r-g = 0.07$, ולכן $PV = 5 / 0.07 = «v»$.", v=m(5 / .07)),
              final=fx(r"$«v»$ ₪", v=m(5 / .07))), "medium", topic="tvm")
    ear = (1 + .12 / 12) ** 12 - 1
    add("ear", "calculation", "ריבית אפקטיבית (EAR)", r"ריבית נומינלית (APR) של $12\%$ בשנה, עם capitalization חודשי. מהי הריבית האפקטיבית השנתית (EAR)?", fx(r"$EAR \approx «v»$", v=p(ear)),
        steps(r"הנוסחה: $EAR = \left(1+\dfrac{APR}{m}\right)^{m} - 1$, כאשר $m$ הוא מספר התקופות בשנה.", r"מציבים: $APR = 0.12$, $m = 12$ ⇒ ריבית חודשית $0.12/12 = 0.01$.",
              fx(r"$(1.01)^{12} = «a»$.", a=f"{1.01 ** 12:.6f}"), fx(r"$EAR = «a» - 1 = «v»$.", a=f"{1.01 ** 12:.6f}", v=p(ear)),
              final=fx(r"$«v»$ — גבוהה מה-APR של $12\%$ בגלל הריבית דריבית החודשית.", v=p(ear))), "medium", topic="tvm")
    yrs = math.log(2) / math.log(1.07)
    add("double", "calculation", "כמה זמן לכפל את הכסף?", r"בכמה שנים יוכפל סכום כסף בריבית דריבית של $7\%$ בשנה? חשבו במדויק והשוו לכלל ה-72.", fx(r"$n \approx «v»$ שנים", v=f"{yrs:.2f}"),
        steps(r"מחפשים $n$ שעבורו $(1.07)^n = 2$.", r"לוקחים לוגריתם משני הצדדים: $n \cdot \ln(1.07) = \ln 2$ ⇒ $n = \dfrac{\ln 2}{\ln 1.07}$.",
              fx(r"$\ln 2 = 0.6931$, $\ln 1.07 = «l»$ ⇒ $n = «v»$.", l=f"{math.log(1.07):.4f}", v=f"{yrs:.2f}"), fx(r"כלל ה-72: $72/7 \approx «r»$ שנים — קירוב טוב.", r=f"{72 / 7:.2f}"),
              final=fx(r"כ-$«v»$ שנים.", v=f"{yrs:.2f}")), "medium", topic="tvm")
    pv3 = 40000 * (1 - 1.10 ** -3) / .10
    add("choose_today", "calculation", "לקחת היום או לקבל תשלומים?", r"מציעים לכם $100{,}000$ ₪ היום, או $40{,}000$ ₪ בסוף כל אחת מ-3 השנים הקרובות. שיעור ההיוון הוא $10\%$. מה כדאי יותר?",
        fx(r"$PV = «v»$ ₪ ⇒ " + ("עדיף לקחת $100{,}000$ היום" if pv3 < 100000 else "עדיף לקבל את התשלומים"), v=m(pv3)),
        steps(r"כדי להשוות חייבים להעביר הכול לאותה נקודת זמן — היום ($t=0$).", r"הערך הנוכחי של האנונה: $PV = 40{,}000 \cdot \dfrac{1-1.10^{-3}}{0.10}$.",
              fx(r"$\dfrac{1-1.10^{-3}}{0.10} = «b»$ ⇒ $PV = 40{,}000 \cdot «b» = «v»$.", b=f"{(1 - 1.10 ** -3) / .10:.4f}", v=m(pv3)),
              fx(r"משווים: $100{,}000$ מול $«v»$.", v=m(pv3)), final=("עדיף לקבל $100{,}000$ ₪ היום." if pv3 < 100000 else "עדיף לקבל את שלושת התשלומים.")), "hard", topic="tvm")

    # ======================= NPV =======================
    n3 = npv(0.12, [-80_000, 30_000, 35_000, 40_000])
    pvs3 = [30_000 / 1.12, 35_000 / 1.12 ** 2, 40_000 / 1.12 ** 3]
    add("npv_calc", "calculation", "חישוב NPV", r"פרויקט דורש השקעה ראשונית של $80{,}000$ ₪ ומניב $30{,}000$, $35{,}000$ ו-$40{,}000$ ₪ בסוף שנים 1, 2 ו-3. שיעור ההיוון: $12\%$. חשבו את ה-NPV והחליטו אם כדאי לבצע.",
        fx(r"$NPV \approx «v»$ ₪ — " + ("חיובי, כדאי לבצע." if n3 > 0 else "שלילי, לא כדאי."), v=m(n3)),
        steps(r"נוסחה: $NPV = -I_0 + \sum_{t=1}^{n} \dfrac{CF_t}{(1+r)^t}$. ההשקעה ב-$t=0$ אינה מהוונת.",
              fx(r"שנה 1: $30{,}000/1.12 = «a»$.", a=m(pvs3[0])), fx(r"שנה 2: $35{,}000/1.12^2 = «a»$.", a=m(pvs3[1])), fx(r"שנה 3: $40{,}000/1.12^3 = «a»$.", a=m(pvs3[2])),
              fx(r"סוכמים את הערכים הנוכחיים: $«a» + «b» + «c» = «s»$.", a=m(pvs3[0]), b=m(pvs3[1]), c=m(pvs3[2]), s=m(sum(pvs3))),
              fx(r"$NPV = -80{,}000 + «s» = «v»$.", s=m(sum(pvs3)), v=m(n3)),
              final=fx(r"$NPV = «v»$ ₪ " + ("> 0 ⇒ הפרויקט כדאי." if n3 > 0 else "< 0 ⇒ הפרויקט לא כדאי."), v=m(n3))), "medium", topic="npv")
    add("npv_rule", "multiple_choice", "כלל ההחלטה של NPV", r"פרויקט בעל $NPV > 0$ (בשיעור ההיוון המתאים) — מה המשמעות?", "הפרויקט מוסיף ערך וכדאי לקבלו.",
        steps("ה-NPV הוא ההפרש בין הערך הנוכחי של התקבולים לעלות ההשקעה, במונחי שקלים של היום.", r"$NPV>0$ פירושו שהפרויקט מרוויח יותר מעלות ההון — כלומר יוצר ערך.", "לכן מקבלים אותו (בהינתן שאין מגבלת הון ושאין פרויקט סותר טוב יותר).", final="הפרויקט מוסיף ערך וכדאי לקבלו."),
        "easy", [("הפרויקט מוסיף ערך וכדאי לקבלו", True), ("הפרויקט מפסיד כסף ולכן יש לדחותו", False), ("הפרויקט מחזיר בדיוק את עלות ההון", False), ("אי אפשר לקבוע בלי לחשב IRR", False)], "npv")
    nneg = npv(0.12, [-150_000] + [45_000] * 4)
    add("npv_neg", "calculation", "פרויקט שאינו כדאי", r"פרויקט דורש השקעה של $150{,}000$ ₪ ומניב $45{,}000$ ₪ בסוף כל אחת מ-4 שנים. עלות ההון: $12\%$. האם כדאי לבצע?",
        fx(r"$NPV \approx «v»$ ₪ ⇒ " + ("לא כדאי." if nneg < 0 else "כדאי."), v=m(nneg)),
        steps(r"התקבולים הם תשלומים שווים (Annuity) ולכן: $PV = 45{,}000 \cdot \dfrac{1-1.12^{-4}}{0.12}$.", fx(r"$\dfrac{1-1.12^{-4}}{0.12} = «b»$ ⇒ $PV = «p»$.", b=f"{(1 - 1.12 ** -4) / .12:.4f}", p=m(45000 * (1 - 1.12 ** -4) / .12)),
              fx(r"$NPV = -150{,}000 + «p» = «v»$.", p=m(45000 * (1 - 1.12 ** -4) / .12), v=m(nneg)), final=("NPV שלילי — לא כדאי לבצע את הפרויקט." if nneg < 0 else "NPV חיובי — כדאי.")), "medium", topic="npv")
    add("excel_npv", "multiple_choice", "פונקציית NPV באקסל", "מה הטעות הנפוצה בשימוש בפונקציה =NPV(rate, values) באקסל?", "הפונקציה מהווננת את הערך הראשון לתקופה 1, ולכן יש להוסיף את ההשקעה ההתחלתית מחוץ לפונקציה.",
        steps("הפונקציה מניחה שהערך הראשון בטווח מתרחש בסוף התקופה הראשונה ($t=1$) ולכן מהווננת אותו.", "ההשקעה ההתחלתית מתרחשת ב-$t=0$ ולא אמורה להיות מהוונת.", "לכן: `=NPV(rate, CF1:CFn) + CF0` — כאשר CF0 (השלילי) נמצא מחוץ לטווח.",
              final="ההשקעה ההתחלתית צריכה להיות מחוץ לטווח ולהתווסף בנפרד."), "medium",
        [("היא מהוונת את הערך הראשון בטווח לתקופה 1, ולכן ההשקעה ההתחלתית צריכה להיות מחוץ לטווח", True), ("היא לא מקבלת שיעורי ריבית שליליים", False), ("היא מחשבת IRR ולא NPV", False), ("היא מצריכה תזרימים שווים", False)], "npv")
    r_e, wacc = .03 + .8 * (.08 - .03), .7 * .11 + .3 * .05 * .77
    add("capm", "calculation", "עלות ההון העצמי (CAPM)", r"הריבית חסרת הסיכון $3\%$, תשואת השוק $8\%$ וה-$\beta$ של מניה היא $0.8$. מהי עלות ההון העצמי לפי CAPM?", fx(r"$r_E = «v»$", v=p(r_e, 1)),
        steps(r"הנוסחה: $r_E = r_f + \beta\,(r_m - r_f)$.", r"פרמיית הסיכון של השוק: $r_m - r_f = 8\% - 3\% = 5\%$.", fx(r"$r_E = 3\% + 0.8 \cdot 5\% = 3\% + 4\% = «v»$.", v=p(r_e, 1)), final=fx(r"$«v»$", v=p(r_e, 1))), "easy", topic="npv")
    add("wacc", "calculation", "חישוב WACC", r"מבנה ההון של חברה: $70\%$ הון עצמי בעלות $11\%$ ו-$30\%$ חוב בעלות $5\%$. מס החברות $23\%$. חשבו את ה-WACC.", fx(r"$WACC \approx «v»$", v=p(wacc, 3)),
        steps(r"הנוסחה: $WACC = \dfrac{E}{V}r_E + \dfrac{D}{V}r_D(1-T_c)$.", fx(r"רכיב ההון העצמי: $0.70 \cdot 11\% = «a»$.", a=p(.7 * .11, 2)),
              fx(r"רכיב החוב אחרי מס: $0.30 \cdot 5\% \cdot (1-0.23) = «a»$.", a=p(.3 * .05 * .77, 3)), fx(r"$WACC = «a» + «b» = «v»$.", a=p(.7 * .11, 2), b=p(.3 * .05 * .77, 3), v=p(wacc, 3)),
              final=fx(r"$«v»$ — מדוע החוב ״זול״ יותר? כי הריבית מוכרת לצורכי מס.", v=p(wacc, 3))), "medium", topic="npv")
    add("sunk", "true_false", "עלויות שקועות", "נכון או לא נכון: הוצאה שכבר בוצעה בעבר (עלות שקועה) צריכה להיכלל בתזרים של פרויקט חדש.", "לא נכון",
        steps("תזרים הפרויקט כולל רק תזרימים **נוספים** (Incremental) שנגרמים בגלל ההחלטה.", "עלות שקועה כבר שולמה ואינה משתנה בין לבצע או לא לבצע — לכן אין להתחשב בה.", "לעומת זאת עלות אלטרנטיבית (Opportunity cost) כן נכללת.", final="לא נכון."),
        "medium", [("True", False), ("False", True)], "npv")
    add("npv_five", "calculation", "NPV של פרויקט עם חמישה תזרימים", r"פרויקט: השקעה $100{,}000$ ₪; תקבולים בשנים 1–5: $25{,}000$, $30{,}000$, $35{,}000$, $40{,}000$, $30{,}000$. שיעור ההיוון $10\%$. מהו ה-NPV?",
        fx(r"$NPV \approx «v»$ ₪", v=m(P_NPV)),
        steps(r"נוסחה: $NPV = -I_0 + \sum CF_t/(1+r)^t$.", *[fx(r"שנה «t»: $«c» / 1.10^{«t»} = «p»$.", t=t, c=m(c, 0), p=m(c / 1.1 ** t)) for t, c in enumerate(P_CF, 1)],
              fx(r"סכום הערכים הנוכחיים: $«s»$.", s=m(sum(c / 1.1 ** t for t, c in enumerate(P_CF, 1)))), fx(r"$NPV = -100{,}000 + «s» = «v»$.", s=m(sum(c / 1.1 ** t for t, c in enumerate(P_CF, 1))), v=m(P_NPV)),
              final=fx(r"$NPV = «v»$ ₪ > 0 ⇒ כדאי.", v=m(P_NPV))), "medium", topic="npv")

    # ======================= IRR =======================
    add("irr_def", "true_false", "הגדרת IRR", "נכון או לא נכון: ה-IRR הוא שיעור ההיוון שבו ה-NPV של הפרויקט שווה לאפס.", "נכון",
        steps(r"$IRR$ מוגדר כשיעור $r$ שמקיים $\sum_{t=0}^{n} CF_t/(1+r)^t = 0$.", "כלומר ב-IRR הערך הנוכחי של התקבולים שווה בדיוק לעלות ההשקעה.", final="נכון."), "easy", [("True", True), ("False", False)], "irr")
    add("irr_simple", "calculation", "IRR של פרויקט פשוט", r"משקיעים $1{,}000$ ₪ היום ומקבלים $1{,}100$ ₪ בעוד שנה. מהו ה-IRR?", fx(r"$IRR = «v»$", v="10%"),
        steps(r"מציבים בהגדרה: $-1{,}000 + \dfrac{1{,}100}{1+IRR} = 0$.", r"מעבירים אגפים: $\dfrac{1{,}100}{1+IRR} = 1{,}000$.", r"מחלקים: $1+IRR = 1.1$.", final=r"$IRR = 10\%$."), "easy", topic="irr")
    ci = [-10000, 4000, 4000, 4000]
    n8, n10 = npv(.08, ci), npv(.10, ci)
    interp = .08 + .02 * n8 / (n8 - n10)
    add("irr_interp", "calculation", "IRR באינטרפולציה", r"השקעה של $10{,}000$ ₪ מניבה $4{,}000$ ₪ בסוף כל אחת מ-3 שנים. חשבו קירוב ל-IRR באינטרפולציה בין $8\%$ ל-$10\%$.", fx(r"$IRR \approx «v»$ (ערך מדויק: «e»)", v=p(interp), e=p(irr(ci))),
        steps(r"מחשבים NPV בשני שיעורי היוון ומחפשים היכן הוא מתאפס.", fx(r"$NPV(8\%) = -10{,}000 + 4{,}000 \cdot 2.5771 = «a»$.", a=m(n8)), fx(r"$NPV(10\%) = -10{,}000 + 4{,}000 \cdot 2.4869 = «b»$.", b=m(n10)),
              r"שינוי הסימן בין $8\%$ ל-$10\%$ ⇒ ה-IRR בין הערכים.", fx(r"אינטרפולציה: $IRR \approx 8\% + 2\% \cdot \dfrac{«a»}{«a» - («b»)} = «v»$.", a=m(n8), b=m(n10), v=p(interp)),
              final=fx(r"$IRR \approx «v»$ (הערך המדויק «e»).", v=p(interp), e=p(irr(ci)))), "hard", topic="irr")
    add("irr_decision", "multiple_choice", "החלטה לפי IRR", r"לפרויקט $IRR = 14\%$ ועלות ההון (Hurdle rate) היא $11\%$. מה ההחלטה?", "לקבל את הפרויקט.",
        steps(r"כלל ההחלטה: מקבלים אם $IRR > r$.", r"כאן $14\% > 11\%$.", r"גם ה-NPV בשיעור $11\%$ חיובי (בפרויקט קונבנציונלי), ולכן שני הקריטריונים מסכימים.", final="לקבל."), "easy",
        [("לקבל, כי IRR גבוה מעלות ההון", True), ("לדחות, כי IRR גבוה מדי", False), ("אי אפשר להחליט בלי Payback", False), ("להיות אדישים", False)], "irr")
    add("multi_irr", "multiple_choice", "יותר מ-IRR אחד", "מתי עלולים להתקבל מספר ערכי IRR לאותו פרויקט?", "כאשר התזרימים אינם קונבנציונליים (יותר מהיפוך סימן אחד).",
        steps(r"ה-IRR הוא שורש של פולינום ב-$1/(1+r)$; כשהסימנים מתהפכים יותר מפעם אחת יכולים להיות כמה שורשים.", r"דוגמה: $-100, +230, -132$ — מציבים $r=10\%$: $-100 + 209.09 - 109.09 = 0$; וגם $r=20\%$: $-100+191.67-91.67=0$.", "לכן בתזרים לא קונבנציונלי משתמשים ב-NPV או ב-MIRR.",
              final="כשיש יותר מהיפוך סימן אחד."), "medium", [("כשיש יותר מהיפוך סימן אחד בתזרימים", True), ("כשהפרויקט ארוך מ-10 שנים", False), ("כשהשקעה ראשונית גבוהה מאוד", False), ("כשעלות ההון נמוכה מ-5%", False)], "irr")
    add("conflict", "conceptual", "סתירה בין NPV ל-IRR", "מדוע ייתכן ש-IRR ו-NPV ידרגו שני פרויקטים סותרים (mutually exclusive) בצורה שונה? איזה קריטריון עדיף ומדוע?",
        "מעדיפים את הפרויקט עם NPV גבוה יותר.",
        steps("**הסיבה:** IRR הוא תשואה באחוזים ומתעלם מגודל ההשקעה, ומניח השקעה מחדש של תזרימי הביניים בשיעור ה-IRR עצמו. NPV מודד תוספת ערך בשקלים ומניח השקעה מחדש בעלות ההון.",
              fx(r"**דוגמה:** פרויקט A: $IRR=«a»$, $NPV(10\%)=«na»$; פרויקט B: $IRR=«b»$, $NPV(10\%)=«nb»$. A עדיף לפי IRR ו-B לפי NPV.", a=p(A_IRR), na=m(A_NPV), b=p(B_IRR), nb=m(B_NPV)),
              fx(r"**נקודת Crossover:** שיעור ההיוון שבו $NPV_A = NPV_B$ — כאן כ-«c». מתחתיו B עדיף, מעליו A עדיף.", c=p(CROSS)),
              "**כלל:** מעדיפים את ה-NPV הגבוה יותר בשיעור ההיוון הרלוונטי, כי המטרה היא למקסם את ערך החברה בשקלים.", final="NPV גבוה יותר — הוא הקריטריון העדיף לבחירה בין פרויקטים סותרים."), "hard", topic="irr")
    mf = (sum(c * 1.10 ** (3 - t) for t, c in enumerate([500, 500, 500], 1)) / 1000) ** (1 / 3) - 1
    add("mirr", "calculation", "חישוב MIRR", r"השקעה של $1{,}000$ ₪ מניבה $500$ ₪ בסוף כל אחת מ-3 שנים. הנחת ההשקעה מחדש: $10\%$. חשבו את MIRR.", fx(r"$MIRR \approx «v»$", v=p(mf)),
        steps(r"מחשבים את הערך העתידי של התקבולים בסוף שנה 3 בשיעור ההשקעה מחדש ($10\%$): $500\cdot1.10^2 + 500\cdot1.10 + 500$.",
              fx(r"$500\cdot1.21 + 500\cdot1.1 + 500 = «a»$.", a=m(500 * 1.21 + 500 * 1.1 + 500)), r"הערך הנוכחי של ההשקעה: $1{,}000$ (יציאה אחת ב-$t=0$).",
              fx(r"$MIRR = \left(\dfrac{«a»}{1{,}000}\right)^{1/3} - 1 = «v»$.", a=m(500 * 1.21 + 500 * 1.1 + 500), v=p(mf)), final=fx(r"$MIRR \approx «v»$", v=p(mf))), "hard", topic="irr")

    # ======================= Payback / PI =======================
    pb_flow = [-50000, 20000, 25000, 30000]
    pbk = 2 + (50000 - 45000) / 30000
    add("payback_calc", "calculation", "תקופת החזר (Payback)", r"השקעה של $50{,}000$ ₪ מניבה $20{,}000$, $25{,}000$ ו-$30{,}000$ ₪ בסוף שנים 1, 2, 3. מהי תקופת ההחזר (Payback)?", fx(r"$\approx «v»$ שנים", v=f"{pbk:.2f}"),
        steps("בונים תזרים מצטבר: אחרי שנה 1: $-30{,}000$; אחרי שנה 2: $-5{,}000$; אחרי שנה 3: $+25{,}000$.", "ההחזר מתרחש במהלך שנה 3.", r"בשנתיים הראשונות נותרו $5{,}000$ ₪ להחזיר, ובשנה 3 מתקבלים $30{,}000$: חלק השנה $= 5{,}000/30{,}000 = 0.17$.",
              final=fx(r"$2 + 0.17 = «v»$ שנים.", v=f"{pbk:.2f}")), "easy", topic="pb")
    dp = [20000 / 1.1, 25000 / 1.1 ** 2, 30000 / 1.1 ** 3]
    dpb = 2 + (50000 - dp[0] - dp[1]) / dp[2]
    add("disc_payback", "calculation", "Discounted Payback", r"באותו פרויקט (השקעה $50{,}000$; תקבולים $20{,}000$, $25{,}000$, $30{,}000$) חשבו Discounted Payback בשיעור $10\%$.", fx(r"$\approx «v»$ שנים", v=f"{dpb:.2f}"),
        steps(fx(r"מהוונים כל תקבול: $20{,}000/1.1 = «a»$; $25{,}000/1.1^2 = «b»$; $30{,}000/1.1^3 = «c»$.", a=m(dp[0]), b=m(dp[1]), c=m(dp[2])),
              fx(r"מצטבר מהוון: שנה 1: $«x»$; שנה 2: $«y»$; שנה 3: $«z»$.", x=m(-50000 + dp[0]), y=m(-50000 + dp[0] + dp[1]), z=m(-50000 + sum(dp))),
              fx(r"נותרו $«r»$ ₪ בסוף שנה 2, והתקבול המהוון בשנה 3 הוא $«c»$: חלק השנה $= «f»$.", r=m(50000 - dp[0] - dp[1]), c=m(dp[2]), f=f"{(50000 - dp[0] - dp[1]) / dp[2]:.2f}"),
              final=fx(r"$2 + «f» = «v»$ שנים — ארוך מה-Payback הפשוט.", f=f"{(50000 - dp[0] - dp[1]) / dp[2]:.2f}", v=f"{dpb:.2f}")), "medium", topic="pb")
    pi_ = sum(dp) / 50000
    add("pi_calc", "calculation", "Profitability Index", r"באותו פרויקט, בשיעור $10\%$ — חשבו את ה-Profitability Index (PI) והחליטו.", fx(r"$PI \approx «v»$", v=f"{pi_:.3f}"),
        steps(r"הנוסחה: $PI = \dfrac{PV\ \text{of inflows}}{I_0}$.", fx(r"סכום הערכים הנוכחיים של התקבולים: $«a» + «b» + «c» = «s»$.", a=m(dp[0]), b=m(dp[1]), c=m(dp[2]), s=m(sum(dp))),
              fx(r"$PI = «s» / 50{,}000 = «v»$.", s=m(sum(dp)), v=f"{pi_:.3f}"), r"$PI > 1 \Leftrightarrow NPV > 0$.", final=fx(r"$PI = «v» > 1$ ⇒ הפרויקט כדאי (NPV = $«n»$ ₪).", v=f"{pi_:.3f}", n=m(sum(dp) - 50000))), "medium", topic="pb")
    add("payback", "multiple_choice", "חיסרון של Payback", "מהו החיסרון העיקרי של שיטת ה-Payback הפשוטה?", "היא מתעלמת מערך הזמן של כסף ומתזרימים שאחרי תקופת ההחזר.",
        steps("Payback סופר רק כמה זמן לוקח לכסות את ההשקעה.", "הוא אינו מהווה את התזרימים — כלומר מתעלם מערך הזמן של כסף.", "והוא מתעלם מכל התזרימים שאחרי נקודת ההחזר, שיכולים להיות גדולים מאוד.", final="מתעלמת מערך הזמן ומתזרימים שאחרי ההחזר."), "easy",
        [("מתעלמת מערך הזמן של כסף ומתזרימים שאחרי תקופת ההחזר", True), ("מורכבת מדי לחישוב", False), ("דורשת ידיעת עלות ההון", False), ("תמיד נותנת NPV שלילי", False)], "pb")

    # ======================= לוחות סילוקין =======================
    add("amort_def", "definition", "לוח סילוקין", "הגדירו מהו לוח סילוקין ואילו עמודות הוא כולל.", "לוח סילוקין הוא טבלה המפרטת את פירעון ההלוואה לאורך זמן.",
        steps("**הגדרה:** לוח סילוקין (Amortization schedule) הוא טבלה שמראה כיצד הלוואה נפרעת בכל תקופה.", "**עמודות:** יתרת פתיחה, תשלום כולל, רכיב הריבית ($r\\cdot B_{t-1}$), רכיב הקרן (תשלום פחות ריבית) ויתרת סגירה.",
              "**בדיקות:** סך הקרן ששולמה שווה לסכום ההלוואה, והיתרה הסופית היא 0.", final="טבלה המפרטת בכל תקופה: יתרת פתיחה, תשלום, ריבית, קרן ויתרת סגירה."), "easy", topic="amort")
    add("pmt", "calculation", "תשלום בלוח שפיצר", r"הלוואה של $100{,}000$ ₪ בריבית שנתית $6\%$ ל-5 שנים, בתשלומים שנתיים שווים (לוח שפיצר). מהו התשלום השנתי?", fx(r"$PMT \approx «v»$ ₪", v=m(SP_PAY)),
        steps(r"הנוסחה: $PMT = \dfrac{L \cdot r}{1-(1+r)^{-n}}$.", r"מציבים: $L=100{,}000$, $r=0.06$, $n=5$ ⇒ מונה: $100{,}000 \cdot 0.06 = 6{,}000$.",
              fx(r"מכנה: $1 - 1.06^{-5} = 1 - «a» = «b»$.", a=f"{1.06 ** -5:.6f}", b=f"{1 - 1.06 ** -5:.6f}"), fx(r"$PMT = 6{,}000 / «b» = «v»$.", b=f"{1 - 1.06 ** -5:.6f}", v=m(SP_PAY)),
              final=fx(r"$«v»$ ₪ בכל שנה (סה״כ $«t»$ ₪).", v=m(SP_PAY), t=m(SP_PAY * 5))), "medium", topic="amort")
    mp = pmt(.03 / 12, 240, 300000)
    add("pmt_monthly", "calculation", "משכנתא חודשית", r"הלוואה של $300{,}000$ ₪ בריבית נומינלית $3\%$ בשנה, ל-20 שנה, בתשלומים חודשיים שווים. מהו התשלום החודשי וסך הריבית?", fx(r"$PMT \approx «v»$ ₪ לחודש; סך ריבית $«i»$ ₪", v=m(mp), i=m(mp * 240 - 300000)),
        steps(r"מעבירים לחודשים: $r = 0.03/12 = 0.0025$, $n = 20 \cdot 12 = 240$.", fx(r"מציבים: $PMT = \dfrac{300{,}000 \cdot 0.0025}{1 - 1.0025^{-240}} = \dfrac{750}{«b»}$.", b=f"{1 - 1.0025 ** -240:.6f}"),
              fx(r"$PMT = «v»$ ₪.", v=m(mp)), fx(r"סך התשלומים: $240 \cdot «v» = «t»$; סך הריבית: $«t» - 300{,}000 = «i»$.", v=m(mp), t=m(mp * 240), i=m(mp * 240 - 300000)),
              final=fx(r"$«v»$ ₪ לחודש, סך ריבית $«i»$ ₪.", v=m(mp), i=m(mp * 240 - 300000))), "hard", topic="amort")
    add("first_interest", "calculation", "פירוק התשלום הראשון", fx(r"הלוואת שפיצר של $500{,}000$ ₪, ריבית נומינלית $4\%$ בשנה, 25 שנה, תשלומים חודשיים (התשלום החודשי: $«p»$ ₪). כמה מהתשלום הראשון הוא ריבית וכמה קרן?", p=m(MPMT)),
        fx(r"ריבית $«i»$ ₪; קרן $«k»$ ₪", i=m(500000 * .04 / 12), k=m(MPMT - 500000 * .04 / 12)),
        steps(r"הריבית החודשית: $0.04/12 = 0.003333$.", fx(r"ריבית התשלום הראשון: $500{,}000 \cdot 0.003333 = «i»$ ₪.", i=m(500000 * .04 / 12)),
              fx(r"קרן = תשלום − ריבית: $«p» - «i» = «k»$ ₪.", p=m(MPMT), i=m(500000 * .04 / 12), k=m(MPMT - 500000 * .04 / 12)), fx(r"יתרה אחרי התשלום: $500{,}000 - «k» = «b»$ ₪.", k=m(MPMT - 500000 * .04 / 12), b=m(500000 - (MPMT - 500000 * .04 / 12))),
              final=fx(r"ריבית $«i»$ ₪ וקרן $«k»$ ₪ — רוב התשלום בתחילת הדרך הוא ריבית.", i=m(500000 * .04 / 12), k=m(MPMT - 500000 * .04 / 12))), "medium", topic="amort")
    r2 = SP[1]
    add("row2", "calculation", "השורה השנייה בלוח", fx(r"בהלוואת שפיצר של $100{,}000$ ₪, ריבית $6\%$, 5 שנים — התשלום השנתי $«p»$ ₪ ויתרת הסגירה בשנה 1 היא $«b»$ ₪. מלאו את השורה של שנה 2: ריבית, קרן ויתרת סגירה.", p=m(SP_PAY), b=m(SP[0][5])),
        fx(r"ריבית $«i»$; קרן $«k»$; יתרת סגירה $«c»$", i=m(r2[3]), k=m(r2[4]), c=m(r2[5])),
        steps(fx(r"יתרת הפתיחה של שנה 2 = יתרת הסגירה של שנה 1 = $«b»$.", b=m(r2[1])), fx(r"ריבית: $«b» \cdot 6\% = «i»$.", b=m(r2[1]), i=m(r2[3])), fx(r"קרן: $«p» - «i» = «k»$.", p=m(SP_PAY), i=m(r2[3]), k=m(r2[4])),
              fx(r"יתרת סגירה: $«b» - «k» = «c»$.", b=m(r2[1]), k=m(r2[4]), c=m(r2[5])), final=fx(r"ריבית $«i»$, קרן $«k»$, יתרת סגירה $«c»$.", i=m(r2[3]), k=m(r2[4]), c=m(r2[5]))), "medium", topic="amort")
    bk = SP[2][5]
    add("balance_k", "calculation", "יתרה לאחר k תשלומים", r"בהלוואת השפיצר ($100{,}000$ ₪, $6\%$, 5 שנים), מהי יתרת החוב אחרי 3 תשלומים? השתמשו בנוסחה.", fx(r"$B_3 \approx «v»$ ₪", v=m(bk)),
        steps(r"הנוסחה: $B_k = L(1+r)^k - PMT \cdot \dfrac{(1+r)^k - 1}{r}$.", fx(r"$(1.06)^3 = «a»$ ⇒ $L(1+r)^3 = «b»$.", a=f"{1.06 ** 3:.6f}", b=m(100000 * 1.06 ** 3)),
              fx(r"$\dfrac{1.06^3-1}{0.06} = «a»$ ⇒ $PMT \cdot «a» = «b»$.", a=f"{(1.06 ** 3 - 1) / .06:.6f}", b=m(SP_PAY * (1.06 ** 3 - 1) / .06)),
              fx(r"$B_3 = «a» - «b» = «v»$.", a=m(100000 * 1.06 ** 3), b=m(SP_PAY * (1.06 ** 3 - 1) / .06), v=m(bk)), "אפשר לוודא מול לוח הסילוקין: זו יתרת הסגירה בשורה של שנה 3.", final=fx(r"$«v»$ ₪", v=m(bk))), "hard", topic="amort")
    add("spitzer_prop", "multiple_choice", "מבנה התשלום בשפיצר", "בלוח שפיצר, ככל שהזמן עובר, החלק של הקרן בתוך התשלום הקבוע:", "גדל, והחלק של הריבית קטן.",
        steps(r"התשלום קבוע: $PMT$ = ריבית + קרן.", r"הריבית בכל תקופה = $r \cdot$ יתרה, והיתרה קטנה עם הזמן ⇒ הריבית קטנה.", "מכיוון שהתשלום קבוע, מה שהריבית מפסידה — הקרן מרוויחה.", final="הקרן גדלה והריבית קטנה."), "medium",
        [("גדל, והריבית קטנה", True), ("קטן, והריבית גדלה", False), ("נשאר קבוע", False), ("תלוי רק בשיעור המדד", False)], "amort")
    add("eq_const", "true_false", "תשלום בקרן שווה", "נכון או לא נכון: בלוח קרן שווה התשלום הכולל (קרן + ריבית) קבוע בכל התקופות.", "לא נכון",
        steps("בקרן שווה החזר הקרן קבוע ($L/n$).", "הריבית מחושבת על היתרה, והיתרה קטנה ⇒ הריבית יורדת.", "לכן התשלום הכולל (קרן + ריבית) **יורד** לאורך זמן.", final="לא נכון."), "easy", [("True", False), ("False", True)], "amort")
    add("eq_first", "calculation", "תשלום ראשון בקרן שווה", r"הלוואה של $120{,}000$ ₪, ריבית $5\%$ בשנה, 10 שנים, לוח קרן שווה. מהו התשלום הכולל בשנה הראשונה?", fx(r"$«v»$ ₪", v=m(18000, 0)),
        steps(r"החזר קרן קבוע: $120{,}000 / 10 = 12{,}000$ ₪.", r"ריבית בשנה הראשונה על כל היתרה: $120{,}000 \cdot 0.05 = 6{,}000$ ₪.", r"תשלום כולל: $12{,}000 + 6{,}000 = 18{,}000$ ₪.", final=r"$18{,}000$ ₪."), "medium", topic="amort")
    add("eq_total", "calculation", "סך הריבית בקרן שווה", r"באותה הלוואה ($120{,}000$ ₪, $5\%$, 10 שנים, קרן שווה) — מהו סך הריבית שתשולם?", fx(r"$«v»$ ₪", v=m(33000, 0)),
        steps(r"הריבית בשנה $t$ היא $r \cdot (L - (t-1)\cdot L/n)$ — סדרה חשבונית יורדת.", r"סך הריבית: $r \cdot L \cdot \dfrac{n+1}{2}$.", r"מציבים: $0.05 \cdot 120{,}000 \cdot \dfrac{11}{2} = 6{,}000 \cdot 5.5 = 33{,}000$.", final=r"$33{,}000$ ₪."), "hard", topic="amort")
    add("balloon", "calculation", "הלוואת בולט", r"הלוואת בולט של $200{,}000$ ₪ ל-4 שנים בריבית $5\%$ בשנה (ריבית משולמת מדי שנה, הקרן בסוף). מהם התשלומים וסך הריבית?", fx(r"שלושה תשלומים של $«i»$, ובשנה 4: $«l»$; סך ריבית $«t»$", i=m(10000, 0), l=m(210000, 0), t=m(40000, 0)),
        steps(r"ריבית שנתית קבועה (הקרן לא יורדת): $200{,}000 \cdot 0.05 = 10{,}000$ ₪.", r"בשנים 1–3 משלמים ריבית בלבד: $10{,}000$ ₪ בכל שנה.", r"בשנה 4: ריבית $10{,}000$ + כל הקרן $200{,}000$ = $210{,}000$ ₪.", r"סך הריבית: $4 \cdot 10{,}000 = 40{,}000$ ₪.", final=r"$10{,}000$ ×3, ואז $210{,}000$; סך ריבית $40{,}000$ ₪."), "medium", topic="amort")
    add("which_more_interest", "multiple_choice", "סך הריבית בין שיטות", "עבור אותה הלוואה, אותה ריבית ואותה תקופה — איזו שיטה גוררת סך ריבית גבוה יותר: שפיצר או קרן שווה?", "שפיצר." if not EQ_LESS else "קרן שווה.",
        steps("בקרן שווה הקרן נפרעת בקצב קבוע ולכן היתרה יורדת מהר יותר בתחילת הדרך.", "בשפיצר התשלום הראשון נמוך יותר, ולכן הקרן יורדת לאט יותר בהתחלה והריבית מחושבת על יתרה גבוהה זמן רב יותר.",
              fx(r"בדוגמה ($100{,}000$, $6\%$, 5 שנים): סך ריבית בשפיצר $«a»$ לעומת $«b»$ בקרן שווה.", a=m(TOT["sp"]), b=m(TOT["eq"])), final="שפיצר — סך הריבית גבוה יותר." if not EQ_LESS else "קרן שווה."), "medium",
        [("שפיצר", not EQ_LESS), ("קרן שווה", EQ_LESS), ("זהה", False)], "amort")
    add("compare_pv", "multiple_choice", "ערך נוכחי של תשלומי ההלוואה", "מהוונים את כל תשלומי הלוואה (בשפיצר, קרן שווה או בולט) בשיעור הריבית של ההלוואה. מה מקבלים?", "בדיוק את סכום ההלוואה, בכל השיטות.",
        steps(r"הלוואה היא בעצם סדרת תשלומים שהערך הנוכחי שלה, בשיעור ריבית ההלוואה, שווה לסכום שהתקבל.", fx(r"בדוגמה: $PV$ של תשלומי שפיצר $= «a»$; של קרן שווה $= «b»$; של בולט $= «c»$.", a=m(npv(R, [0] + [x[2] for x in SP])), b=m(npv(R, [0] + [x[2] for x in EQ])), c=m(npv(R, [0] + [x[2] for x in BL]))),
              "לכן אף שיטה אינה זולה יותר במונחי NPV — ההבדל הוא בתזמון ובנטל התזרימי.", final="בדיוק את סכום ההלוואה."), "hard",
        [("בדיוק את סכום ההלוואה בכל השיטות", True), ("יותר מסכום ההלוואה בשפיצר", False), ("פחות מסכום ההלוואה בבולט", False), ("תלוי בשיטה", False)], "amort")
    return q


# ---------------------------------------------------------------- lessons
def build_course(qid):
    """Returns the course structure: list of modules -> (title, summary, lessons[(title, minutes, summary, blocks)])."""
    cf_rows = [(t, m(c, 0), m(c / (1 + r10) ** t)) for t, c in enumerate(P_FLOW)]
    pv_rows = [(t, m(c, 0), f"{(1 + r10) ** t:.4f}", m(c / (1 + r10) ** t)) for t, c in enumerate(P_FLOW)]
    profile = [(f"{int(r * 100)}%", m(npv(r, P_FLOW))) for r in (0, .05, .10, .15, .17, .20, .25)]
    ab_prof = [(f"{int(r * 100)}%", m(npv(r, A)), m(npv(r, B)), "A" if npv(r, A) > npv(r, B) else "B") for r in (0, .05, .10, .15, .20, .25)]
    comp = [("שנתית", 1), ("חצי-שנתית", 2), ("רבעונית", 4), ("חודשית", 12), ("יומית", 365)]
    comp_rows = [(a, f"{(1 + .12 / k) ** k - 1:.4%}") for a, k in comp] + [("רציפה", f"{math.exp(.12) - 1:.4%}")]
    growth_rows = [(t, m(10_000 * 1.06 ** t), m(10_000 * (1 + .06 * t))) for t in range(0, 6)]
    cum_rows, cum, dc = [], 0, 0
    for t, c in enumerate(P_FLOW):
        cum += c
        dc += c / (1 + r10) ** t
        cum_rows.append((t, m(c, 0), m(cum, 0), m(dc)))
    sens = [(f"{int(r * 100)}%", m(npv(r, CASE_FLOW))) for r in (.05, .09, .15, .20, .25)]
    sp_total, eq_total, bl_total = TOT["sp"], TOT["eq"], TOT["bl"]
    comparison = tbl(["שיטה", "תשלום ראשון", "תשלום אחרון", "סך ריבית", "סך תשלומים"], [
        ("שפיצר (Level payment)", m(SP[0][2]), m(SP[-1][2]), m(sp_total), m(sum(x[2] for x in SP))),
        ("קרן שווה (Equal principal)", m(EQ[0][2]), m(EQ[-1][2]), m(eq_total), m(sum(x[2] for x in EQ))),
        ("תשלום בולט (Balloon)", m(BL[0][2]), m(BL[-1][2]), m(bl_total), m(sum(x[2] for x in BL)))])
    monthly_total = MPMT * 300
    xl_layout = tbl(["תא", "A", "B"], [(1, "שנה", "תזרים"), (2, "0", "-100,000"), (3, "1", "25,000"), (4, "2", "30,000"), (5, "3", "35,000"), (6, "4", "40,000"), (7, "5", "30,000")])

    M1 = ("מודול 1: יסודות — ערך הזמן של כסף", "ערך הזמן של כסף הוא אבן היסוד של כל החלטת השקעה ומימון: שקל היום שווה יותר משקל מחר, ולכן מהוונים תזרימים לנקודת זמן אחת לפני שמשווים או מסכמים אותם.", [
        ("למה שקל היום שווה יותר משקל מחר?", 25, "שקל שבידינו היום ניתן להשקעה ולהניב ריבית, ולכן שווה יותר משקל עתידי. עם $FV=PV(1+r)^n$ ו-$PV=FV/(1+r)^n$ מעבירים סכומים בין נקודות זמן.", [
            video(),
            T("כסף שאנחנו מקבלים היום שווה יותר מאותו סכום שנקבל בעתיד, מכמה סיבות: אפשר להשקיע אותו ולהרוויח **ריבית**, הציפייה ל**אינפלציה** שמשחיקה את כוח הקנייה, וה**סיכון** שהכסף בעתיד לא יתקבל בפועל. מושג זה נקרא **ערך הזמן של כסף** (Time Value of Money, TVM).\n\nבקורס הזה נלמד להעביר סכומי כסף בין נקודות זמן, להעריך פרויקטים באמצעות **NPV** ו-**IRR**, ולבנות **לוחות סילוקין** להלוואות.", "מבוא"),
            C("**הרעיון המרכזי:** אי אפשר לחבר או להשוות סכומים שנופלים בנקודות זמן שונות. קודם מעבירים אותם לאותה נקודת זמן (בדרך כלל להיום), ורק אחר כך משווים.", "important"),
            F("Future Value (FV)", r"FV = PV \cdot (1+r)^n", "ערך עתידי של סכום PV לאחר n תקופות בריבית r לתקופה."),
            F("Present Value (PV)", r"PV = \frac{FV}{(1+r)^n}", "ערך נוכחי של סכום עתידי. הפעולה נקראת היוון (Discounting) ו-r נקרא שיעור ההיוון (Discount rate)."),
            EX("דוגמה: ריבית דריבית מול ריבית פשוטה", f"מפקידים $10{{,}}000$ ₪ בריבית שנתית של $6\\%$. אחרי 5 שנים עם ריבית דריבית:\n\n$FV = 10{{,}}000 \\cdot 1.06^5 = {m(10000 * 1.06 ** 5)}$ ₪\n\nהטבלה משווה בין ריבית דריבית לריבית פשוטה:\n\n" + tbl(["שנה", "ריבית דריבית (₪)", "ריבית פשוטה (₪)"], growth_rows) + "\n\nההפרש גדל משנה לשנה — זה כוחה של הריבית דריבית."),
            ("question", {"question_id": qid["pv"], "show_answer": "after_attempt"}),
            ("question", {"question_id": qid["fv"], "show_answer": "after_attempt"}),
            S("- שקל היום שווה יותר משקל מחר בגלל ריבית, אינפלציה וסיכון.\n- $FV = PV(1+r)^n$ ו-$PV = FV/(1+r)^n$.\n- משווים סכומים רק אחרי שהעברנו אותם לאותה נקודת זמן."),
        ]),
        ("ציר זמן ותזרימי מזומנים (Cash Flows)", 25, "ציר זמן מסדר את התזרימים (CF) לפי תקופות: יציאות בסימן שלילי, כניסות בסימן חיובי; ההשקעה ההתחלתית נמצאת ב-$t=0$.", [
            video(),
            T("כדי לנתח השקעה מציירים **ציר זמן**: $t=0$ הוא היום, $t=1$ סוף התקופה הראשונה וכן הלאה. כל **תזרים מזומנים** (Cash Flow, CF) מסומן בסימן: **שלילי** ליציאה (השקעה, תשלום) ו**חיובי** לכניסה (הכנסה, החזר).\n\nהנחת העבודה הנפוצה: התזרים מתרחש **בסוף** התקופה, וההשקעה ההתחלתית מתרחשת ב-$t=0$ ולכן אינה מהוונת.", "ציר זמן"),
            F("Present Value of multiple cash flows", r"PV = \sum_{t=1}^{n} \frac{CF_t}{(1+r)^t}", "הערך הנוכחי של סדרת תזרימים הוא סכום הערכים הנוכחיים של כל אחד מהם."),
            EX("דוגמה: פרויקט עם חמישה תזרימים", f"פרויקט דורש השקעה של $100{{,}}000$ ₪ ומניב בסוף שנים 1 עד 5: $25{{,}}000$, $30{{,}}000$, $35{{,}}000$, $40{{,}}000$ ו-$30{{,}}000$ ₪. נהוון בשיעור $10\\%$:\n\n" + tbl(["t", "תזרים (CF)", "גורם היוון $(1+r)^t$", "ערך נוכחי"], pv_rows) + f"\n\nסכום הערכים הנוכחיים של התקבולים: ${m(sum(c / (1 + r10) ** (t + 1) for t, c in enumerate(P_CF)))}$ ₪. את הפרויקט הזה נשתמש בו שוב במודולים הבאים."),
            C("**טעות נפוצה:** לחבר תזרימים משנים שונות בלי להוון. הסכום $25{,}000+30{,}000+\\dots$ אינו הערך של הפרויקט.", "warning"),
            S("- ציר זמן: $t=0$ היום; יציאות שליליות, כניסות חיוביות.\n- $PV = \\sum CF_t/(1+r)^t$.\n- ההשקעה ההתחלתית ב-$t=0$ אינה מהוונת."),
        ]),
        ("אנונה ופרפטואיטי (Annuity & Perpetuity)", 30, "Annuity היא סדרת תשלומים שווים לאורך תקופות; Perpetuity היא סדרה אינסופית. לכולן נוסחאות סגורות שחוסכות היוון תזרים אחר תזרים.", [
            video(),
            T("**Annuity** היא סדרה של תשלומים שווים ($C$) במרווחי זמן קבועים, למשל החזר הלוואה או שכר דירה. **Perpetuity** היא סדרה אינסופית של תשלומים שווים, למשל מניה ש\"מחלקת\" דיבידנד קבוע לנצח. הנוסחאות מתבססות על סכום של סדרה הנדסית.", "הגדרות"),
            F("PV of Annuity", r"PV = C \cdot \frac{1-(1+r)^{-n}}{r}", "ערך נוכחי של n תשלומים שווים בסוף כל תקופה."),
            F("FV of Annuity", r"FV = C \cdot \frac{(1+r)^{n}-1}{r}"),
            F("Perpetuity", r"PV = \frac{C}{r}", "ערך נוכחי של תשלום קבוע C לנצח."),
            F("Growing Perpetuity", r"PV = \frac{C_1}{r-g}, \quad r>g", "תשלום ראשון C₁ בעוד תקופה, שגדל בקצב קבוע g."),
            EX("דוגמאות", f"**Annuity:** $12{{,}}000$ ₪ בשנה למשך 5 שנים, $r=8\\%$: $PV = 12{{,}}000 \\cdot \\frac{{1-1.08^{{-5}}}}{{0.08}} = {m(12000 * (1 - 1.08 ** -5) / .08)}$ ₪.\n\n**Perpetuity:** $6{{,}}000$ ₪ בשנה לנצח, $r=5\\%$: $PV = 6{{,}}000 / 0.05 = {m(6000 / .05, 0)}$ ₪.\n\n**Growing Perpetuity:** דיבידנד ראשון $5$ ₪ שגדל $3\\%$ בשנה, $r=10\\%$: $PV = 5/(0.10-0.03) = {m(5 / .07)}$ ₪."),
            ("question", {"question_id": qid["annuity"], "show_answer": "after_attempt"}),
            ("question", {"question_id": qid["perp"], "show_answer": "after_attempt"}),
            S("- Annuity: $PV = C\\cdot\\frac{1-(1+r)^{-n}}{r}$.\n- Perpetuity: $PV = C/r$; Growing perpetuity: $PV = C_1/(r-g)$ עבור $r>g$.\n- הנוסחאות מניחות תשלום בסוף כל תקופה."),
        ]),
        ("ריבית נומינלית ואפקטיבית (APR / EAR)", 20, "ריבית נומינלית (APR) אינה משקפת את העלות האמיתית כשיש capitalization תכוף; הריבית האפקטיבית (EAR) כן, ולכן משווים ביניהן רק במונחי EAR.", [
            video(),
            T("בהצעות הלוואה מופיעה בדרך כלל ריבית **נומינלית שנתית** (APR), אך הריבית מחושבת בפועל כל חודש או רבעון. כדי להשוות בין הצעות מחשבים את **הריבית האפקטיבית השנתית** (Effective Annual Rate, EAR) — הריבית השנתית שנותנת את אותה תוצאה בדיוק.", "מדוע צריך EAR"),
            F("Effective Annual Rate", r"EAR = \left(1+\frac{APR}{m}\right)^{m}-1", "m הוא מספר התקופות בשנה שבהן הריבית מתווספת לקרן."),
            EX("דוגמה: APR של 12%", "הטבלה מציגה את ה-EAR עבור APR של $12\\%$ בתדירויות שונות:\n\n" + tbl(["תדירות capitalization", "EAR"], comp_rows) + "\n\nשימו לב: התדירות הגבוהה יותר מגדילה את ה-EAR, אך בשיעור הולך ופוחת. עבור capitalization רציף $EAR = e^{APR}-1$."),
            ("question", {"question_id": qid["ear"], "show_answer": "after_attempt"}),
            S("- APR היא ריבית נקובה; EAR היא העלות/התשואה האמיתית בשנה.\n- $EAR = (1+APR/m)^m - 1$.\n- משווים הצעות לפי EAR."),
        ]),
    ])
    M2 = ("מודול 2: ערך נוכחי נקי (NPV)", "NPV הוא סכום הערכים הנוכחיים של כל תזרימי הפרויקט, כולל ההשקעה ההתחלתית. הוא מודד את תוספת הערך בשקלים של היום ומהווה את קריטריון ההחלטה המועדף בתורת המימון.", [
        ("מהו NPV וכלל ההחלטה", 25, "$NPV>0$ — הפרויקט מוסיף ערך וכדאי לקבלו; $NPV<0$ — דוחים; $NPV=0$ — אדישות. ה-NPV מודד תוספת ערך בשקלים של היום.", [
            video(),
            T("**ערך נוכחי נקי** (Net Present Value, NPV) הוא ההפרש בין הערך הנוכחי של כל התקבולים העתידיים לבין עלות ההשקעה. הוא עונה על השאלה: \"בכמה שקלים של היום עשיר יותר החברה אם תבצע את הפרויקט, אחרי שהתחשבנו בעלות ההון?\"", "הגדרה"),
            F("Net Present Value", r"NPV = \sum_{t=0}^{n} \frac{CF_t}{(1+r)^t} = -I_0 + \sum_{t=1}^{n}\frac{CF_t}{(1+r)^t}", "I₀ היא ההשקעה ההתחלתית, r עלות ההון (שיעור ההיוון)."),
            T(tbl(["תוצאה", "פירוש", "החלטה"], [("$NPV > 0$", "הפרויקט מרוויח יותר מעלות ההון", "לקבל"), ("$NPV = 0$", "הפרויקט מחזיר בדיוק את עלות ההון", "אדישות"), ("$NPV < 0$", "הפרויקט מרוויח פחות מעלות ההון", "לדחות")]), "כלל ההחלטה"),
            C("**מדוע NPV הוא הקריטריון המועדף?** (1) הוא מתחשב בערך הזמן של כסף, (2) הוא מתחשב בכל התזרימים, (3) הוא מודד תוספת ערך בשקלים, ולכן ה-NPV של פרויקטים עצמאיים ניתן לחיבור.", "tip"),
            ("question", {"question_id": qid["npv_rule"], "show_answer": "after_attempt"}),
            ("question", {"question_id": qid["npv_calc"], "show_answer": "after_attempt"}),
            S("- $NPV=\\sum CF_t/(1+r)^t$ כולל $CF_0$.\n- $NPV>0$ → לקבל; $NPV<0$ → לדחות.\n- NPV הוא תוספת ערך בשקלים של היום."),
        ]),
        ("דוגמה מלאה צעד אחר צעד", 30, f"בפרויקט הדוגמה, NPV בשיעור $10\\%$ הוא כ-{m(P_NPV)} ₪ (חיובי — כדאי); ה-NPV יורד ככל ששיעור ההיוון עולה.", [
            video(),
            T(f"נחשב NPV לפרויקט שהכרנו: השקעה של $100{{,}}000$ ₪, תזרימים $25{{,}}000$, $30{{,}}000$, $35{{,}}000$, $40{{,}}000$, $30{{,}}000$ בשנים 1–5, ושיעור היוון $10\\%$.\n\n**שלב 1:** מסדרים את התזרימים על ציר הזמן.\n\n**שלב 2:** מהוונים כל תזרים:\n\n" + tbl(["t", "CF (₪)", "ערך נוכחי (₪)"], cf_rows) + f"\n\n**שלב 3:** מסכמים: $NPV = {m(P_NPV)}$ ₪.\n\n**שלב 4 — החלטה:** $NPV>0$, ולכן הפרויקט כדאי.", "פתרון"),
            F("חישוב", r"NPV = -100{,}000 + \frac{25{,}000}{1.10} + \frac{30{,}000}{1.10^2} + \frac{35{,}000}{1.10^3} + \frac{40{,}000}{1.10^4} + \frac{30{,}000}{1.10^5}"),
            EX("רגישות לשיעור ההיוון (NPV Profile)", "נחשב את ה-NPV של אותו פרויקט בשיעורי היוון שונים:\n\n" + tbl(["שיעור היוון", "NPV (₪)"], profile) + f"\n\nה-NPV יורד ככל ששיעור ההיוון עולה, ומתאפס בסביבות $r \\approx {p(P_IRR)}$ — זהו ה-IRR של הפרויקט, ועליו נלמד במודול הבא."),
            C("שיעור היוון גבוה מקטין את הערך הנוכחי של תזרימים רחוקים יותר בעוד שההשקעה (ב-$t=0$) אינה מושפעת; לכן פרויקטים עם תקבולים מאוחרים רגישים יותר לשיעור ההיוון.", "info"),
            S(f"- $NPV = {m(P_NPV)}$ ₪ ב-$r=10\\%$ → הפרויקט כדאי.\n- NPV יורד כשהריבית עולה.\n- הנקודה שבה $NPV=0$ היא ה-IRR (≈ {p(P_IRR)})."),
        ]),
        ("בחירת שיעור ההיוון: WACC ו-CAPM", 30, "שיעור ההיוון משקף את עלות ההון ואת סיכון הפרויקט. מחשבים אותו באמצעות WACC (משוקלל לפי מבנה ההון) ו-CAPM (עלות ההון העצמי).", [
            video(),
            T("שיעור ההיוון הוא **התשואה הנדרשת** על הפרויקט בהתחשב בסיכונו — מה המשקיעים יכלו להרוויח על השקעה אחרת באותה רמת סיכון (עלות אלטרנטיבית). שני מושגים מרכזיים:\n\n- **CAPM** (Capital Asset Pricing Model) — מעריך את עלות ההון העצמי $r_E$ לפי הסיכון השיטתי ($\\beta$).\n- **WACC** (Weighted Average Cost of Capital) — עלות ההון הממוצעת המשוקללת של החברה, כשהחוב מוזל בגלל מס חברות.", "מהו שיעור ההיוון"),
            F("CAPM", r"r_E = r_f + \beta \cdot (r_m - r_f)", "r_f ריבית חסרת סיכון, β רגישות לשוק, r_m תשואת השוק."),
            F("WACC", r"WACC = \frac{E}{V}\, r_E + \frac{D}{V}\, r_D\,(1-T_c)", "E הון עצמי, D חוב, V = E + D, T_c שיעור מס חברות."),
            EX("דוגמה", f"נתון: $r_f=4\\%$, $\\beta=1.2$, $r_m=9\\%$ ⇒ $r_E = 4\\% + 1.2\\cdot(9\\%-4\\%) = {p(.04 + 1.2 * .05, 1)}$.\n\nמבנה ההון: $60\\%$ הון עצמי, $40\\%$ חוב בעלות $6\\%$, מס חברות $23\\%$:\n\n$WACC = 0.60 \\cdot {p(.04 + 1.2 * .05, 1)} + 0.40 \\cdot 6\\% \\cdot (1-0.23) = {p(.6 * (.04 + 1.2 * .05) + .4 * .06 * .77)}$."),
            C("**עיקרון:** שיעור ההיוון צריך להתאים לסיכון **הפרויקט**, ולא בהכרח לסיכון החברה. פרויקט מסוכן יותר מהפעילות הרגילה דורש שיעור היוון גבוה יותר.", "warning"),
            S("- שיעור ההיוון = התשואה הנדרשת בהתחשב בסיכון.\n- $r_E = r_f + \\beta(r_m - r_f)$.\n- $WACC = \\frac{E}{V}r_E + \\frac{D}{V}r_D(1-T_c)$."),
        ]),
        ("NPV באקסל וטעויות נפוצות", 25, "באקסל, =NPV מהווננת את הערך הראשון בטווח לתקופה 1, ולכן ההשקעה ההתחלתית מתווספת מחוץ לפונקציה. טעויות נפוצות נוספות: עלויות שקועות, אינפלציה, ושימוש בתזרים חשבונאי במקום תזרים מזומנים.", [
            video(),
            T("הפונקציה `NPV(rate, value1, ...)` באקסל **מהווננת את הערך הראשון לתקופה 1**. לכן, אם ההשקעה ההתחלתית היא בתא B2 והתקבולים ב-B3:B7:\n\n`=NPV(10%, B3:B7) + B2`\n\nואם התאריכים אינם במרווחים שווים — משתמשים ב-`XNPV(rate, values, dates)`.", "אקסל"),
            T(xl_layout, "דוגמה לפריסת הנתונים"),
            C("**טעות קלאסית:** `=NPV(10%, B2:B7)` — כולל את ההשקעה בטווח. התוצאה מהווננת את ההשקעה לתקופה 1 ולכן **שגויה**.", "warning"),
            T("**טעויות מושגיות נפוצות בהערכת פרויקטים:**\n\n1. **עלויות שקועות** (Sunk costs) — הוצאות שכבר בוצעו ואינן תלויות בהחלטה אינן חלק מהתזרים.\n2. **עלות אלטרנטיבית** (Opportunity cost) — משאב קיים שבו נעשה שימוש (קרקע, מבנה) הוא עלות גם אם אין תשלום חדש.\n3. **עקביות באינפלציה** — תזרימים נומינליים מהוונים בשיעור נומינלי; תזרימים ריאליים בשיעור ריאלי.\n4. **מסים והפחת** — משתמשים בתזרים **לאחר מס**; הפחת אינו תזרים אך יוצר חיסכון במס (מס מגן).\n5. **הון חוזר** — גידול בהון החוזר הוא יציאת מזומנים.\n6. **תזרים מצטבר** (Incremental cash flows) — רק ההפרש שנגרם בגלל הפרויקט.", "טעויות נפוצות"),
            ("question", {"question_id": qid["excel_npv"], "show_answer": "after_attempt"}),
            S("- `=NPV(r, CF1:CFn) + CF0`; לתאריכים לא שווים: `XNPV`.\n- מתעלמים מעלויות שקועות, כוללים עלות אלטרנטיבית.\n- שומרים על עקביות נומינלי/ריאלי ועובדים עם תזרים לאחר מס."),
        ]),
    ])
    M3 = ("מודול 3: שיעור תשואה פנימי (IRR)", "IRR הוא שיעור ההיוון שמאפס את ה-NPV. הוא נוח לתקשורת (אחוזים) אך חשוף למגבלות, ולכן משלימים אותו ב-NPV וב-MIRR.", [
        ("IRR — הגדרה וחישוב", 30, f"IRR הוא ה-$r$ שעבורו $NPV=0$; בפרויקט הדוגמה הוא כ-{p(P_IRR)}. מחשבים בניסוי וטעייה, אינטרפולציה או בפונקציה IRR באקסל.", [
            video(),
            T("**שיעור תשואה פנימי** (Internal Rate of Return, IRR) הוא שיעור ההיוון שבו ה-NPV של הפרויקט שווה לאפס. אפשר לראות בו את **התשואה השנתית** של הפרויקט על הכסף המושקע בו, בהנחות מסוימות.", "הגדרה"),
            F("Internal Rate of Return", r"0 = \sum_{t=0}^{n} \frac{CF_t}{(1+IRR)^t}", "אין פתרון אלגברי כללי עבור n>4; מחשבים באופן נומרי."),
            EX("חישוב באינטרפולציה", f"בפרויקט הדוגמה: $NPV(15\\%) = {m(npv(.15, P_FLOW))}$ ו-$NPV(20\\%) = {m(npv(.20, P_FLOW))}$. ה-IRR נמצא בין 15% ל-20%. באינטרפולציה לינארית:\n\n$IRR \\approx 15\\% + 5\\% \\cdot \\frac{{{m(npv(.15, P_FLOW))}}}{{{m(npv(.15, P_FLOW))} - ({m(npv(.20, P_FLOW))})}} \\approx {p(.15 + .05 * npv(.15, P_FLOW) / (npv(.15, P_FLOW) - npv(.20, P_FLOW)))}$\n\nהערך המדויק: $IRR = {p(P_IRR)}$. באקסל: `=IRR(B2:B7)` (כאן ההשקעה **כן** נכללת בטווח)."),
            C("**כלל ההחלטה:** מקבלים פרויקט אם $IRR > r$ (עלות ההון / Hurdle rate), ודוחים אם $IRR < r$.", "important"),
            ("question", {"question_id": qid["irr_def"], "show_answer": "after_attempt"}),
            S(f"- $IRR$: שיעור ההיוון שבו $NPV=0$ (≈ {p(P_IRR)} בדוגמה).\n- $IRR > r$ → לקבל.\n- חישוב: ניסוי וטעייה, אינטרפולציה, או `IRR` באקסל."),
        ]),
        ("הקשר בין IRR ל-NPV, ובחירה בין פרויקטים", 30, f"עבור פרויקט יחיד IRR ו-NPV מובילים להחלטה זהה, אבל בין פרויקטים סותרים הם עלולים לדרג אחרת; במקרה כזה מעדיפים NPV. נקודת ה-Crossover היא כ-{p(CROSS)}.", [
            video(),
            T("עבור פרויקט **קונבנציונלי** (השקעה ראשונה ואחריה תקבולים) ה-NPV יורד ככל ששיעור ההיוון עולה, ומקבל ערך אפס ב-IRR. לכן: $NPV>0 \\Leftrightarrow IRR>r$ — שני הקריטריונים מובילים להחלטה זהה.\n\nהבעיה מתחילה כשבוחרים בין פרויקטים **סותרים** (Mutually exclusive), כלומר אפשר לבצע רק אחד.", "הקשר"),
            EX("פרויקטים A ו-B", f"שני פרויקטים בהשקעה של $100{{,}}000$ ₪:\n\n- A: תזרימים $90{{,}}000$, $30{{,}}000$, $10{{,}}000$ (תקבולים מוקדמים).\n- B: תזרימים $10{{,}}000$, $40{{,}}000$, $110{{,}}000$ (תקבולים מאוחרים).\n\n$IRR_A = {p(A_IRR)}$, $IRR_B = {p(B_IRR)}$ — A גבוה יותר. אבל ב-$r=10\\%$: $NPV_A = {m(A_NPV)}$ ו-$NPV_B = {m(B_NPV)}$ — **B גבוה יותר**.\n\n" + tbl(["שיעור היוון", "NPV של A", "NPV של B", "עדיף"], ab_prof) + f"\n\nהפרויקטים נחתכים בשיעור היוון של כ-${p(CROSS)}$ (נקודת Crossover): מתחתיו B עדיף, מעליו A עדיף."),
            C("**מסקנה:** כשיש סתירה, מעדיפים את הפרויקט עם **NPV גבוה יותר** (בשיעור ההיוון הרלוונטי) — משום שהוא מודד תוספת ערך בשקלים, ואילו IRR מתעלם מגודל ההשקעה ומניח השקעה מחדש בשיעור ה-IRR.", "important"),
            ("question", {"question_id": qid["conflict"], "show_answer": "after_attempt"}),
            S("- פרויקט יחיד: NPV ו-IRR נותנים אותה החלטה.\n- פרויקטים סותרים: עלולה להיווצר סתירה (גודל/תזמון).\n- הכלל: עדיף NPV גבוה יותר."),
        ]),
        ("מגבלות IRR ו-MIRR", 30, f"ל-IRR יש מגבלות: ייתכנו כמה IRR, הוא מניח reinvestment ב-IRR, ואינו מתחשב בגודל. MIRR פותר זאת; בפרויקט הדוגמה MIRR ≈ {p(MIRR)}.", [
            video(),
            T("**מגבלות IRR:**\n\n1. **מספר IRR** — כשהתזרימים אינם קונבנציונליים (יותר מהיפוך סימן אחד) ייתכנו כמה פתרונות. דוגמה: $-100, +230, -132$ נותן $IRR=10\\%$ וגם $IRR=20\\%$.\n2. **הנחת ההשקעה מחדש** — IRR מניח שתזרימי הביניים מושקעים מחדש בשיעור ה-IRR עצמו, הנחה לא ריאלית כשה-IRR גבוה.\n3. **התעלמות מגודל** — פרויקט קטן עם IRR גבוה עשוי להוסיף פחות ערך מפרויקט גדול עם IRR נמוך יותר.", "המגבלות"),
            F("Modified IRR (MIRR)", r"MIRR = \left(\frac{FV\ \text{of positive CFs at reinvestment rate}}{PV\ \text{of negative CFs at financing rate}}\right)^{1/n} - 1", "MIRR מניח השקעה מחדש בשיעור סביר (למשל עלות ההון) ולכן אינו סובל מהבעיות של IRR."),
            EX("דוגמה", f"בפרויקט הדוגמה, בהנחה של השקעה מחדש ב-$10\\%$: $FV$ של התקבולים בסוף שנה 5 הוא ${m(sum(c * (1 + mirr_re) ** (5 - (t + 1)) for t, c in enumerate(P_CF)))}$ ₪, והשקעה של $100{{,}}000$ ₪.\n\n$MIRR = ({m(sum(c * (1 + mirr_re) ** (5 - (t + 1)) for t, c in enumerate(P_CF)))}/100{{,}}000)^{{1/5}} - 1 = {p(MIRR)}$ — נמוך מה-IRR ({p(P_IRR)}), כי ההנחה על ההשקעה מחדש מתונה יותר. באקסל: `=MIRR(values, finance_rate, reinvest_rate)`."),
            ("question", {"question_id": qid["multi_irr"], "show_answer": "after_attempt"}),
            S("- ייתכנו כמה IRR בתזרים לא קונבנציונלי.\n- IRR מניח reinvestment ב-IRR ומתעלם מגודל.\n- MIRR מתקן את ההנחה על ההשקעה מחדש."),
        ]),
        ("Payback, Discounted Payback ו-PI", 25, f"Payback פשוט אך מתעלם מערך הזמן; Discounted Payback מתחשב בו; PI יחס ערך לעלות. בדוגמה: Payback ≈ {PAYBACK:.2f} שנים, Discounted Payback ≈ {DPAYBACK:.2f} שנים, PI ≈ {PI:.2f}.", [
            video(),
            T("**תקופת החזר** (Payback Period) היא הזמן עד שהתזרימים המצטברים מכסים את ההשקעה. היא פשוטה ונותנת אינדיקציה לנזילות וסיכון, אך **מתעלמת מערך הזמן** ומתזרימים שאחרי תקופת ההחזר. **Discounted Payback** מהוון את התזרימים ולכן מתחשב בערך הזמן, אך עדיין מתעלם מהתזרימים שאחרי ההחזר.", "תקופת החזר"),
            EX("חישוב עבור פרויקט הדוגמה", "הטבלה מציגה תזרים מצטבר ותזרים מצטבר מהוון ($r=10\\%$):\n\n" + tbl(["t", "CF", "מצטבר", "מצטבר מהוון"], cum_rows) + f"\n\nה-Payback הוא בין שנה 3 לשנה 4: ≈ **{PAYBACK:.2f} שנים**. ה-Discounted Payback ≈ **{DPAYBACK:.2f} שנים**."),
            F("Profitability Index (PI)", r"PI = \frac{PV\ \text{of future cash flows}}{I_0} = 1 + \frac{NPV}{I_0}", "PI > 1 שקול ל-NPV > 0. שימושי לדירוג פרויקטים כשיש מגבלת הון (Capital rationing)."),
            T(f"בדוגמה: $PI = {m(sum(c / (1 + r10) ** (t + 1) for t, c in enumerate(P_CF)))} / 100{{,}}000 = {PI:.3f}$, כלומר כל שקל שמושקע מייצר ערך נוכחי של כ-{PI:.2f} ₪."),
            ("question", {"question_id": qid["payback"], "show_answer": "after_attempt"}),
            S("- Payback: מתעלם מערך הזמן ומתזרימים אחרי ההחזר.\n- Discounted Payback: מתחשב בערך הזמן.\n- $PI = PV/I_0$; $PI>1 \\Leftrightarrow NPV>0$."),
        ]),
    ])
    M4 = ("מודול 4: לוחות סילוקין", "לוח סילוקין מפרט כיצד הלוואה נפרעת לאורך זמן. השיטות העיקריות הן שפיצר, קרן שווה ותשלום בולט — כולן שוות ערך נוכחי להלוואה בשיעור הריבית, אך שונות במבנה התשלומים.", [
        ("לוח סילוקין — מושגי יסוד", 20, "לוח סילוקין הוא טבלה של פירעון ההלוואה: יתרת פתיחה, תשלום, ריבית, קרן ויתרת סגירה. הריבית נגזרת מהיתרה, והקרן היא התשלום פחות הריבית.", [
            video(),
            T("**הלוואה** היא סכום ($L$) שמתקבל היום ונפרע בתשלומים לאורך תקופה, בריבית ($r$ לתקופה). כל תשלום מורכב משני רכיבים:\n\n- **ריבית** — המחיר על הכסף שנשאר חייבים: $\\text{Interest}_t = r \\cdot B_{t-1}$.\n- **קרן** (Principal) — החלק שמקטין את החוב: $\\text{Principal}_t = \\text{Payment}_t - \\text{Interest}_t$.\n\n**לוח סילוקין** (Amortization schedule) הוא הטבלה שמראה את הפירוק הזה בכל תקופה.", "מושגים"),
            F("יתרה לאחר תשלום", r"B_t = B_{t-1} - \text{Principal}_t = B_{t-1}\,(1+r) - \text{Payment}_t"),
            T(tbl(["עמודה", "משמעות"], [("יתרת פתיחה", "החוב בתחילת התקופה ($B_{t-1}$)"), ("תשלום כולל", "מה ששולם בתקופה"), ("ריבית", "$r \\cdot B_{t-1}$"), ("החזר קרן", "תשלום פחות ריבית"), ("יתרת סגירה", "$B_t$")]), "עמודות הלוח"),
            C("**בדיקות שפיות:** סך החזרי הקרן שווה בדיוק לסכום ההלוואה, ויתרת הסגירה האחרונה היא $0$.", "tip"),
            ("question", {"question_id": qid["amort_def"], "show_answer": "after_attempt"}),
            S("- ריבית = $r \\times$ יתרת פתיחה; קרן = תשלום − ריבית.\n- לוח סילוקין מפרט את הפירוק בכל תקופה.\n- סך הקרן = סכום ההלוואה; היתרה הסופית = 0."),
        ]),
        ("לוח שפיצר (Level Payment)", 35, f"בלוח שפיצר התשלום קבוע ($PMT$): בהתחלה רוב התשלום ריבית, ובהמשך רוב התשלום קרן. בהלוואה לדוגמה PMT ≈ {m(SP_PAY)} ₪.", [
            video(),
            T("בלוח **שפיצר** (Annuity-style loan) משלמים **סכום קבוע** בכל תקופה. התשלום נבחר כך שהערך הנוכחי של כל התשלומים, בשיעור הריבית, שווה לסכום ההלוואה — כלומר $L$ הוא ה-PV של אנונה.", "הרעיון"),
            F("PMT", r"PMT = \frac{L \cdot r}{1-(1+r)^{-n}}"),
            F("Balance after k payments", r"B_k = L(1+r)^k - PMT\cdot\frac{(1+r)^k-1}{r}"),
            EX(f"לוח שפיצר: הלוואה של {m(L, 0)} ₪, ריבית {int(R * 100)}%, {N} שנים", f"$PMT = \\frac{{100{{,}}000 \\cdot 0.06}}{{1-1.06^{{-5}}}} = {m(SP_PAY)}$ ₪ לשנה.\n\n" + sched_md(SP) + f"\n\nשימו לב: הריבית יורדת משנה לשנה ({m(SP[0][3])} → {m(SP[-1][3])}) והקרן גדלה ({m(SP[0][4])} → {m(SP[-1][4])}), כשהתשלום הכולל קבוע."),
            EX("הלוואה חודשית", f"הלוואה של $500{{,}}000$ ₪, ריבית נומינלית $4\\%$ בשנה, 25 שנים (300 תשלומים חודשיים). ריבית חודשית $r=0.04/12$:\n\n$PMT = {m(MPMT)}$ ₪ לחודש. סך התשלומים: ${m(monthly_total, 0)}$ ₪; סך הריבית: ${m(monthly_total - 500000, 0)}$ ₪ — יותר מ-{(monthly_total - 500000) / 500000 * 100:.0f}% מהקרן.\n\nבאקסל: `=PMT(0.04/12, 300, -500000)`, וכן `IPMT` ו-`PPMT` לפירוק תשלום בודד."),
            ("resource", {"attachment_id": "__CSV__", "title": "לוח סילוקין שפיצר לדוגמה (קובץ CSV לפתיחה באקסל)", "description": "אותו לוח כמו בדוגמה, להורדה ולשימוש בתרגול."}),
            ("question", {"question_id": qid["pmt"], "show_answer": "after_attempt"}),
            ("question", {"question_id": qid["spitzer_prop"], "show_answer": "after_attempt"}),
            S("- שפיצר: $PMT = \\frac{Lr}{1-(1+r)^{-n}}$ קבוע בכל תקופה.\n- בתחילה רוב התשלום ריבית; עם הזמן הקרן גדלה.\n- באקסל: `PMT`, `IPMT`, `PPMT`."),
        ]),
        ("לוח קרן שווה (Equal Principal)", 25, f"בלוח קרן שווה מחזירים קרן קבועה ($L/n$) ועוד ריבית על היתרה, ולכן התשלום הכולל יורד עם הזמן. בדוגמה התשלום הראשון {m(EQ[0][2])} ₪ והאחרון {m(EQ[-1][2])} ₪.", [
            video(),
            T("בלוח **קרן שווה** (Constant principal) החזר הקרן **קבוע** בכל תקופה, והריבית מחושבת על היתרה. מכיוון שהיתרה קטנה, **התשלום הכולל יורד** משנה לשנה. התשלום הראשון גבוה יותר מבשפיצר, אך סך הריבית נמוך יותר.", "הרעיון"),
            F("Equal principal", r"\text{Payment}_t = \frac{L}{n} + r\cdot\left(L - (t-1)\frac{L}{n}\right), \qquad \text{Total interest} = r\,L\,\frac{n+1}{2}"),
            EX(f"אותה הלוואה: {m(L, 0)} ₪, {int(R * 100)}%, {N} שנים", f"החזר קרן קבוע: $100{{,}}000/5 = {m(L / N, 0)}$ ₪ בשנה.\n\n" + sched_md(EQ) + f"\n\nבדיקה בנוסחה: סך ריבית $= 0.06 \\cdot 100{{,}}000 \\cdot \\frac{{6}}{{2}} = {m(.06 * L * 3, 0)}$ ₪."),
            ("question", {"question_id": qid["eq_first"], "show_answer": "after_attempt"}),
            ("question", {"question_id": qid["eq_const"], "show_answer": "after_attempt"}),
            S("- קרן קבועה $L/n$ + ריבית על היתרה.\n- התשלום הכולל יורד לאורך זמן.\n- סך הריבית: $rL(n+1)/2$, נמוך מבשפיצר."),
        ]),
        ("תשלום בולט, ריבית משתנה והצמדה", 25, f"בהלוואת בולט משלמים רק ריבית ואת הקרן בסוף (סך ריבית {m(bl_total, 0)} ₪ בדוגמה). בשוק קיימים גם מסלולי פריים ומדד, שבהם הריבית או הקרן משתנות לאורך זמן.", [
            video(),
            T("בהלוואת **תשלום בולט** (Balloon / Bullet) משלמים בכל תקופה **ריבית בלבד**, ואת **כל הקרן בסוף**. זה נוח לתזרים בזמן ההלוואה, אך סך הריבית הגבוה ביותר והחשיפה לסיכון מימון מחדש בסוף התקופה.", "בולט"),
            EX("הלוואה בולטת — אותה הלוואה", sched_md(BL)),
            T("**מסלולי ריבית נפוצים** (בהקשר של משכנתאות ובנקאות בישראל):\n\n- **ריבית קבועה** — לא משתנה לאורך ההלוואה, ולכן התשלום ידוע מראש.\n- **ריבית משתנה** — מתעדכנת כל תקופה לפי עוגן (למשל פריים או ריבית בנק מרכזי); לוח הסילוקין מחושב מחדש בכל עדכון על היתרה שנותרה ועל התקופה שנותרה.\n- **הצמדה למדד** (CPI-linked) — היתרה צומחת בשיעור האינפלציה, ולכן התשלום הנומינלי עולה.\n\nהעיקרון זהה בכל המסלולים: ריבית = שיעור הריבית × יתרה, וקרן = תשלום − ריבית. כל שינוי בריבית או בהצמדה משנה את היתרה ואת התשלומים העתידיים.", "מסלולים"),
            C("**פירעון מוקדם:** כשמשלמים חלק מהקרן מוקדם מהמתוכנן, היתרה קטנה והריבית העתידית קטנה. ייתכנו עמלות פירעון מוקדם ותנאים משפטיים לפי חוזה ההלוואה — יש לבדוק את תנאי ההסכם.", "warning"),
            S("- בולט: ריבית בלבד + כל הקרן בסוף.\n- ריבית משתנה/צמודה: מחשבים מחדש לפי היתרה והתקופה שנותרו.\n- ריבית = $r \\times$ יתרה, בכל מסלול."),
        ]),
        ("השוואה בין שיטות הסילוקין", 25, "כל שיטות הסילוקין שוות ערך נוכחי להלוואה בשיעור הריבית, אבל מבנה התשלומים שונה: שפיצר — תשלום קבוע; קרן שווה — סך ריבית נמוך יותר; בולט — סך ריבית גבוה ביותר.", [
            video(),
            T("נשווה את שלוש השיטות על אותה הלוואה ($100{,}000$ ₪, $6\\%$, 5 שנים):\n\n" + comparison, "טבלת השוואה"),
            C("**תובנה חשובה:** אם מהוונים את כל תשלומי ההלוואה בשיעור ריבית ההלוואה, מקבלים **בדיוק** את סכום ההלוואה — בכל אחת מהשיטות. זה אומר שאף שיטה אינה \"זולה\" יותר במונחי NPV; ההבדל הוא בתזמון התשלומים, בנטל התזרימי ובסך הריבית הנומינלי.", "important"),
            T("**איך בוחרים?**\n\n- **שפיצר** — תשלום יציב וקל לתכנון; מתאים כשהתזרים קבוע.\n- **קרן שווה** — תשלומים גבוהים בהתחלה, סך ריבית נמוך; מתאים למי שיכול לעמוד בנטל ההתחלתי.\n- **בולט** — תזרים נוח עד הסוף, אך נדרשת יכולת להחזיר את הקרן או למחזר.", "שיקולי בחירה"),
            ("question", {"question_id": qid["which_more_interest"], "show_answer": "after_attempt"}),
            S(f"- כל השיטות: $PV(\\text{{payments}}, r) = L$.\n- סך ריבית: {'קרן שווה' if EQ_LESS else 'שפיצר'} נמוך מ{'שפיצר' if EQ_LESS else 'קרן שווה'}, ובולט הגבוה ביותר.\n- הבחירה תלויה ביכולת התזרימית ובהעדפת סיכון."),
        ]),
    ])
    M5 = ("מודול 5: סיכום ויישום", "מחברים את כל הכלים: מעריכים פרויקט באמצעות NPV, IRR ו-Payback, ובוחנים את אפשרויות המימון באמצעות לוחות סילוקין.", [
        ("מקרה בוחן: בחירת פרויקט ומימונו", 40, f"מקרה בוחן מסכם: מכונה בעלות {m(CASE_I, 0)} ₪ — NPV ≈ {m(CASE_NPV)} ₪ ו-IRR ≈ {p(CASE_IRR)}, ולכן כדאי; לאחר מכן בוחנים את המימון.", [
            video(),
            T(f"חברה שוקלת לרכוש מכונה:\n\n- עלות: ${m(CASE_I, 0)}$ ₪ (ב-$t=0$).\n- תזרים שנתי נקי לאחר מס: ${m(CASE_CF, 0)}$ ₪ במשך 5 שנים.\n- שווי גריטה בסוף שנה 5: ${m(CASE_SALV, 0)}$ ₪.\n- שיעור ההיוון ($WACC$): ${int(CASE_R * 100)}\\%$.", "תיאור המקרה"),
            EX("שלב 1 — NPV ו-IRR", f"התזרימים: {', '.join(m(c, 0) for c in CASE_FLOW)}.\n\n$NPV = {m(CASE_NPV)}$ ₪ ו-$IRR = {p(CASE_IRR)}$.\n\nמכיוון ש-$NPV>0$ וגם $IRR > WACC$, הפרויקט **כדאי**.\n\nרגישות לשיעור ההיוון:\n\n" + tbl(["שיעור היוון", "NPV (₪)"], sens)),
            EX("שלב 2 — מימון", f"נניח שהחברה לוקחת הלוואת שפיצר של $200{{,}}000$ ₪ ל-5 שנים בריבית $6\\%$: $PMT = {m(pmt(.06, 5, 200000))}$ ₪ לשנה, וסך ריבית ${m(pmt(.06, 5, 200000) * 5 - 200000)}$ ₪. הערכת הפרויקט נעשית **בנפרד** מהמימון (על התזרים התפעולי ובשיעור WACC), ואילו לוח הסילוקין עוזר לתכנן את תזרים המזומנים והיכולת לעמוד בתשלומים."),
            C("**עיקרון:** מפרידים בין החלטת ההשקעה (האם הפרויקט יוצר ערך — NPV) לבין החלטת המימון (איך מממנים — לוח סילוקין). עלות החוב כבר משוקללת ב-WACC, ולכן אין להפחית שוב את תשלומי הריבית מתזרימי הפרויקט.", "important"),
            S(f"- $NPV = {m(CASE_NPV)}$ ₪, $IRR = {p(CASE_IRR)}$ > WACC → כדאי.\n- מפרידים בין החלטת השקעה להחלטת מימון.\n- לוח הסילוקין משמש לתכנון התזרים והיכולת לשרת את החוב."),
        ]),
        ("סיכום הקורס ודף נוסחאות", 25, "סיכום כל הנוסחאות, מילון מונחים (עברית–English) ורשימת בדיקה לטעויות נפוצות.", [
            video(),
            T(tbl(["נושא", "נוסחה"], [("ערך עתידי", "$FV = PV(1+r)^n$"), ("ערך נוכחי", "$PV = FV/(1+r)^n$"), ("Annuity", "$PV = C\\,\\frac{1-(1+r)^{-n}}{r}$"), ("Perpetuity", "$PV = C/r$"), ("EAR", "$(1+APR/m)^m-1$"), ("NPV", "$\\sum_{t=0}^{n} CF_t/(1+r)^t$"), ("IRR", "$\\sum CF_t/(1+IRR)^t = 0$"), ("CAPM", "$r_E = r_f+\\beta(r_m-r_f)$"), ("WACC", "$\\frac{E}{V}r_E+\\frac{D}{V}r_D(1-T_c)$"), ("PI", "$PV/I_0$"), ("שפיצר", "$PMT = \\frac{Lr}{1-(1+r)^{-n}}$"), ("קרן שווה", "$L/n + r\\cdot B_{t-1}$")]), "דף נוסחאות"),
            T(tbl(["מונח בעברית", "English"], [("ערך נוכחי נקי", "Net Present Value (NPV)"), ("שיעור תשואה פנימי", "Internal Rate of Return (IRR)"), ("שיעור היוון", "Discount rate"), ("תזרים מזומנים", "Cash Flow (CF)"), ("עלות ההון המשוקללת", "WACC"), ("תקופת החזר", "Payback Period"), ("מדד רווחיות", "Profitability Index (PI)"), ("לוח סילוקין", "Amortization schedule"), ("לוח שפיצר", "Level-payment loan"), ("קרן", "Principal"), ("ריבית אפקטיבית", "Effective Annual Rate (EAR)")]), "מילון מונחים"),
            C("**רשימת בדיקה לפני שמגישים תשובה:** האם ההשקעה ההתחלתית ב-$t=0$ ללא היוון? האם שיעור ההיוון מתאים לתקופה (שנתי/חודשי)? האם התזרימים לאחר מס ובמונחים עקביים? האם סך הקרן בלוח הסילוקין שווה להלוואה?", "tip"),
            S("סיימתם את הקורס! עברו על הבחנים בסוף כל מודול כדי לבדוק את עצמכם."),
        ]),
    ])
    mods = [M1, M2, M3, M4, M5]
    quizzes = {0: ["pv", "fv", "annuity", "perp", "ear"], 1: ["npv_calc", "npv_rule", "excel_npv"], 2: ["irr_def", "conflict", "multi_irr", "payback"], 3: ["pmt", "spitzer_prop", "eq_const", "eq_first", "which_more_interest", "amort_def"], 4: ["npv_calc", "pmt", "conflict", "which_more_interest"]}
    return mods, quizzes


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True, help="email of the teacher/admin who will own the course")
    ap.add_argument("--student", default="", help="optional student email to enroll")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        owner = db.scalar(select(User).where(User.email == args.owner.lower()))
        if owner is None or owner.role not in ("teacher", "admin"):
            sys.exit("Owner must be an existing teacher/admin account")

        # ---- cleanup of a previous run
        old = db.scalar(select(LmsCourse).where(LmsCourse.owner_id == owner.id, LmsCourse.title == COURSE_TITLE))
        if old:
            db.delete(old)
        tag = db.scalar(select(Tag).where(Tag.user_id == owner.id, Tag.name == SEED_TAG))
        if tag:
            for qq in db.scalars(select(Question).where(Question.user_id == owner.id)):
                if tag in qq.tags:
                    db.delete(qq)
        subj = db.scalar(select(Subject).where(Subject.user_id == owner.id, Subject.name == "מימון והשקעות"))
        if subj:
            db.delete(subj)
        db.flush()

        # ---- private question bank (Hebrew) in the owner's library
        subj = Subject(user_id=owner.id, name="מימון והשקעות", description="NPV, IRR, ערך הזמן של כסף ולוחות סילוקין", color="#2f5bea", icon="book", position=99)
        db.add(subj)
        db.flush()
        topics = {}
        for key, name in (("tvm", "ערך הזמן של כסף"), ("npv", "Net Present Value (NPV)"), ("irr", "Internal Rate of Return (IRR)"), ("pb", "Payback ו-PI"), ("amort", "לוחות סילוקין")):
            t = Topic(user_id=owner.id, subject_id=subj.id, name=name, position=len(topics))
            db.add(t)
            db.flush()
            topics[key] = t
        qid = {}
        qdefs = build_questions()
        for d in qdefs:
            opts = [OptionIn(text=t, is_correct=ok) for t, ok in d["options"]]
            q = create_question(db, owner, QuestionCreate(
                title=d["title"], content=d["content"], question_type=d["qtype"], difficulty=d["difficulty"], subject_id=subj.id,
                topic_ids=[topics[d["topic"]].id] if d["topic"] else [], tags=[SEED_TAG],
                answer=AnswerIn(answer=d["answer"], explanation=d["explanation"]), options=opts))
            qid[d["key"]] = str(q.id)

        # ---- downloadable resource: the Spitzer schedule as CSV (UTF-8 with BOM for Excel)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["תקופה", "יתרת פתיחה", "תשלום כולל", "ריבית", "החזר קרן", "יתרת סגירה"])
        for t, b0, pay, i, pr, b1 in SP:
            w.writerow([t, round(b0, 2), round(pay, 2), round(i, 2), round(pr, 2), round(b1, 2)])
        data = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
        key = storage.save(owner.id, data, "schedule.csv")
        att = Attachment(user_id=owner.id, filename="spitzer_schedule.csv", content_type="text/csv", size_bytes=len(data), storage_key=key)
        db.add(att)
        db.flush()

        # ---- the course
        mods, quizzes = build_course(qid)
        total_min = sum(les[1] for mod in mods for les in mod[2])
        course = LmsCourse(
            owner_id=owner.id, slug=slugify("npv-irr-amortization"), title=COURSE_TITLE,
            subtitle="קורס מקיף ליישום ערך הזמן של כסף בהחלטות השקעה ובמימון הלוואות",
            description="בקורס זה תלמדו להעריך פרויקטים ולנהל מימון בצורה מקצועית: **ערך הזמן של כסף**, **Net Present Value (NPV)**, **Internal Rate of Return (IRR)**, כלי הערכה משלימים (Payback, PI, MIRR) ו**לוחות סילוקין** — שפיצר, קרן שווה ובולט.\n\nכל שיעור כולל הסבר, נוסחאות, דוגמאות מחושבות צעד אחר צעד, שאלות לתרגול וסיכום. בסוף כל מודול יש בוחן.",
            summary="**מה למדנו:** העברת כסף בין נקודות זמן; הערכת פרויקטים ב-NPV וב-IRR ומגבלותיהם; בחירת שיעור היוון (CAPM, WACC); וכן בניית לוחות סילוקין בשיטות שפיצר, קרן שווה ובולט והשוואה ביניהן.\n\n**הכלל שחוזר בכל הקורס:** מהוונים לנקודת זמן אחת לפני שמשווים או מסכמים.",
            instructor_name=owner.display_name or "", category="מימון והשקעות", difficulty="intermediate", language="עברית", status="draft",
            price_amount=1200, discount_amount=900, currency="ILS", enrollment_type="paid", payment_policy="full_payment", access_days=None,
            objectives=["להעביר סכומי כסף בין נקודות זמן (FV / PV, Annuity, Perpetuity)", "לחשב ולפרש NPV ולהחליט על כדאיות פרויקט", "לחשב IRR, להבין את מגבלותיו ולהשתמש ב-MIRR", "להעריך פרויקטים בעזרת Payback ו-PI", "לבנות ולהשוות לוחות סילוקין: שפיצר, קרן שווה ובולט"],
            requirements=["אלגברה ברמת תיכון", "היכרות בסיסית עם אקסל (מומלץ)"], target_audience="סטודנטים לכלכלה, מימון וניהול, אנשי כספים ומשקיעים פרטיים שרוצים להבין החלטות השקעה ומימון.",
            estimated_minutes=total_min, completion_rule={"min_lesson_percent": 90, "require_quizzes": False})
        db.add(course)
        db.flush()
        for mi, (mtitle, msummary, lessons) in enumerate(mods):
            module = LmsModule(course_id=course.id, title=mtitle, description="", summary=msummary, position=mi, is_published=True)
            db.add(module)
            db.flush()
            qs_set = LmsPracticeSet(course_id=course.id, title=f"בוחן — {mtitle}", kind="exam", position=100 + mi, is_published=True,
                                    description="בוחן סיכום למודול. נסו לפתור לפני שמציגים את הפתרון המלא.")
            db.add(qs_set)
            db.flush()
            for ii, k in enumerate(quizzes[mi]):
                db.add(LmsPracticeItem(set_id=qs_set.id, question_id=uuid.UUID(qid[k]), position=ii))
            all_lessons = list(lessons) + [("בוחן סיכום מודול", 15, "בחן את עצמך על חומר המודול.", [("quiz", {"title": f"בוחן — {mtitle}", "question_ids": [qid[k] for k in quizzes[mi]], "practice_set_id": str(qs_set.id), "settings": {"passing_grade": 60, "shuffle": True, "show_answers": "after_submit"}}), ("callout", {"variant": "tip", "markdown": "אפשר לחזור לשיעורים בכל עת. הפתרונות המלאים מופיעים בשאלות התרגול של כל שיעור."})])]
            for li, (ltitle, minutes, lsummary, blocks) in enumerate(all_lessons):
                les = LmsLesson(course_id=course.id, module_id=module.id, title=ltitle, summary=lsummary, position=li, is_published=True,
                                estimated_minutes=minutes, is_free_preview=(li == 0 and mi in (0, 1)))
                db.add(les)
                db.flush()
                for bi, (btype, bdata) in enumerate(blocks):
                    bdata = dict(bdata)
                    if bdata.get("attachment_id") == "__CSV__":
                        bdata["attachment_id"] = str(att.id)
                    db.add(LmsBlock(lesson_id=les.id, type=btype, position=bi, is_visible=True, data=clean_block(db, owner.id, btype, bdata)))

        # ---- topic practice sets + a final exam (students receive only these questions, solutions only on request)
        set_defs = [
            ("tvm", "ערך הזמן של כסף", "תרגול ב-FV, PV, Annuity, Perpetuity ו-EAR. לחצו על ״הצג תשובה ופתרון מלא״ כדי לראות את כל שלבי הפתרון."),
            ("npv", "Net Present Value (NPV)", "חישוב NPV, כלל ההחלטה, CAPM ו-WACC, וטעויות נפוצות."),
            ("irr", "Internal Rate of Return (IRR)", "חישוב IRR, אינטרפולציה, MIRR, ובחירה בין פרויקטים סותרים."),
            ("pb", "Payback ו-PI", "תקופת החזר, Discounted Payback ו-Profitability Index."),
            ("amort", "לוחות סילוקין", "שפיצר, קרן שווה ובולט: חישוב תשלומים, פירוק לריבית וקרן, יתרות והשוואות."),
        ]
        for pos, (tk, stitle, sdesc) in enumerate(set_defs):
            ps = LmsPracticeSet(course_id=course.id, title=stitle, description=sdesc, kind="practice", position=pos, is_published=True)
            db.add(ps)
            db.flush()
            for ii, d in enumerate(x for x in qdefs if x["topic"] == tk):
                db.add(LmsPracticeItem(set_id=ps.id, question_id=uuid.UUID(qid[d["key"]]), position=ii))
        exam_keys = ["pv", "double", "npv_calc", "npv_neg", "wacc", "irr_simple", "irr_decision", "payback_calc", "pmt", "row2", "eq_first", "which_more_interest"]
        ex = LmsPracticeSet(course_id=course.id, title="מבחן מסכם — כל הנושאים", kind="exam", position=len(set_defs), is_published=True,
                            description="מבחן תרגול מסכם שמערבב את כל הנושאים. נסו לפתור לפני שאתם חושפים את הפתרון.")
        db.add(ex)
        db.flush()
        for ii, k in enumerate(exam_keys):
            db.add(LmsPracticeItem(set_id=ex.id, question_id=uuid.UUID(qid[k]), position=ii))
        course.status, course.published_at = "published", utcnow()

        # ---- archive the old English sample, enroll the student
        for c in db.scalars(select(LmsCourse).where(LmsCourse.title == "Investment Fundamentals")):
            c.status = "archived"
        if args.student:
            stu = db.scalar(select(User).where(User.email == args.student.lower(), User.role == "student"))
            if stu is None:
                sys.exit("Student account not found (register it first)")
            db.add(LmsEnrollment(student_id=stu.id, course_id=course.id, status="active", source="manual", starts_at=utcnow(), granted_by=owner.id, notes="seed"))
        db.commit()
        n_lessons = sum(len(mod[2]) + 1 for mod in mods)
        print(f"OK: course '{COURSE_TITLE}' — {len(mods)} modules, {n_lessons} lessons, {len(qid)} bank questions. NPV example={m(P_NPV)} IRR={p(P_IRR)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
