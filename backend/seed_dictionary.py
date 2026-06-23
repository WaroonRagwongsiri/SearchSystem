import csv

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db import engine
from models import Dictionary

# utf-8-sig strips the BOM. Word→ancient_word, Definition→modern_definition.
# `References` column (parent/child relations) is dropped — not in the model; re-add if the
# modernization prompt ever needs it.
CSV = "dict_โบราณ.csv"
CHUNK = 500

with open(CSV, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

mapped = [
    {"ancient_word": r["Word"].strip(), "modern_definition": r["Definition"]}
    for r in rows
    if (r.get("Word") or "").strip()
]

with engine.begin() as conn:
    for i in range(0, len(mapped), CHUNK):
        stmt = pg_insert(Dictionary).values(mapped[i:i + CHUNK])
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["ancient_word"],
                set_={"modern_definition": stmt.excluded.modern_definition},
            )
        )
    total = conn.execute(text("SELECT count(*) FROM dictionary")).scalar_one()

print(f"CSV rows         : {len(rows)}")
print(f"mapped           : {len(mapped)}")
print(f"dictionary total : {total}")
assert total == len(mapped) == 1097, f"mismatch: db={total} mapped={len(mapped)}"
print("OK: dictionary seeded.")
