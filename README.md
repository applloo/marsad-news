# رادار الأخبار العالمية

الملفات المطلوبة للنشر: `app.py` و `core.py` و `sources.py` و `requirements.txt`

## النشر للحصول على رابط دائم (مجاني)
1. أنشئ مستودعاً على GitHub وارفع الملفات الأربعة.
2. ادخل https://share.streamlit.io ← New app ← اختر المستودع ← Main file: `app.py` ← Deploy.
3. احفظ الرابط الناتج `https://اسم-تطبيقك.streamlit.app`.
4. (اختياري) للتلخيص الذكي: Settings ← Secrets: `ANTHROPIC_API_KEY = "sk-ant-..."`

## تشغيل محلي
pip install -r requirements.txt
streamlit run app.py

## تعديل قوائم المصادر
افتح `sources.py` وأضف/احذف سطراً بصيغة: ("الاسم", "الدومين", "he|en|both")
