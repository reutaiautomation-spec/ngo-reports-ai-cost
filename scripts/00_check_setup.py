"""Stage 0: verify keys and connectivity with the cheapest possible calls (~$0.0001)."""
import _bootstrap  # noqa: F401

from src import llm
from src.settings import env, model_for


def check_anthropic():
    env("ANTHROPIC_API_KEY")
    req = llm.Req(custom_id="setup-check", model=model_for("simple"), user="ענה במילה אחת: מה בירת ישראל?",
                  max_tokens=50, effort="low", thinking_off=True)
    n = llm.count_tokens(req)
    res = llm.call(req, component="setup", kind="setup", note="connectivity check")
    print(f"  Anthropic OK — count_tokens={n}, real input={res.usage.input_tokens}, "
          f"output={res.usage.output_tokens}, cost=${res.cost_usd:.6f}, answer={res.text.strip()!r}")


def check_voyage():
    import voyageai
    env("VOYAGE_API_KEY")
    r = voyageai.Client().embed(["בדיקת חיבור"], model=model_for("embeddings"), input_type="query")
    print(f"  Voyage OK — dim={len(r.embeddings[0])}, tokens={r.total_tokens}")


def check_supabase():
    from supabase import create_client
    sb = create_client(env("SUPABASE_URL"), env("SUPABASE_SERVICE_KEY"))
    try:
        rows = sb.table("orgs").select("id").limit(1).execute().data
        print(f"  Supabase OK — orgs table reachable ({len(rows)} rows sampled)")
    except Exception as e:  # schema not applied yet is expected before stage 2
        print(f"  Supabase connected, but schema missing? Run sql/schema.sql. ({e.__class__.__name__}: {e})")


if __name__ == "__main__":
    for name, fn in [("Anthropic", check_anthropic), ("Voyage", check_voyage), ("Supabase", check_supabase)]:
        print(f"[{name}]")
        try:
            fn()
        except Exception as e:
            print(f"  FAILED: {e.__class__.__name__}: {e}")
