"""Translation layer. Uses Groq (OpenAI-compatible API); falls back to passthrough without a key."""
import json
import os
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
    """Use the OS certificate store (works behind corporate proxies); fall back to the default bundle."""
    try:
        import ssl

        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return True


def enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _call(texts: list[str], target: str) -> list[str]:
    """Translate a batch of texts into `target` using Groq. Raises on failure."""
    system = (
        f"You translate workplace task-tracking text into {target}. The input may be in Hindi, Marathi, "
        "English or Hinglish (or a mix). Keep names, product names, codes and technical terms unchanged. "
        "Be concise and natural. If a text is already in the target language return it unchanged. "
        'Reply ONLY with JSON: {"translations": [...]} with exactly one string per input, same order.'
    )
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={
            "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps({"texts": texts}, ensure_ascii=False)},
            ],
        },
        timeout=30,
        verify=_verify(),
    )
    r.raise_for_status()
    out = json.loads(r.json()["choices"][0]["message"]["content"])["translations"]
    if len(out) != len(texts) or not all(isinstance(x, str) for x in out):
        raise ValueError("bad translation shape")
    return out


def translate_many(texts: list[str], lang: str) -> list[str]:
    """Translate texts to lang code, using the cache. Never raises; falls back to the input text."""
    result = {t: t for t in texts}
    todo = sorted({t for t in texts if t and t.strip()})
    if not todo or lang not in LANGS:
        return [result[t] for t in texts]
    with conn() as c:
        missing = []
        for t in todo:
            row = c.execute("SELECT result FROM translations WHERE text=? AND lang=?", (t, lang)).fetchone()
            if row:
                result[t] = row["result"]
            else:
                missing.append(t)
        if missing and enabled():
            try:
                for i in range(0, len(missing), 30):
                    chunk = missing[i:i + 30]
                    for src, out in zip(chunk, _call(chunk, LANGS[lang])):
                        result[src] = out
                        c.execute("INSERT OR REPLACE INTO translations VALUES(?,?,?)", (src, lang, out))
            except Exception as e:  # network/quota/format -> show original rather than fail
                print("translation failed:", e)
    return [result[t] for t in texts]


def to_english(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return translate_many([text], "en")[0]
