# رادار الأخبار العالمية

الملفات المطلوبة للنشر: `app.py` و `core.py` و `sources.py` و `writers.py` و `store.py` و `requirements.txt`

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

## إضافة كاتب
افتح `writers.py` وأضف سطراً بصيغة W("id", "الاسم بالعربية", "English Name", "المنفذ", "US|UK|IL", "رأي|تحليل|خبر", ["موقع1.com"]).

## تفعيل الحفظ الدائم (المحفوظات + المصادر والكتّاب المضافون)
بدونه يعمل التطبيق لكن المحفوظات تضيع عند تحديث الصفحة. الإعداد مرة واحدة (3 دقائق):
1. ادخل https://gist.github.com وأنشئ Gist **سرّياً (secret)** باسم ملف `marsad_store.json` ومحتواه `{}` ثم Create. انسخ المعرّف (الجزء الأخير من رابط الـ Gist).
2. ادخل https://github.com/settings/tokens ← Generate new token (classic) ← فعّل صلاحية **gist** فقط ← انسخ المفتاح.
3. في Streamlit Cloud: التطبيق ← Settings ← Secrets وأضف:
   GITHUB_TOKEN = "ghp_..."
   GIST_ID = "معرّف الـ Gist"
4. Reboot app. صار الحفظ يعمل ويتزامن بين هاتفك وحاسوبك.

ملاحظة: الرابط عام ما لم تقيّد التطبيق من Share في Streamlit؛ والمحفوظات مشتركة لكل من يفتح التطبيق.

## القراءة الصوتية
- زر «🎧 استمع» تحت كل نتيجة ومحفوظ، وقسم «استمع للمقال» داخل صفحة القراءة، و«نشرة صوتية» في تاب المحفوظات.
- الصوت عصبي عبر حزمة `edge-tts` (موجودة في requirements.txt). إن فشل تثبيتها يعمل الصوت البديل من Google تلقائياً.
  وإن فشل النشر كله بسببها احذف سطر `edge-tts` من requirements.txt.

