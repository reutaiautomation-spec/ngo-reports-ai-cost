"""Applies sql/schema.sql using SUPABASE_DB_URL (direct Postgres). Safe to re-run."""
import _bootstrap  # noqa: F401

import psycopg

from src.settings import ROOT, env

TABLES = ["orgs", "financial_lines", "org_year_stats", "grants", "documents", "doc_extractions",
          "chunks", "org_cards", "reports", "eval_results", "api_calls"]

if __name__ == "__main__":
    sql = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(env("SUPABASE_DB_URL"), autocommit=True) as conn:
        conn.execute(sql)
        conn.execute("notify pgrst, 'reload schema'")          # make PostgREST see the new tables now
        rls = dict(conn.execute(
            "select relname, relrowsecurity from pg_class where relname = any(%s) and relkind = 'r'", (TABLES,)).fetchall())
        ext = conn.execute("select extversion from pg_extension where extname = 'vector'").fetchone()
        fn = conn.execute("select count(*) from pg_proc where proname = 'match_chunks'").fetchone()[0]
    print(f"pgvector {ext[0] if ext else 'MISSING'} | match_chunks: {'ok' if fn else 'MISSING'}")
    for t in TABLES:
        print(f"  {t:<16} {'RLS on' if rls.get(t) else ('RLS OFF' if t in rls else 'MISSING')}")
