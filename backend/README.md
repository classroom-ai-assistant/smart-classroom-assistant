<div dir="rtl">

# الخادم (FastAPI)

## التشغيل محلياً

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    |    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # ثم عبّئي القيم
uvicorn app.main:app --reload
```

- التوثيق التفاعلي: http://localhost:8000/docs
- فحص سريع: http://localhost:8000/health

## الاختبارات

```bash
pytest
```

الاختبارات لا تحتاج Supabase ولا إنترنت. اختبارات قاعدة البيانات الحقيقية (`-m integration`) تعمل فقط عند ضبط `TEST_DATABASE_URL` على قاعدة **تطوير**، وتُلغي كل تغييراتها في النهاية.

## كيف يعمل الدخول

1. الواجهة تسجّل المعلمة وتدخلها عبر Supabase Auth مباشرة.
2. الواجهة ترسل التوكن لهذا الخادم في `Authorization: Bearer ...`.
3. الخادم يتحقق منه بالمفاتيح العامة لـ Supabase، ثم ينفذ كل استعلام باسم المعلمة حتى تعمل RLS.

</div>
