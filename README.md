# מערכת דוחות לעמותות — הדגמה עם השוואת עלויות

אב־טיפוס שקולט נתונים כספיים ומסמכים של עמותות, מפיק דוח מקצועי לכל עמותה ומאפשר לשאול שאלות על המסמכים.
לצד כל רכיב המערכת מציגה **עלות נאיבית**, **עלות ביניים** ו**עלות בפועל**, כולן מדודות.

| רכיב | נאיבי | נכון |
|---|---|---|
| 1. חישובים כספיים | Sonnet מחשב מהנתונים הגולמיים | קוד Python (0$) |
| 2. קליטת מסמכים | אין — המסמכים נשלחים מחדש בכל פעולה | Haiku מחלץ JSON (Batch), חיתוך לקטעים, embeddings ל־Voyage, שמירה ב־pgvector |
| 3. כרטיס עמותה | אין — כל פעם קוראים את כל ההיסטוריה | Haiku מעדכן כרטיס (≤1,500 מילים) מכרטיס קיים + מסמך חדש |
| 4. דוח | Sonnet + כל המסמכים + נתונים גולמיים | Sonnet + חישובים + כרטיס + 9 קטעי RAG, caching + Batch |
| 5. צ'אט | Sonnet + כל המסמכים | RAG מסונן לפי org_id + Haiku, עם מקורות |

## התקנה

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # ומלאו את 4 המפתחות
```

ב־Supabase: SQL Editor ← הדביקו את כל `sql/schema.sql` ← Run. הסקריפט יוצר את הטבלאות, את pgvector,
את מדיניות ה־RLS ואת פונקציית החיפוש `match_chunks` (שבה org_id הוא חובה).

## הרצה — שלב אחרי שלב

לכל סקריפט שעולה כסף יש `--dry-run` שמציג ספירת טוקנים מדויקת והערכת עלות, בלי להריץ.
כל סקריפט עוצר לפני שהעלות המצטברת עלולה לעבור את `budget.stop_at_usd` ב־`config.yaml`.

```powershell
.venv\Scripts\python scripts\apply_schema.py           # יצירת הסכמה ב־Supabase (דורש SUPABASE_DB_URL ב־.env)
.venv\Scripts\python scripts\00_check_setup.py          # בדיקת מפתחות וחיבורים
.venv\Scripts\python scripts\01_generate_data.py        # נתונים סינתטיים: 5 עמותות, 50 מסמכים (Haiku, Batch)
.venv\Scripts\python scripts\01b_fix_lengths.py         # השלמת אורך למסמכים שיצאו קצרים
.venv\Scripts\python scripts\02_ingest.py               # רכיב 2: קליטה, חילוץ, embeddings
.venv\Scripts\python scripts\03_build_cards.py          # רכיב 3: כרטיסי עמותה, מסמך אחר מסמך
.venv\Scripts\python scripts\04_reports.py              # רכיבים 1+4: חישובים + דוחות (Sonnet, Batch) + בדיקת איכות
.venv\Scripts\python scripts\05_chat.py                 # רכיב 5: 25 שאלות לדוגמה
.venv\Scripts\python scripts\06_validate_naive.py       # הרצה אמיתית של כל גרסה נאיבית, פעם אחת, על עמותה אחת
.venv\Scripts\python scripts\07_isolation_check.py      # בדיקת בידוד בין עמותות: בקוד וב־RLS
.venv\Scripts\python scripts\08_reconcile.py            # התאמת היומן מול Anthropic (חינם): Batch שורה־שורה + סכומים יומיים ל־Console
.venv\Scripts\python -m pytest -q tests                 # בדיקות יחידה (חישובים, תמחור, evals)
.venv\Scripts\streamlit run app\streamlit_app.py        # הממשק
```

סקריפטים של Batch שומרים את מזהה ה־Batch ב־`data/batches/`. אם סקריפט נקטע — מריצים אותו שוב והוא ממשיך
מאותו Batch, בלי לשלם פעמיים.

**Voyage בלי אמצעי תשלום** מוגבל ל־3 בקשות ול־10K טוקנים בדקה. המערכת מאטה את עצמה אוטומטית
(`embeddings.throttle` ב־`config.yaml`). אחרי שמוסיפים אמצעי תשלום, משנים ל־`false` והקליטה מהירה פי עשרות.

## איך נמדדות העלויות

- **בפועל:** כל קריאה ל־API עוברת דרך `src/llm.py`, שמתמחר את שדה ה־`usage` (קלט, פלט, כתיבה/קריאה מהמטמון)
  לפי `pricing.yaml`, כולל הנחת Batch ו־caching, ורושם שורה ב־`api_calls` (קובץ מקומי + טבלה ב־Supabase).
- **נאיבי:** הבקשה הנאיבית נבנית במלואה ונספרת ב־token counting API (חינם). הפלט מונח זהה לפלט של הגרסה הנכונה.
- **ביניים:** אותה בקשה נאיבית, עם Batch לעבודה אסינכרונית (חישובים, כרטיס, דוח) ו־caching לשאלות ברצף.
- **אימות:** `06_validate_naive.py` מריץ כל גרסה נאיבית באמת פעם אחת ומשווה הערכה מול חיוב בפועל.
- **התאמה מול Anthropic:** כל שורה ביומן נושאת את המזהים של Anthropic (`request_id` לקריאה רגילה, `batch_id` ל־Batch,
  `message_id` לשתיהן). `08_reconcile.py` מוריד מחדש את תוצאות ה־Batch מ־Anthropic ומשווה טוקנים שורה־שורה,
  ומפיק סכומים יומיים לפי מודל להשוואה עם דפי Usage/Cost ב־Console. התוצאה מוצגת בעמוד "אימות המספרים".
- **עדכון מחירים:** רק `pricing.yaml`. שום מחיר לא כתוב בקוד.

## החלפת הנתונים הסינתטיים בנתונים אמיתיים

הצנרת לא יודעת אם הנתונים סינתטיים. כל מה שצריך הוא תיקייה באותו מבנה:

```
data/real/
  <org_id>/                      מזהה באנגלית, בלי רווחים (למשל: kanfei-noar)
    profile.json                 {"id": "<org_id>", "name": "...", "field": "...", "city": "..."}
    finance.json                 ראו פורמט למטה
    facts.json                   (לא חובה) עובדות ידועות לבדיקת איכות הדוח
    questions.json               (לא חובה) שאלות לדוגמה
    docs/
      2024_annual_report.pdf     PDF / Word (.docx) / Markdown / טקסט
      2024_annual_report.pdf.meta.json   (לא חובה) {"title": "...", "type": "annual_report", "date": "2025-04-27"}
