"""
Shifa AI (شفاء AI) — PharmaNear's smart pharmacist assistant.

Same architecture as api/pharmacy-search.py, and for the same reason: a
plain BaseHTTPRequestHandler-based function that Vercel auto-detects with
zero configuration (no vercel.json, no Flask/WSGI, no requirements.txt —
the Gemini call uses urllib.request from the standard library). This file
is served automatically at:

    POST /api/shifa-chat

Reads the API key from the GEMINI_API_KEY environment variable only — it is
never present in any file that reaches the frontend or the Git history.

Request body (JSON):
    {
      "message": "ما هي جرعة الباراسيتامول للبالغين؟",
      "history": [                      # optional, for multi-turn context
        {"role": "user",  "text": "..."},
        {"role": "model", "text": "..."}
      ]
    }

Response body (JSON):
    { "status": "success", "reply": "..." }
    { "status": "error",   "message": "..." }
"""

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
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

أسلوبك: دافئ، مهني، مطمئن، ومختصر — لست بديلاً عن الصيدلي، أنتِ مساعدة أولية توجّه الزائر بشكل صحيح."""

# Appended programmatically to every single reply — not left to the model's
# discretion, so it is guaranteed present regardless of what Gemini returns.
SAFETY_DISCLAIMER = (
    "\n\n⚠️ هذه المعلومات لإرشادك ولا تُغني عن استشارة الطبيب أو الصيدلي مباشرة."
)


def call_gemini(user_message, history):
    contents = []
    for turn in history or []:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if role in ("user", "model") and text:
            contents.append({"role": role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 700},
    }

    request = urllib.request.Request(
        GEMINI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        data = json.loads(response.read().decode("utf-8"))

    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("لم يُرجع النموذج أي إجابة.")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
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

        if not GEMINI_API_KEY:
            self._send_json({
                "status": "error",
                "message": "مفتاح GEMINI_API_KEY غير مضبوط على الخادم.",
            }, 500)
            return

        if not message:
            self._send_json({"status": "error", "message": "الرجاء كتابة سؤالك أولاً."}, 400)
            return

        try:
            reply = call_gemini(message, history)
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
        except Exception as exc:  # last-resort safety net — never a non-JSON crash
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
