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


def provider() -> str | None:
    """Which LLM to use: LLM_PROVIDER if set, else whichever key is present (azure > openai > groq)."""
    p = os.environ.get("LLM_PROVIDER", "").lower()
    if p in ("azure", "openai", "groq"):
        return p
    if os.environ.get("AZURE_OPENAI_API_KEY"):
        return "azure"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return None


def describe() -> str:
    p = provider()
    if p == "azure":
        return f"Azure OpenAI, deployment {os.environ.get('AZURE_OPENAI_DEPLOYMENT', '?')}"
    if p == "openai":
        return f"OpenAI-compatible, model {os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}"
    if p == "groq":
        return f"Groq, model {os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')}"
    return "none"


def enabled() -> bool:
    return provider() is not None


def _request(messages: list[dict]) -> dict:
    """Build (url, headers, body) for the configured provider. All three speak the OpenAI chat format."""
    p = provider()
    env = os.environ
    if p == "azure":
        base = env["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        url = (f"{base}/openai/deployments/{env['AZURE_OPENAI_DEPLOYMENT']}/chat/completions"
               f"?api-version={env.get('AZURE_OPENAI_API_VERSION', '2024-06-01')}")
        return {"url": url, "headers": {"api-key": env["AZURE_OPENAI_API_KEY"]},
                "body": {"messages": messages, "temperature": 0, "response_format": {"type": "json_object"}}}
    if p == "openai":
        base = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model, key = env.get("OPENAI_MODEL", "gpt-4o-mini"), env["OPENAI_API_KEY"]
    else:
        base, key = "https://api.groq.com/openai/v1", env["GROQ_API_KEY"]
        model = env.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    return {"url": f"{base}/chat/completions", "headers": {"Authorization": f"Bearer {key}"},
            "body": {"model": model, "messages": messages, "temperature": 0,
                     "response_format": {"type": "json_object"}}}


def _call(texts: list[str], target: str) -> list[str]:
    """Translate a batch of texts into `target`. Raises on failure."""
    system = (
        f"You translate workplace task-tracking text into {target}. The input may be in Hindi, Marathi, "
        "English or Hinglish (or a mix). Keep names, product names, codes and technical terms unchanged. "
        "Be concise and natural. If a text is already in the target language return it unchanged. "
        'Reply ONLY with JSON: {"translations": [...]} with exactly one string per input, same order.'
    )
    req = _request([{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps({"texts": texts}, ensure_ascii=False)}])
    r = httpx.post(req["url"], headers=req["headers"], json=req["body"], timeout=30, verify=_verify())
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
