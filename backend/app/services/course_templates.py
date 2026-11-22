"""Course templates: a ready-made SKELETON (modules, lessons and the usual blocks) the teacher then fills in.
Everything created is an unpublished draft. Placeholder text is marked [להשלמה] so it is obvious what still needs writing.
Templates are data, not code: add one by adding an entry to TEMPLATES."""

TODO = "[להשלמה] "

# the usual shape of a teaching lesson: goals, explanation, key formula, worked example, summary
def concept_blocks(topic: str) -> list[dict]:
    return [
        {"type": "callout", "data": {"variant": "info", "markdown": f"{TODO}מטרות השיעור: מה התלמיד יידע ויוכל לעשות אחריו ({topic})."}},
        {"type": "text", "data": {"title": "הסבר", "markdown": f"{TODO}הסבירו את הנושא: {topic}."}},
        {"type": "formula", "data": {"title": "נוסחה מרכזית", "latex": "", "description": f"{TODO}אם יש נוסחה, כתבו אותה ב-LaTeX ופרשו כל סימן."}},
        {"type": "example", "data": {"title": "דוגמה מחושבת", "markdown": f"{TODO}דוגמה אחת מלאה, צעד אחר צעד."}},
        {"type": "summary", "data": {"title": "סיכום", "markdown": f"{TODO}3-5 נקודות מפתח."}},
    ]


def practice_blocks() -> list[dict]:
    return [
        {"type": "text", "data": {"title": "תרגול", "markdown": f"{TODO}הנחיות לתרגול. הוסיפו כאן שאלות או בוחן מהמאגר."}},
    ]


def lesson(title: str, minutes: int, blocks: list[dict], free: bool = False) -> dict:
    return {"title": title, "estimated_minutes": minutes, "blocks": blocks, "is_free_preview": free}


TEMPLATES: list[dict] = [
    {
        "id": "academic",
        "title": "קורס אקדמי מלא",
        "description": "מבוא, שלושה נושאים (הסבר, דוגמה ותרגול בכל אחד) ומודול סיכום ומבחן.",
        "difficulty": "intermediate",
        "modules": [
            {"title": "מבוא", "lessons": [
                lesson("ברוכים הבאים ומטרות הקורס", 10, [
                    {"type": "text", "data": {"title": "על הקורס", "markdown": f"{TODO}מה לומדים, למי הקורס מתאים, ומה נדרש."}},
                    {"type": "callout", "data": {"variant": "tip", "markdown": f"{TODO}איך ללמוד בקורס ולהצליח."}}], free=True)]},
            *[{"title": f"נושא {i}: [שם הנושא]", "lessons": [
                lesson(f"נושא {i}: מושגי יסוד", 20, concept_blocks(f"מושגי יסוד של נושא {i}")),
                lesson(f"נושא {i}: נוסחאות ודוגמאות", 25, concept_blocks(f"יישום ודוגמאות בנושא {i}")),
                lesson(f"נושא {i}: תרגול", 20, practice_blocks())]} for i in (1, 2, 3)],
            {"title": "סיכום ומבחן", "lessons": [
                lesson("סיכום הקורס", 15, [{"type": "summary", "data": {"title": "מה למדנו", "markdown": f"{TODO}סיכום כל הנושאים."}}]),
                lesson("מבחן מסכם", 45, [{"type": "text", "data": {"title": "הנחיות", "markdown": f"{TODO}יצרו מבחן בלשונית מבחנים וקשרו אליו כאן."}}])]},
        ],
    },
    {
        "id": "short",
        "title": "קורס קצר (3 שיעורים)",
        "description": "שלושה שיעורים ממוקדים עם הסבר, דוגמה וסיכום. מתאים לנושא יחיד או לסדנה.",
        "difficulty": "beginner",
        "modules": [{"title": "השיעורים", "lessons": [
            lesson("שיעור 1: הבסיס", 15, concept_blocks("הבסיס"), free=True),
            lesson("שיעור 2: העמקה", 20, concept_blocks("העמקה")),
            lesson("שיעור 3: יישום וסיכום", 20, concept_blocks("יישום") + practice_blocks())]}],
    },
    {
        "id": "exam_prep",
        "title": "הכנה למבחן",
        "description": "מודול לכל נושא עם סיכום ותרגול, ומודול סיום עם מבחן מדומה וטעויות נפוצות.",
        "difficulty": "intermediate",
        "modules": [
            *[{"title": f"נושא {i}: [שם הנושא]", "lessons": [
                lesson(f"נושא {i}: סיכום", 15, [
                    {"type": "summary", "data": {"title": "סיכום הנושא", "markdown": f"{TODO}הנקודות החשובות לבחינה."}},
                    {"type": "formula", "data": {"title": "נוסחאות לזכור", "latex": "", "description": f"{TODO}הנוסחאות המרכזיות."}}]),
                lesson(f"נושא {i}: תרגול", 25, practice_blocks())]} for i in (1, 2, 3)],
            {"title": "לקראת המבחן", "lessons": [
                lesson("טעויות נפוצות", 10, [{"type": "callout", "data": {"variant": "warning", "markdown": f"{TODO}טעויות שחוזרות במבחנים."}}]),
                lesson("מבחן מדומה", 60, [{"type": "text", "data": {"title": "הנחיות", "markdown": f"{TODO}יצרו מבחן בלשונית מבחנים וקשרו אליו."}}])]},
        ],
    },
]
BY_ID = {t["id"]: t for t in TEMPLATES}


def summary(t: dict) -> dict:
    mods = t["modules"]
    return {"id": t["id"], "title": t["title"], "description": t["description"], "modules": len(mods),
            "lessons": sum(len(m["lessons"]) for m in mods), "outline": [m["title"] for m in mods]}
