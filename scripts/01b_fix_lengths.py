"""Stage 1b: fix document lengths after the first generation pass.

Haiku tends to stop at ~1,500–1,800 Hebrew words per response, and Hebrew costs ~4 output
tokens per word, so: (a) truncated documents are regenerated with a larger max_tokens;
(b) documents under 75% of their target length get a continuation (extra sections) appended.

    python scripts/01b_fix_lengths.py --dry-run
    python scripts/01b_fix_lengths.py
"""
import argparse
import re

import _bootstrap  # noqa: F401

from src import finance, llm
from src.ledger import ensure_budget
from src.loaders import _split_front_matter, front_matter
from src.settings import config, model_for, path
from src.synthetic import doc_plan, finance_gen
from src.synthetic.profiles import ORGS

TRUNCATED = {"elderly__bp2024a", "elderly__bp2026a", "youth__bp2024a", "youth__bp2026a"}
TOKENS_PER_WORD = 4.1          # measured in stage 1

EXTRA_SECTIONS = {
    "annual_report": "פירוט פעילות לפי רבעונים; שלושה סיפורי מוטבים (שמות בדויים) עם ציטוטים; שותפויות "
                     "(רשויות, בתי ספר, ארגונים) ומה כל אחת תרמה; מערך המתנדבים והכשרתם; נספח: עיקרי דוח ועדת "
                     "הביקורת לשנה (בלי סכומים כספיים חדשים); תודות לשותפים ולתורמים.",
    "grant_application": "נספח: מודל לוגי (תשומות → פעילויות → תפוקות → תוצאות); נספח: מדדי הצלחה ושיטת "
                         "המדידה וההערכה, כולל כלי איסוף נתונים; נספח: תיאור מקצועי של הצוות המוביל; נספח: "
                         "ניהול סיכונים ותוכנית חלופית; נספח: מכתבי תמיכה משותפים (תקציר).",
    "board_protocol": "המשך דיון בסעיפים נוספים בסדר היום: עדכון מנכ\"ל/ית, דיווח ועדת כספים (רק נתונים "
                      "כספיים שניתנו), שונות; החלטות ממוספרות; מועד הישיבה הבאה וחתימות.",
    "impact_update": "סיפור משתתף/ת נוסף; ציטוטים של צוות ושל הורים/משפחות; מבט קדימה לרבעון הבא; קריאה לתורמים.",
}

CONT_SYSTEM = doc_plan.SYSTEM + """
משימה נוספת: לפעמים תקבל מסמך קיים ותתבקש לכתוב לו המשך. במקרה כזה כתוב רק את הפרקים החדשים — בלי
לחזור על מה שכבר כתוב ובלי כותרת ראשית חדשה — כך שאפשר יהיה להדביק אותם ישירות בסוף המסמך הקיים.
שמור על אותו סגנון, אותם שמות ואותם נתונים בדיוק.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    wpp = config()["data"]["words_per_page"]
    reqs, plan = [], {}
    for org in ORGS:
        fin = finance_gen.generate(org)
        m = finance.metrics(fin)
        for i, (slot, dtype, date, pages, years) in enumerate(doc_plan.SLOTS):
            if slot not in {s[0] for s in doc_plan.org_slots(org["id"])}:
                continue
            cid = f"{org['id']}__{slot}"
            f = path("synthetic_dir") / org["id"] / "docs" / f"{i + 1:02d}_{slot}.md"
            meta, body = _split_front_matter(f.read_text(encoding="utf-8"))
            words = len(re.findall(r"\S+", body))
            target = pages * wpp
            base_prompt = doc_plan.user_prompt(org, fin, m, slot, dtype, date, pages, years, wpp)
            if cid in TRUNCATED:
                plan[cid] = ("regen", f, meta)
                reqs.append(llm.Req(custom_id=cid, model=model_for("simple"), system=CONT_SYSTEM, cache_system=True,
                                    user=base_prompt, max_tokens=int(target * TOKENS_PER_WORD * 1.6),
                                    effort="high", thinking_off=True, org_id=org["id"]))
            elif words < 0.75 * target:
                missing = target - words
                plan[cid] = ("extend", f, meta)
                user = (f"{base_prompt}\n\n## המסמך הקיים (כ־{words:,} מילים)\n<existing>\n{body}\n</existing>\n\n"
                        f"## המשימה\nהמסמך קצר מהיעד. כתוב לו המשך של כ־{missing:,} מילים, עם הפרקים הבאים: "
                        f"{EXTRA_SECTIONS[dtype]}\nכתוב רק את ההמשך.")
                reqs.append(llm.Req(custom_id=cid, model=model_for("simple"), system=CONT_SYSTEM, cache_system=True,
                                    user=user, max_tokens=min(int(missing * TOKENS_PER_WORD * 1.6), 32000),
                                    effort="high", thinking_off=True, org_id=org["id"]))

    counts = [llm.count_tokens(r) for r in reqs]
    worst = llm.worst_case_cost(reqs, counts, batch=True)
    print(f"{sum(p[0] == 'regen' for p in plan.values())} to regenerate, "
          f"{sum(p[0] == 'extend' for p in plan.values())} to extend | input {sum(counts):,} | worst ${worst:.3f}")
    if args.dry_run:
        return
    ensure_budget(worst, "fix document lengths")
    results = llm.run_batch("gen_docs_v2_fix", reqs, component="setup", kind="setup")
    for cid, res in results.items():
        mode, f, meta = plan[cid]
        _, body = _split_front_matter(f.read_text(encoding="utf-8"))
        new_body = res.text.strip() if mode == "regen" else body + "\n\n" + res.text.strip()
        f.write_text(front_matter(meta) + new_body + "\n", encoding="utf-8")
        print(f"{cid:<26} {mode:<6} -> {len(re.findall(r'\S+', new_body)):>5} words  stop={res.stop_reason}")
    print(f"cost ${sum(r.cost_usd for r in results.values()):.4f}")


if __name__ == "__main__":
    main()