```

- **מסמכים:** PDF ו־Word נקראים אוטומטית (`src/loaders.py`). בלי קובץ meta — הכותרת היא שם הקובץ והתאריך הוא
  תאריך שינוי הקובץ. סוגים מוכרים: `annual_report`, `board_protocol`, `grant_application`, `impact_update`, `other`.
  PDF סרוק (תמונה) צריך OCR לפני הקליטה.
- **finance.json:**
  ```json
  {"org_id": "kanfei-noar", "currency": "ILS", "years": {
    "2025": {
      "income":   {"תרומות מיחידים": 1577000, "קרנות ופילנתרופיה": 1581000, "מענקים ממשלתיים ורשויות": 1614000, "הכנסות עצמיות": 417000},
      "expenses": {"שכר ונלווים": 2762000, "תוכניות ופעילות": 1417000, "שכירות ואחזקה": 398000, "הנהלה וכלליות": 340000, "גיוס משאבים": 256000},
      "donors": 1420, "beneficiaries": 745,
      "grants": [{"grantor": "עיריית באר שבע", "type": "government", "amount": 1094000, "purpose": "..."}]
    }}}
  ```
  שמות סעיפי ההכנסה וההוצאה חופשיים. מדדי "שיעור הנהלה וגיוס", "הוצאות תוכניות" ו"תרומה ממוצעת מיחיד"
  מזהים את הסעיפים לפי השמות שבדוגמה. אם השמות שונים, עדכנו את `src/finance.py`.
- **facts.json** (לבדיקת איכות): `[{"id": "income_2025", "label": "סך ההכנסות ב־2025", "type": "ils", "value": 5189000}]`.
  סוגים אפשריים: `ils`, `pct`, `int`, `grant` (עם `grantor`).

ואז מריצים את אותם סקריפטים עם `--data data/real`:

```powershell
.venv\Scripts\python scripts\02_ingest.py --data data/real
.venv\Scripts\python scripts\03_build_cards.py --data data/real
.venv\Scripts\python scripts\04_reports.py --data data/real --label reports_real_v1
.venv\Scripts\python scripts\05_chat.py --data data/real
```

## אבטחה ובידוד בין עמותות

- המפתחות נמצאים רק ב־`.env`, והקובץ נמצא ב־`.gitignore`.
- **RLS** מופעל על כל הטבלאות. משתמש קצה עם JWT רואה רק שורות שבהן `org_id` תואם לטוקן שלו.
- מפתח ה־service של השרת עוקף את RLS מעצם הגדרתו. לכן `src/db.py` מחייב `org_id` בכל פונקציה ומסנן לפיו.
  החיפוש עובר רק דרך `match_chunks(org_id, ...)`, ו־`src/rag.py` בודק שוב שכל קטע שחזר שייך לעמותה.
- במסד הנתונים, מפתח זר מורכב `(doc_id, org_id)` מונע שיוך של קטע למסמך של עמותה אחרת.

## מבנה הקוד

```
pricing.yaml / config.yaml      מחירים, מודלים ופרמטרים
src/llm.py                      כל קריאה ל־Claude: קריאות רגילות, Batch, ספירת טוקנים ותמחור
src/ledger.py                   רישום העלויות ובדיקת התקציב
src/finance.py                  רכיב 1 (קוד)            src/finance_naive.py   רכיב 1 (נאיבי + השוואת דיוק)
src/ingest.py, chunking.py      רכיב 2                  src/embeddings.py      Voyage
src/org_card.py                 רכיב 3                  src/report.py          רכיב 4
src/rag.py, chat.py             רכיב 5                  src/naive.py           הערכות נאיביות וביניים
src/evals.py                    בדיקת איכות             src/costs.py           טבלאות ותחזית
src/loaders.py                  קריאת md/pdf/docx (נקודת ההחלפה לנתונים אמיתיים)
src/synthetic/                  יצירת הנתונים הסינתטיים
app/                            ממשק Streamlit (עברית, RTL)
```
