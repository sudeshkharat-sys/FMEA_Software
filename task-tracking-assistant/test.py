"""Check the AI connection AND the exact translation path the app uses.  Run:  python test.py"""
import os
import sys

from backend import ai, db  # ai loads .env

db.init_db()  # translation cache lives in the app database

if not ai.enabled():
    sys.exit("FAIL: no API key set. Put your Azure/OpenAI/Groq settings in task-tracking-assistant/.env")
print("LLM provider:", ai.describe())
print("Certificate trust:", ai.trust_mode(), "\n")

samples = [
    "\u0936\u0941\u0915\u094d\u0930\u0935\u093e\u0930 \u0924\u0915 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0924\u092f\u093e\u0930 \u0915\u0930\u093e",       # Marathi (Devanagari)
    "UI ho gaya, backend mein ek Excel format fail ho raha hai",                            # Hinglish
    "\u0938\u0930\u094d\u0935\u0930 \u090f\u0915\u094d\u0938\u0947\u0938 \u0928\u0939\u0940\u0902 \u092e\u093f\u0932\u093e, \u0921\u093f\u092a\u094d\u0932\u0949\u092f\u092e\u0947\u0902\u091f \u0930\u0941\u0915\u093e \u0939\u0948",  # Hindi
    "waiting for acess from IT dept",                                                        # English with a typo
]
failed = False
print("== Typed text -> English (this is what happens when someone saves a task/blocker/remark) ==")
for src in samples:
    out, ok = ai.to_english(src)
    bad = ai._problem(out, "en")
    status = "OK" if ok and not bad and out != src else "PROBLEM"
    failed |= status != "OK" and not src.startswith("waiting")
    print(f"  [{status}] {src}\n        -> {out}" + ("" if ok else "   (AI CALL FAILED - see error above)") + (f"   ({bad})" if bad else "") + "\n")

english = "Chakan Excel format is failing, waiting for deployment access"
for code in ("mr", "hi", "hinglish"):
    out = ai.translate_many([english], code)[0]
    bad = ai._problem(out, code)
    print(f"== English to {code} ==\n  {out}" + (f"\n  (still needs fixing: {bad})" if bad else "") + "\n")

print("FAIL: translation to English is not working, see above." if failed else "PASS: the AI connection and translation are working.")
sys.exit(1 if failed else 0)
