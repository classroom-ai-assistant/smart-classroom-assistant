<div dir="rtl">

# إعدادات Supabase Auth

هذه الإعدادات تُضبط من لوحة Supabase (لا تُدار من الـ migrations). هذا الملف هو المرجع حتى يُعاد ضبطها بنفس الشكل في أي مشروع جديد.

| المكان في اللوحة | الإعداد | القيمة | المرجع |
| --- | --- | --- | --- |
| Authentication ← Sign In / Providers ← Email | Enable Email provider | مفعّل | AUTH-01 |
| نفس الصفحة | Confirm email | مفعّل | — |
| نفس الصفحة | Minimum password length | 8 | DR-02 |
| نفس الصفحة | Password requirements | Letters and digits | — |
| Authentication ← URL Configuration | Site URL | رابط الواجهة (Lovable) | — |
| نفس الصفحة | Redirect URLs | رابط معاينة Lovable + `/**`، و `http://localhost:5173/**` | — |
| Authentication ← Emails ← Confirm sign up | القالب والعنوان | `templates/confirm_signup.html` | — |
| Authentication ← Emails ← Reset password | القالب والعنوان | `templates/reset_password.html` | AUTH-06 |

## قيود معروفة

- **البريد الافتراضي** يرسل لأعضاء فريق Supabase فقط، وبعدد محدود في الساعة. قبل تسجيل معلمات حقيقيات يلزم بريد خاص (SMTP) مثل Resend.
- **AUTH-05** (قفل الحساب بعد 5 محاولات): Supabase يحدّ المحاولات حسب عنوان الـ IP ولا يقفل الحساب نفسه. القرار مسجّل في ملف حالة المشروع.

</div>
