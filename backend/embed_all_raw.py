"""
Embed every document's RAW description with BGE-M3 — full vector coverage now,
without waiting on modernization. (Modernization will be redone dictionary-grounded
later, then re-embedded.) Resumable: skips rows that already have an embedding.
"""
import os
import time

import httpx
from sqlalchemy import create_engine, text

from config import DATABASE_URL  # importing config runs load_dotenv()

EMBED_URL = os.environ["EMBEDDING_ENDPOINT"].rstrip("/") + "/v1/embeddings"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
BATCH = 64

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
client = httpx.Client(timeout=120)

done = 0
start = time.time()
while True:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT id, json_data->>'description' AS d FROM documents "
                "WHERE embedding IS NULL AND coalesce(json_data->>'description','') <> '' "
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
