"""Prompts for AI-designed slides (lesson step 3, approved 2026-11-25).

The model designs whole slides — colours, shapes, stickers, animations, text,
robot narration and a question — inside the same Layout schema the editor
uses. Real photos are never invented: the model leaves `placeholder`
elements with what to search for, and the teacher fills them.
"""

from app.modules.pages.layout import ANIMATIONS, FONTS, SHAPES, TRANSITIONS
from app.modules.stickers.catalog import catalog

PALETTE = {
    "كريمي": "#FAEFE9",
    "برقوقي (للنصوص)": "#68546F",
    "أصفر": "#FCDC9F",
    "وردي": "#F8CDD4",
    "أزرق فاتح": "#CFD6E8",
    "نعناعي": "#B8CCCB",
    "بنفسجي فاتح": "#CAB2D4",
    "أبيض": "#FFFFFF",
}

TEMPLATES = {
    "letter": "درس حرف: غلاف الحرف كبير، شكل الحرف، كلمات تبدأ بالحرف مع ملصقات، تتبّع الحرف (شكل dashed)، سؤال «ما أول حرف في...؟»، حركة، ختام وتشجيع.",
    "number": "درس رقم: غلاف الرقم، عدّ أشياء بالملصقات (نفس الملصق مكرر بعدد الرقم)، الرقم بالكلمات، تتبّع الرقم، سؤال «كم...؟»، لعبة حركة، ختام.",
    "story": "قصة: غلاف القصة، 3 إلى 5 مشاهد (ملصقات الشخصيات + نص المشهد)، سؤال عن القصة، الدرس المستفاد، ختام.",
    "thing": "تعرّف على شيء (حيوان/فاكهة/لون...): غلاف، ما هو؟، شكله ولونه، صوته أو فائدته، سؤالان، نشاط حركي، ختام.",
    "morning": "حلقة الصباح: ترحيب، اليوم والطقس (ملصقات شمس/غيمة)، كيف حالكم (ملصقات مشاعر)، نشاط اليوم، ختام.",
    "free": "درس حرّ حسب الموضوع: غلاف، شرائح تشرح الفكرة خطوة خطوة، سؤال أو اثنان، نشاط حركي، ختام.",
}


def _stickers() -> str:
    by_cat: dict[str, list[str]] = {}
    for s in catalog():
        by_cat.setdefault(s["category"], []).append(f'{s["name"]}={s["label"]}')
    return "\n".join(f"- {cat}: " + ", ".join(items) for cat, items in by_cat.items())


def design_rules() -> str:
    palette = ", ".join(f"{name} {hex_}" for name, hex_ in PALETTE.items())
    return (
        "\nأنت أيضاً مصمّم شرائح لأطفال الروضة، تصمّم مثل Canva: ألوان مبهجة، عناصر كبيرة، حركة لطيفة.\n"
        "الشريحة 16:9، والمواقع والأحجام نسب مئوية من الشريحة (x و y و w و h من 0 إلى 100، وابقِ العناصر داخل الشريحة).\n"
        f"الألوان المسموحة فقط: {palette}.\n"
        f"الأشكال (shape): {', '.join(SHAPES)}.\n"
        f"الخطوط (font): {', '.join(FONTS)} — للعناوين lalezar أو changa أو reem_kufi، وللنص tajawal أو almarai.\n"
        f"حركات الدخول (animation.effect): {', '.join(ANIMATIONS)}. الانتقال بين الشرائح (transition): {', '.join(TRANSITIONS)}.\n"
        "الملصقات (sticker) — استخدم الاسم الإنجليزي قبل علامة = فقط ومن هذه القائمة حصراً:\n"
        f"{_stickers()}\n"
        "أنواع العناصر وحقولها:\n"
        '- {"id","type":"text","text","font","font_size" (نسبة من ارتفاع الشريحة 3 إلى 20),"color","bold","align":"start|center|end","x","y","w","h","z","animation"}\n'
        '- {"id","type":"shape","shape","fill","x","y","w","h","rotation","z","dashed","animation"}\n'
        '- {"id","type":"sticker","name","x","y","w","h","z","animation"}\n'
        '- {"id","type":"placeholder","query":"وصف قصير للصورة الحقيقية المطلوبة","x","y","w","h","z"} — لصورة حقيقية لا يغني عنها ملصق.\n'
        'animation = {"effect","delay" (ثوانٍ 0-5),"duration" (0.4-1.5)}.\n'
        "قواعد التصميم:\n"
        "- من 4 إلى 12 عنصراً في الشريحة، ونص قليل وكبير (الأطفال لا يقرؤون كثيراً؛ الروبوت هو من يتكلم).\n"
        "- خلفية ملونة من الألوان المسموحة، وأشكال زخرفية خلفية (z منخفض) وملصقات ونص في المقدمة.\n"
        "- اجعل الحركات متتابعة (delay متزايد) ولطيفة، ولا تضع حركة على كل عنصر.\n"
        "- الشريحة الأولى غلاف بعنوان الدرس، والأخيرة ختام وتشجيع.\n"
        "- speech: ما يقوله الروبوت في هذه الشريحة، جمل قصيرة دافئة (حتى 600 حرف).\n"
        '- question اختياري: {"question","expected_answers":[...],"hint","simpler_question"} أو null.\n'
        "- اكتب الأرقام في speech بالكلمات.\n"
    )


def generate_prompt(title: str, topic: str, template: str, count: int, notes: str | None) -> str:
    return (
        f"عنوان الدرس: {title}\nموضوع الدرس: {topic}\n"
        + (f"ملاحظات المعلمة: <<<{notes}>>>\n" if notes else "")
        + f"نوع الدرس: {TEMPLATES[template]}\n"
        + f"صمّم {count} شرائح بهذا الشكل بالضبط:\n"
        + '{"slides": [{"layout": {"background": "#RRGGBB", "transition": "fade", "elements": [...]}, '
        + '"speech": "...", "question": null}]}'
    )


def assist_prompt(action: str, slide_text: str, speech: str | None, title: str, topic: str) -> str:
    base = f"عنوان الدرس: {title}\nموضوع الدرس: {topic}\nنصوص الشريحة: <<<{slide_text}>>>\n"
    if speech:
        base += f"كلام الروبوت الحالي: <<<{speech}>>>\n"
    if action == "speech":
        return base + 'اكتب ما يقوله الروبوت للأطفال في هذه الشريحة. أجب بالشكل: {"speech": "..."}'
    if action == "question":
        return base + (
            "اقترح سؤالاً واحداً للأطفال عن هذه الشريحة. أجب بالشكل: "
            '{"question": {"question": "...", "expected_answers": ["..."], "hint": "...", "simpler_question": "..."}}'
        )
    return base + (
        "بسّط كل نص من نصوص الشريحة على عمر الأطفال مع الحفاظ على معناه. "
        'أجب بالشكل: {"texts": {"<id العنصر>": "النص المبسّط"}}'
    )
