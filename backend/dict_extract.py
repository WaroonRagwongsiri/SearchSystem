"""
Pure modern-word extraction helper — no module-level engine/env/client.

Shared by the batch CLI (modernize_dictionary.py) and the synchronous on-add
extraction in main.py. The caller injects the httpx client + endpoints, so this
module is safe to import anywhere (it never touches the DB or reads the env).

Returns (modern_word, error): modern_word is None ONLY on an exception (the LLM
call raised); garbage output falls back to the identity (the ancient word) and
counts as success — identity is always safe, a hallucinated equivalent is not.
"""

SYSTEM = (
    "You extract the single best modern Thai equivalent of a historical Thai dictionary word. "
    "Read the entry and output ONLY one modern Thai word — no quotes, no list, no commas, "
    "no part-of-speech, no explanation, no trailing punctuation. "
    "Rules: if the entry gives an explicit modern form (after 'ดู', 'ปัจจุบันเรียกว่า', "
    "or as the headword gloss), output that single form; "
    "modernize old spelling to current Thai orthography (e.g. เฑียร->เทียร, ฑ->น); "
    "do not reorder or rearrange syllables of the word; "
    "do not invent a meaning — if uncertain or no modern form is determinable, "
    "output the word unchanged."
)

# Few-shot from real entries in this dictionary.
FEW_SHOT = """Examples (ancient word -> one modern equivalent):
สรวป -> สรุป
ขยุม ๑ -> ขยม
กงเวียน -> วงเวียน
กฎมณเฑียรบาล -> กฎมนเทียรบาล
กราล -> กราน
โกรด -> โกรก
กฎ -> กฎ"""

DEF_MAX = 2000  # cap definition chars sent to the model (rare entries are long)


def _clean(s: str) -> str:
    # Tolerate the model wrapping output in quotes / a trailing period / stray markers.
    s = s.strip().strip("“。\"'").strip()
    if s.endswith("."):
        s = s[:-1]
    return s.strip()


def _valid_thai(s: str) -> bool:
    """True if s is a plausible modern Thai word: non-empty, <=40 chars, Thai-only.
    Rejects the model's failure mode of emitting English meta-commentary or CJK on
    hard entries — garbage here would poison the document-modernization prompt."""
    if not s or len(s) > 40:
        return False
    return all(("฀" <= ch <= "๿") or ch in " ,." for ch in s)  # Thai block U+0E00–U+0E7F


def extract_modern_word(ancient, definition, *, client, chat_url, model):
    """Return (modern_word_or_None, error_or_None).

    modern_word is None only when the LLM call raised; on garbage output the ancient
    word is returned as the identity fallback (still a success, error is None).
    """
    try:
        r = client.post(
            chat_url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": (
                        f"{FEW_SHOT}\n\n"
                        f"Word: {ancient}\n"
                        f"Entry: {definition[:DEF_MAX]}\n"
                        f"Modern equivalent:"
                    )},
                ],
                "temperature": 0,
                "max_tokens": 48,
            },
        )
        r.raise_for_status()
        mod = _clean(r.json()["choices"][0]["message"]["content"])
        # Reject garbage (non-Thai / over-long); fall back to the word itself.
        if not _valid_thai(mod):
            mod = ancient
        return (mod, None)
    except Exception as e:  # one bad word must not poison the caller
        return (None, str(e)[:200])
