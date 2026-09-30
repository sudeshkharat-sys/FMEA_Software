"""Check that the LLM API key (Groq / OpenAI / Azure OpenAI) works and translation is good.  Run:  python test.py"""
import os
import sys

import httpx

from backend import ai  # loads .env

if not ai.enabled():
    sys.exit("FAIL: no API key set. Put GROQ_API_KEY, OPENAI_API_KEY or AZURE_OPENAI_API_KEY in task-tracking-assistant/.env")
print("LLM provider:", ai.describe())
print("Certificate trust:", ai.trust_mode(), "\n")

samples = [
    "शुक्रवार तक रिपोर्ट तयार करा",                 # Marathi
    "UI ho gaya, backend mein ek Excel format fail ho raha hai",  # Hinglish
    "सर्वर एक्सेस मिळाला नाही, डिप्लॉयमेंट रुकी हुई है",   # Marathi + Hindi mix
]

try:
    print("== To English ==")
    for src, out in zip(samples, ai._call(samples, ai.LANGS["en"])):
        print(f"  {src}\n  -> {out}\n")

    english = "Chakan Excel format is failing, waiting for deployment access"
    for code in ("mr", "hi", "hinglish"):
        print(f"== English to {code} ==")
        print(f"  {ai._call([english], ai.LANGS[code])[0]}\n")
except httpx.HTTPStatusError as e:
    print(f"FAIL: LLM API returned HTTP {e.response.status_code}")
    print(e.response.text[:500])
    print("\nSSL certificate error = company network; run: pip install truststore | 401 = bad key | 403 = blocked by company firewall or no access | 429 = rate limit | 400/404 = wrong model name (check GROQ_MODEL)")
    sys.exit(1)
except Exception as e:
    sys.exit(f"FAIL: {type(e).__name__}: {e}")

print("PASS: Groq key works and translation is working.")
