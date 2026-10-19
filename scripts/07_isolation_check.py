"""Org isolation check — two independent layers.

1. Application layer: for every org, search with the OTHER orgs' sample questions (which are
   about content that exists only elsewhere) and assert every returned chunk belongs to the org.
2. Database layer (RLS): impersonate an end user (role `authenticated` with org_id in the JWT
   claims) over a direct connection and assert each table returns only that org's rows.
   Also asserts match_chunks rejects a missing org_id.

    python scripts/07_isolation_check.py
"""
import json

import _bootstrap  # noqa: F401

import psycopg

from src import db, rag
from src.loaders import load_json, org_ids
from src.settings import env, path

TABLES = ["orgs", "documents", "chunks", "doc_extractions", "org_cards", "reports", "financial_lines", "grants"]


def app_layer() -> int:
    data_dir = path("synthetic_dir")
    orgs = org_ids(data_dir)
    failures = 0
    for org in orgs:
        foreign = [q["question"] for o in orgs if o != org for q in (load_json(data_dir, o, "questions.json") or [])[:2]]
        hits, _ = rag.retrieve(org, foreign, 6, component="isolation_test", ref=f"isolation__{org}")
        leaked = [h.doc_id for h in hits if not h.doc_id.startswith(f"{org}__")]
        failures += len(leaked)
        print(f"  [app] {org:<12} {len(foreign)} foreign questions -> {len(hits)} chunks, leaked: {leaked or 'none'}")
    return failures


def db_layer() -> int:
    failures = 0
    with psycopg.connect(env("SUPABASE_DB_URL")) as conn:
        for org in org_ids(path("synthetic_dir")):
            with conn.transaction():
                conn.execute("set local role authenticated")
                conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps({"org_id": org}),))
                for t in TABLES:
                    col = "id" if t == "orgs" else "org_id"
                    seen = [r[0] for r in conn.execute(f"select distinct {col} from {t}").fetchall()]
                    bad = [s for s in seen if s != org]
                    failures += len(bad)
                    if bad:
                        print(f"  [rls] {org}: table {t} exposed {bad}")
            print(f"  [rls] {org:<12} sees only its own rows in {len(TABLES)} tables")
        # an end user with no org_id sees nothing
        with conn.transaction():
            conn.execute("set local role authenticated")
            conn.execute("select set_config('request.jwt.claims', '{}', true)")
            n = conn.execute("select count(*) from chunks").fetchone()[0]
            print(f"  [rls] no org_id in token -> {n} chunks visible")
            failures += n
    try:
        db.sb().rpc("match_chunks", {"p_org_id": "", "p_query": [0.0] * 1024, "p_k": 3}).execute()
        print("  [fn] match_chunks accepted an empty org_id!")
        failures += 1
    except Exception as e:
        print(f"  [fn] match_chunks without org_id -> rejected ({str(e)[:60]}...)")
    return failures


if __name__ == "__main__":
    print("application layer:")
    f1 = app_layer()
    print("database layer:")
    f2 = db_layer()
    print(f"\nRESULT: {'PASS' if f1 + f2 == 0 else 'FAIL'} ({f1 + f2} leaks)")
