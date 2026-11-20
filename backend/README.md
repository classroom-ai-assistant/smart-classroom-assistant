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

الاختبارات لا تحتاج Supabase ولا إنترنت.

**اختبارات التكامل** (الدروس والأنشطة مع RLS حقيقية) تحتاج Postgres **محلي** فقط:

```bash
TEST_ADMIN_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres pytest
```

تنشئ قاعدة مؤقتة، وتطبّق عليها نسخة مبسطة من Supabase (`tests/db/supabase_stub.sql`) ثم كل ملفات `supabase/migrations`، وتحذفها في النهاية. لا تضعي هنا رابط Supabase أبداً.

`TEST_DATABASE_URL` (اختياري) يشغّل فحصين على قاعدة Supabase **تطوير** ويلغي تغييراته.

## كيف يعمل الدخول

1. الواجهة تسجّل المعلمة وتدخلها عبر Supabase Auth مباشرة.
2. الواجهة ترسل التوكن لهذا الخادم في `Authorization: Bearer ...`.
3. الخادم يتحقق منه بالمفاتيح العامة لـ Supabase، ثم ينفذ كل استعلام باسم المعلمة حتى تعمل RLS.

</div>
