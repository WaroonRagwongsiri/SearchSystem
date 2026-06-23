import glob
import json
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db import Base, engine
from models import Document  # noqa: F401  (registers model on Base.metadata)

CHUNK = 1000

# ponytail: one-line table creation. Add Alembic only when we need to ALTER the table
# (add embedding/tsvector columns); stamp current schema as baseline then.
Base.metadata.create_all(engine)

FILES = sorted(glob.glob("all_documents/*.json"))
parse_err: list[str] = []
n_items = 0
start = time.time()

with engine.begin() as conn:
    for f in FILES:
        try:
            items = json.load(open(f, encoding="utf-8")).get("items", [])
        except Exception:
            parse_err.append(Path(f).name)  # trust boundary: bad file → skip + log, don't crash
            continue
        n_items += len(items)
        rows = [{"id": it["id"], "json_data": it} for it in items if it.get("id")]
        for i in range(0, len(rows), CHUNK):
            stmt = pg_insert(Document).values(rows[i:i + CHUNK])
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={"json_data": stmt.excluded.json_data},  # idempotent re-runs
                )
            )

with engine.connect() as conn:
    stored = conn.execute(text("SELECT count(*) FROM documents")).scalar_one()

print(f"files read    : {len(FILES)}")
print(f"files skipped : {len(parse_err)}  {parse_err}")
print(f"items seen    : {n_items}")
print(f"rows in DB    : {stored}")
print(f"elapsed       : {time.time() - start:.1f}s")
assert stored == n_items == 313600, f"mismatch: stored={stored} items={n_items}"
print("OK: all items stored.")
