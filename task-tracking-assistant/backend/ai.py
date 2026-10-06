"""Translation layer. Uses Groq (OpenAI-compatible API); falls back to passthrough without a key."""
import json
import os
import re
from pathlib import Path

import httpx

from .db import conn

LANGS = {
    "en": "English",
    "mr": "Marathi (Devanagari script)",
    "hi": "Hindi (Devanagari script)",
    "hinglish": "Hinglish (Hindi written in Roman/Latin letters, mixing common English words naturally, like people text in India)",
}

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _verify():
    """TLS trust: custom CA file (CA_BUNDLE) > OS certificate store (truststore) > default bundle."""
    import ssl

    ca = os.environ.get("CA_BUNDLE") or os.environ.get("GROQ_CA_BUNDLE")
    if ca:
        return ssl.create_default_context(cafile=ca)
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


def trust_mode() -> str:
    ca = os.environ.get("CA_BUNDLE") or os.environ.get("GROQ_CA_BUNDLE")
    if ca:
        return f"custom CA file ({ca})"
    try:
        import truststore  # noqa: F401
        return "Windows/OS certificate store (truststore)"
    except ImportError:
        return "default Python bundle (truststore NOT installed: run pip install truststore)"


def _azure(what: str) -> str | None:
    """Azure settings. Accepts our names AND the traceability-chatbot names, so its .env lines work as-is."""
    e = os.environ
    if what == "KEY":
        return e.get("AZURE_OPENAI_API_KEY") or e.get("AZURE_API_KEY")
    if what == "ENDPOINT":  # base URL only; a full ".../openai/deployments/x" URL is trimmed
        v = e.get("AZURE_OPENAI_ENDPOINT") or e.get("AZURE_CHAT_ENDPOINT") or ""
        return v.split("/openai")[0].rstrip("/")
    if what == "DEPLOYMENT":  # explicit name, else the one inside the endpoint URL, else gpt-4o-mini
        v = e.get("AZURE_OPENAI_DEPLOYMENT") or e.get("AZURE_CHAT_DEPLOYMENT")
        if v:
            return v
        full = e.get("AZURE_OPENAI_ENDPOINT") or e.get("AZURE_CHAT_ENDPOINT") or ""
        return full.split("/deployments/")[1].split("/")[0] if "/deployments/" in full else "gpt-4o-mini"
    if what == "VERSION":
        return e.get("AZURE_OPENAI_API_VERSION") or e.get("AZURE_API_VERSION_CHAT") or "2024-12-01-preview"


def provider() -> str | None:
    """Which LLM to use: LLM_PROVIDER if set, else whichever key is present (azure > openai > groq)."""
    p = os.environ.get("LLM_PROVIDER", "").lower()
    if p in ("azure", "openai", "groq"):
        return p
    if _azure("KEY"):
        return "azure"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return None


def describe() -> str:
    p = provider()
    if p == "azure":
        return f"Azure OpenAI, deployment {_azure('DEPLOYMENT')}"
    if p == "openai":
        return f"OpenAI-compatible, model {os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}"
    if p == "groq":
        return f"Groq, model {os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')}"
    return "none"


def enabled() -> bool:
    return provider() is not None


