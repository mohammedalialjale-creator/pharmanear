"""
Shifa AI (شفاء AI) — PharmaNear's smart pharmacist assistant.

Serverless Python function deployed on Vercel at:
    POST /api/shifa-chat

Reads the API key from the DEEPSEEK_API_KEY environment variable.
"""

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
REQUEST_TIMEOUT_S = 25

SYSTEM_PROMPT = """أنتِ "شفاء AI" — المساعد الصيدلي الذكي التابع لمنصة PharmaNear (فارمانير).

عرّفي نفسك في أول رسالة بأنكِ "المساعد الصيدلي الذكي شفاء AI التابع لموقع PharmaNear".

مهمتك:
- الإجابة على أسئلة الزوّار حول الأدوية: دواعي الاستعمال، الجرعات الشائعة والعامة، الآثار الجانبية المعروفة، والتداخلات الدوائية.
- استخدمي لغة عربية واضحة وبسيطة، بدون مصطلحات طبية معقدة إلا مع شرح مبسّط لها.
- نظّمي الإجابات الطويلة في نقاط قصيرة عند الحاجة لتسهيل القراءة.
- إذا كان السؤال خارج نطاق الأدوية والصحة الصيدلانية تماماً، وضّحي بلطف أن تخصصك هو الاستشارات الدوائية فقط.

حدود مهمة يجب الالتزام بها دائماً:
- لا تُشخّصي حالة مرضية لأي شخص، ولا تصفي جرعة دقيقة مخصصة لحالة فردية معينة (عمر، وزن، حالة مرضية مصاحبة) — قدّمي معلومات عامة موثوقة فقط وأحيلي التفاصيل الفردية للصيدلي أو الطبيب.
- إذا ذكر الزائر أعراضاً قد تدل على حالة طارئة (صعوبة تنفس حادة، ألم صدر، فقدان وعي، جرعة زائدة)، وجّهيه فوراً وبوضوح لطلب الطوارئ أو التوجه لأقرب مستشفى، قبل أي شيء آخر.
- لا تخترعي أسماء أدوية أو جرعات لست متأكدة منها.

قاعدة دقة صارمة (لتفادي الخلط بين الأدوية):
- في أول جملة من إجابتك، اذكري بوضوح اسم الدواء الذي سُئلتِ عنه بالضبط كما ورد في السؤال (مثال: "بخصوص الإيبوبروفين..." وليس اسم دواء آخر مشابه أو من نفس الفئة).
- الإيبوبروفين والباراسيتامول دواءان مختلفان تماماً (الإيبوبروفين مضاد التهاب غير ستيرويدي NSAID، والباراسيتامول مسكّن وخافض حرارة من فئة مختلفة تماماً) — لا تخلطي بينهما ولا بين أي دواءين آخرين مختلفين، حتى لو كانا يُستخدمان لنفس الغرض (تسكين الألم مثلاً).
- إذا لم تكوني متأكدة تماماً من اسم الدواء أو تعرّفتِ على تهجئة غير مألوفة، اسألي الزائر للتأكيد بدل التخمين وتقديم معلومات عن دواء مختلف.

أسلوبك: دافئ، مهني، مطمئن، ومختصر — لست بديلاً عن الصيدلي، أنتِ مساعدة أولية توجّه الزائر بشكل صحيح."""

SAFETY_DISCLAIMER = (
    "\n\n⚠️ هذه المعلومات لإرشادك ولا تُغني عن استشارة الطبيب أو الصيدلي مباشرة."
)


def call_deepseek(user_message, history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for turn in history or []:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if text:
            # Map frontend roles to OpenAI/DeepSeek schema
            mapped_role = "assistant" if role in ("model", "assistant") else "user"
            messages.append({"role": mapped_role, "content": text})

    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 700,
    }

    request = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        data = json.loads(response.read().decode("utf-8"))

    choices = data.get("choices") or []
    if not choices:
        raise ValueError("لم يُرجع النموذج أي إجابة.")

    text = choices[0].get("message", {}).get("content", "").strip()
    if not text:
        raise ValueError("رد فارغ من النموذج.")

    return text + SAFETY_DISCLAIMER


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw_body = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except (ValueError, TypeError):
            self._send_json({"status": "error", "message": "بيانات الطلب غير صالحة."}, 400)
            return

        message = (body.get("message") or "").strip()
        history = body.get("history") or []

        if not DEEPSEEK_API_KEY:
            self._send_json({
                "status": "error",
                "message": "مفتاح DEEPSEEK_API_KEY غير مضبوط على الخادم.",
            }, 500)
            return

        if not message:
            self._send_json({"status": "error", "message": "الرجاء كتابة سؤالك أولاً."}, 400)
            return

        try:
            reply = call_deepseek(message, history)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            self._send_json({
                "status": "error",
                "message": f"خطأ من خدمة الذكاء الاصطناعي (HTTP {exc.code}): {detail}",
            }, 502)
            return
        except urllib.error.URLError:
            self._send_json({"status": "error", "message": "تعذّر الاتصال بخدمة الذكاء الاصطناعي."}, 502)
            return
        except Exception as exc:  # last-resort safety net
            self._send_json({"status": "error", "message": f"خطأ غير متوقع: {exc}"}, 500)
            return

        self._send_json({"status": "success", "reply": reply}, 200)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, obj, status):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)