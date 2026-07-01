"""
Embed every document's RAW text with BGE-M3 — full vector coverage now,
without waiting on modernization. (Modernization will be redone dictionary-grounded
later, then re-embedded.) Resumable: skips rows that already have an embedding.

Text source: `description` where present; otherwise falls back to `subject` (image
records have description=null but a meaningful subject). Other metadata fields
(accountName/branchName) are the same repeated label across many records, so they
are intentionally NOT included — they would collapse distinct records to near-
identical vectors.
"""
import os
import time

import httpx
from sqlalchemy import create_engine, text

from config import DATABASE_URL  # importing config runs load_dotenv()

EMBED_URL = os.environ["EMBEDDING_ENDPOINT"].rstrip("/") + "/v1/embeddings"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "baai/bge-m3")  # lowercase on this gateway (BAAI/ is rejected)
_API_KEY = os.environ.get("MODEL_API_KEY", "").strip()
_headers = {"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else {}  # gateway requires Bearer; empty ⇒ unauth endpoint
BATCH = 64

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
client = httpx.Client(timeout=120, headers=_headers)

done = 0
start = time.time()
while True:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT id, coalesce(nullif(json_data->>'description',''), json_data->>'subject') AS d "
                "FROM documents "
                "WHERE embedding IS NULL "
                "  AND coalesce(nullif(json_data->>'description',''), json_data->>'subject','') <> '' "
                "ORDER BY id LIMIT :n"
            ),
            {"n": BATCH},
        ).all()
    if not rows:
        break
    r = client.post(EMBED_URL, json={"model": EMBED_MODEL, "input": [row[1] for row in rows]})
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda x: x["index"])
    params = [
        {"id": rows[i][0], "e": "[" + ",".join(f"{x:.7f}" for x in data[i]["embedding"]) + "]"}
        for i in range(len(rows))
    ]
    with engine.begin() as c:
        c.execute(text("UPDATE documents SET embedding = CAST(:e AS vector) WHERE id = :id"), params)
    done += len(rows)
    if done % 640 == 0:
        print(f"embedded {done}  ({done / (time.time() - start):.1f}/s)", flush=True)

print(f"done: {done} in {time.time() - start:.0f}s", flush=True)