def _request(messages: list[dict], json_mode: bool = True) -> dict:
    """Build (url, headers, body) for the configured provider. All three speak the OpenAI chat format."""
    p = provider()
    env = os.environ
    if p == "azure":
        url = (f"{_azure('ENDPOINT')}/openai/deployments/{_azure('DEPLOYMENT')}/chat/completions"
               f"?api-version={_azure('VERSION')}")
        body = {"messages": messages, "temperature": 0}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return {"url": url, "headers": {"api-key": _azure("KEY")}, "body": body}
    if p == "openai":
        base = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model, key = env.get("OPENAI_MODEL", "gpt-4o-mini"), env["OPENAI_API_KEY"]
    else:
        base, key = "https://api.groq.com/openai/v1", env["GROQ_API_KEY"]
        model = env.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    body = {"model": model, "messages": messages, "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return {"url": f"{base}/chat/completions", "headers": {"Authorization": f"Bearer {key}"}, "body": body}


CACHE_VER = "v3"  # bump when prompts change so old cached translations are not reused

# What the OUTPUT must look like for each language.
SCRIPT_RULES = {
    "en": "Write plain, natural workplace English using only Latin letters. NEVER output Devanagari. "
          "Fix spelling and grammar mistakes from the input. Keep people and place names, product names and codes as they are (in Latin letters).",
    "mr": "Write natural Marathi ENTIRELY in Devanagari script, the way a colleague in a Maharashtra office writes. "
          "Transliterate English/technical words and people/place names INTO Devanagari, never leave them in Latin letters "
          "(Excel -> एक्सेल, deployment -> डिप्लॉयमेंट, server -> सर्व्हर, access -> ऍक्सेस, report -> रिपोर्ट, Chakan -> चाकण, Sudesh -> सुदेश). "
          "Only ALL-CAPITAL acronyms (UI, PFMEA, PDF, API) and numbers/codes may stay in Latin letters.",
    "hi": "Write natural Hindi ENTIRELY in Devanagari script, the way a colleague in an Indian office writes. "
          "Transliterate English/technical words and people/place names INTO Devanagari, never leave them in Latin letters "
          "(Excel -> एक्सेल, deployment -> डिप्लॉयमेंट, server -> सर्वर, access -> एक्सेस, report -> रिपोर्ट, Chakan -> चाकण, Sudesh -> सुदेश). "
          "Only ALL-CAPITAL acronyms (UI, PFMEA, PDF, API) and numbers/codes may stay in Latin letters.",
    "hinglish": "Write casual Hindi in ROMAN (Latin) letters as Indians text at work, e.g. 'Server access nahi mila, deployment ruka hua hai'. "
                "NEVER output Devanagari. Common English work words stay in English.",
}

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_LATIN_WORD = re.compile(r"\b[A-Za-z]{2,}\b")
# distinctive Hindi/Marathi words in Roman letters that should never survive into English output
_ROMAN_INDIC = re.compile(r"\b(hai|hain|nahi|nahin|raha|rahi|rahe|karna|karne|karo|kiya|kiye|mein|gaya|gayi|gaye|mila|mili|hua|hui|abhi|baaki|baki|liye|aur|kal|aaj|aahe|ahe|zala|zali|kela|keli|karayche|nahiye|chalu|pahije|bhetla|milala)\b", re.I)


def _problem(out: str, lang: str) -> str | None:
    """Return a description of what is wrong with `out` for this language, or None if it is fine."""
    if lang in ("en", "hinglish") and _DEVANAGARI.search(out):
        return "it contains Devanagari letters but must use only Latin letters"
    if lang == "en":
        w = sorted({m.group(0).lower() for m in _ROMAN_INDIC.finditer(out)})
        if w:
            return "it still contains Hindi/Marathi words written in Roman letters, translate them to English: " + ", ".join(w)
    if lang in ("mr", "hi"):
        bad = [w for w in _LATIN_WORD.findall(out) if not w.isupper()]
        if bad:
            return "these words are still in Latin letters, write them in Devanagari: " + ", ".join(sorted(set(bad)))
    return None


def _chat_json(system: str, payload: dict) -> dict:
    req = _request([{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    r = httpx.post(req["url"], headers=req["headers"], json=req["body"], timeout=30, verify=_verify())
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def _system(lang: str) -> str:
    if lang == "en":
        return (
            "You clean up and translate workplace task-tracking notes INTO ENGLISH. Each input may be Hindi or Marathi in Devanagari, "
            "Hindi/Marathi written in Roman letters (Hinglish), English with spelling mistakes, or a mix. "
            "ALWAYS detect the language, correct spelling, and output correct concise English. Do not leave any Hindi/Marathi words untranslated "
            "(except people/place/product names and codes). Do not add information that is not there. "
            + SCRIPT_RULES["en"] + " Examples: 'server var deploy karne' -> 'Deploy to the server'; "
            "'Chakan Excel format fail ho raha hai' -> 'Chakan Excel format is failing'; "
            "'बारकोड स्कॅन मधील बग दुरुस्त करा' -> 'Fix the bug in barcode scanning'; 'waiting for acess from IT' -> 'Waiting for access from IT'. "
            'Reply ONLY with JSON: {"translations": [...]}, exactly one string per input, same order.'
        )
    return (
        f"You translate short workplace task-tracking notes from English into {LANGS[lang]}. "
        + SCRIPT_RULES[lang] + " Be concise; do not add or drop information. "
        'Reply ONLY with JSON: {"translations": [...]}, exactly one string per input, same order.'
    )


def _repair(src: str, draft: str, lang: str, problem: str) -> str:
    system = (f"You fix a translation. Target: {LANGS[lang]}. Rules: {SCRIPT_RULES[lang]} "
              'Reply ONLY with JSON: {"result": "..."} containing the corrected text.')
    out = _chat_json(system, {"source": src, "draft": draft, "problem": problem})["result"]
    return out if isinstance(out, str) and out.strip() else draft


def _translate(texts: list[str], lang: str) -> tuple[list[str], bool]:
    """Translate/clean texts into `lang` (cached). Never raises. Returns (results, ok); ok=False if the AI call failed."""
    result = {t: t for t in texts}
    todo = sorted({t for t in texts if t and t.strip()})
    if not todo or lang not in LANGS:
        return [result[t] for t in texts], True
    key = f"{lang}:{CACHE_VER}"
    ok = True
    with conn() as c:
        missing = []
        for t in todo:
            row = c.execute("SELECT result FROM translations WHERE text=? AND lang=?", (t, key)).fetchone()
            if row:
                result[t] = row["result"]
            else:
                missing.append(t)
        if missing and enabled():
            try:
                for i in range(0, len(missing), 30):
                    chunk = missing[i:i + 30]
                    outs = _chat_json(_system(lang), {"texts": chunk})["translations"]
                    if len(outs) != len(chunk) or not all(isinstance(x, str) for x in outs):
                        raise ValueError("bad translation shape")
                    for src, out in zip(chunk, outs):
                        problem = _problem(out, lang)
                        if problem:  # one automatic repair pass
                            try:
                                out = _repair(src, out, lang, problem)
                            except Exception as e:
                                print("repair failed:", e)
                        result[src] = out
                        if _problem(out, lang):  # still breaks the rules: do not cache it, and tell the caller
                            ok = False
                            print(f"[ai] translation to {lang} still invalid ({_problem(out, lang)}): {out!r}")
                        else:
                            c.execute("INSERT OR REPLACE INTO translations VALUES(?,?,?)", (src, key, out))
            except Exception as e:  # network/quota/format
                ok = False
                print("translation failed:", e)
        elif missing:
            ok = True  # AI not configured: nothing to translate with (UI shows a banner)
    return [result[t] for t in texts], ok


def translate_many(texts: list[str], lang: str) -> list[str]:
    return _translate(texts, lang)[0]


def to_english(text: str) -> tuple[str, bool]:
    """Spell-check + translate anything a user typed into English. Returns (english_text, ai_ok)."""
    text = (text or "").strip()
    if not text:
        return "", True
    out, ok = _translate([text], "en")
    return out[0], ok


def parse_task(text: str, today: str, names: list[str]) -> tuple[dict, bool]:
    """Pull task name / deadline / priority / assignee out of one free-text sentence. Never raises.
    Returns (fields, ai_ok); without AI the whole text becomes the title and no deadline is set."""
    text = (text or "").strip()
    plain = {"title": text, "deadline": None, "priority": None, "assignee": None}
    if not enabled():
        return plain, False
    system = (
        f"You turn one short task sentence (English, Hindi, Marathi or Hinglish) into fields. Today is {today}. "
        f"Team members: {', '.join(names) or 'none'}. Reply ONLY with JSON: "
        '{"title": str, "deadline": "YYYY-MM-DD" or null, "priority": "Low"|"Medium"|"High" or null, "assignee": one of the team member names or null}. '
        "title = a short task name WITHOUT the person's name and WITHOUT the deadline words. "
        "deadline = only if the sentence states or implies a date (tomorrow, Friday, 15th, next week = following Monday); otherwise null, never guess. "
        "priority = only if stated (urgent/asap -> High); otherwise null. assignee = only if a team member is named; otherwise null."
    )
    try:
        d = _chat_json(system, {"text": text})
        title = d.get("title") if isinstance(d.get("title"), str) and d["title"].strip() else text
        return {"title": title.strip(), "deadline": d.get("deadline") or None,
                "priority": d.get("priority"), "assignee": d.get("assignee")}, True
    except Exception as e:
        print("parse_task failed:", e)
        return plain, False


def summarize(facts: str, lang: str, scope: str) -> str:
    """AI summary of task facts in the chosen language. Raises on failure (caller falls back)."""
    lang = lang if lang in LANGS else "en"
    system = (
        f"You help a team lead understand {scope}. Write the summary in {LANGS[lang]}. " + SCRIPT_RULES[lang] + " "
        "Use ONLY the facts given; never invent tasks, numbers or names. Format: plain text. Each group starts with a line '• Label:' (a short label, then a colon) and every item of that group goes on its OWN following line starting with '   – '. Never put several items on one line and NEVER use the '|' character or ';' to separate items. No markdown, no headings, no preamble. "
        "ORDER IS FIXED. First a group 'Key points': the 2 to 4 most important things, taken from the KEY POINTS line (High priority items that are overdue, blocked or at risk come first). "
        + ("Then ONGOING tasks, then REMAINING tasks, then blockers. People marked HAS COMPLETED ALL TASKS get one line near the end (e.g. 'Priya has completed all tasks.'), not at the top. "
           if "team" in scope else
           "If the person is marked HAS COMPLETED ALL TASKS, reply with only one line saying so. Otherwise: Key points, then ONGOING (progress %, deadline), then REMAINING, then blockers. ")
        + "Last, one line 'Overall:' with overall progress. "
        "Inside each group list High priority first, then Medium, then Low, and say the priority for High items. "
"Skip a group that has nothing. Do not list COMPLETED tasks one by one unless nothing else exists."
    )
    req = _request([{"role": "system", "content": system}, {"role": "user", "content": facts}], json_mode=False)
    r = httpx.post(req["url"], headers=req["headers"], json=req["body"], timeout=45, verify=_verify())
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
