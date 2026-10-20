-- סכמת המערכת. להרצה פעם אחת ב־Supabase: SQL Editor → New query → הדבק → Run.
-- אפשר להריץ שוב בבטחה (idempotent).

create extension if not exists vector;

-- ───────────── עמותות ונתונים כספיים ─────────────
create table if not exists orgs (
  id          text primary key,
  name        text not null,
  field       text,
  profile     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create table if not exists financial_lines (
  id        bigserial primary key,
  org_id    text not null references orgs(id) on delete cascade,
  year      int  not null,
  kind      text not null check (kind in ('income', 'expense')),
  category  text not null,
  amount    numeric not null,
  unique (org_id, year, kind, category)
);

create table if not exists org_year_stats (
  org_id         text not null references orgs(id) on delete cascade,
  year           int  not null,
  donors         int,
  beneficiaries  int,
  primary key (org_id, year)
);

create table if not exists grants (
  id       bigserial primary key,
  org_id   text not null references orgs(id) on delete cascade,
  year     int  not null,
  grantor  text not null,
  type     text,
  amount   numeric not null,
  purpose  text
);

-- ───────────── מסמכים, חילוץ וקטעים ─────────────
create table if not exists documents (
  id          text primary key,              -- '<org_id>__<slot or file stem>'
  org_id      text not null references orgs(id) on delete cascade,
  doc_type    text,
  title       text,
  doc_date    date,
  source_path text,
  content     text not null,
  n_tokens    int,                            -- Claude tokens (count_tokens), for naive estimates
  created_at  timestamptz not null default now(),
  unique (id, org_id)
);

create table if not exists doc_extractions (
  doc_id   text primary key,
  org_id   text not null,
  data     jsonb not null,
  foreign key (doc_id, org_id) references documents(id, org_id) on delete cascade
);

create table if not exists chunks (
  id           bigserial primary key,
  org_id       text not null,
  doc_id       text not null,
  chunk_index  int  not null,
  content      text not null,
  n_tokens     int,
  embedding    vector(1024) not null,
  -- a chunk can only belong to a document of the same org
  foreign key (doc_id, org_id) references documents(id, org_id) on delete cascade,
  unique (doc_id, chunk_index)
);
create index if not exists chunks_org_idx on chunks (org_id);
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);

-- ───────────── כרטיס עמותה, דוחות, בדיקות איכות ─────────────
create table if not exists org_cards (
  id          bigserial primary key,
  org_id      text not null references orgs(id) on delete cascade,
  version     int  not null,
  after_doc   text,                           -- the document that produced this version
  content     text not null,
  n_words     int,
  created_at  timestamptz not null default now(),
  unique (org_id, version)
);

create table if not exists reports (
  id          bigserial primary key,
  org_id      text not null references orgs(id) on delete cascade,
  variant     text not null default 'correct',   -- 'correct' | 'naive_validation'
  content     text not null,
  model       text,
  cost_usd    numeric,
  meta        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create table if not exists eval_results (
  id          bigserial primary key,
  report_id   bigint not null references reports(id) on delete cascade,
  org_id      text not null references orgs(id) on delete cascade,
  score       numeric not null,
  details     jsonb not null,
  created_at  timestamptz not null default now()
);

-- ───────────── רישום עלויות ─────────────
create table if not exists api_calls (
  id                  bigserial primary key,
  uid                 text unique,
  ts                  timestamptz not null,
  component           text not null,
  org_id              text,
  model               text not null,
  kind                text not null,      -- actual | naive_estimate | middle_estimate | naive_validation | setup | discarded[_estimate]
  batch               boolean not null default false,
  input_tokens        int not null default 0,
  output_tokens       int not null default 0,
  cache_write_tokens  int not null default 0,
  cache_read_tokens   int not null default 0,
  cost_usd            numeric not null,
  ref                 text,
  note                text
);
alter table api_calls add column if not exists uid text unique;
alter table api_calls drop constraint if exists api_calls_ts_component_ref_kind_model_key;
-- Anthropic's own identifiers, so every row can be traced to the provider's records
alter table api_calls add column if not exists request_id text;   -- live calls (request-id header)
alter table api_calls add column if not exists message_id text;   -- msg_...
alter table api_calls add column if not exists batch_id   text;   -- msgbatch_...

-- ───────────── RLS: עמותה רואה רק את המידע שלה ─────────────
-- Requests from the app's users carry org_id in their JWT; the policy compares it to each row.
-- The server-side service_role key bypasses RLS by design, so the Python code ALSO filters by
-- org_id on every query (see src/db.py) and search goes only through match_chunks below.
do $$
declare t text;
begin
  foreach t in array array['orgs','financial_lines','org_year_stats','grants','documents',
                           'doc_extractions','chunks','org_cards','reports','eval_results','api_calls']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists org_isolation on %I', t);
    execute format(
      'create policy org_isolation on %I for select to authenticated using (%s = (auth.jwt() ->> ''org_id''))',
      t, case when t = 'orgs' then 'id' else 'org_id' end);
  end loop;
end $$;

-- ───────────── הרשאות לתפקידי ה־API ─────────────
-- service_role: the server-side scripts (bypasses RLS; the code filters by org_id).
-- authenticated: end users — read only, and RLS limits them to their own org. anon: nothing.
grant usage on schema public to service_role, authenticated;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant select on all tables in schema public to authenticated;
revoke all on all tables in schema public from anon;

-- ───────────── חיפוש וקטורי — org_id חובה ─────────────
create or replace function match_chunks(p_org_id text, p_query vector(1024), p_k int default 8)
returns table (id bigint, doc_id text, chunk_index int, content text, similarity float)
language plpgsql stable
as $$
begin
  if p_org_id is null or p_org_id = '' then
    raise exception 'match_chunks: org_id is required';
  end if;
  return query
    select c.id, c.doc_id, c.chunk_index, c.content, 1 - (c.embedding <=> p_query) as similarity
    from chunks c
    where c.org_id = p_org_id
    order by c.embedding <=> p_query
    limit p_k;
end $$;

revoke execute on function match_chunks(text, vector, int) from public, anon;
grant execute on function match_chunks(text, vector, int) to service_role, authenticated;
