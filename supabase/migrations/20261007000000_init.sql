-- Phase 1 schema. Spec §4.

create table companies (
  id bigint generated always as identity primary key,
  name text not null,
  ats text not null check (ats in ('greenhouse','lever','ashby','workday','smartrecruiters','workable')),
  slug text not null,
  workday_host text,
  workday_site text,
  domain text,
  tier text not null default 'warm' check (tier in ('hot','warm','cold','inactive')),
  curated_hot boolean not null default false,
  last_polled_at timestamptz,
  last_success_at timestamptz,
  fail_count int not null default 0,
  consecutive_404s int not null default 0,
  first_404_at timestamptz,
  job_ids_hash text,
  last_intern_seen_at timestamptz,
  discovered_from text,
  h1b_count int,
  h1b_fiscal_year int,
  created_at timestamptz not null default now(),
  unique (ats, slug)
);

create table jobs (
  id uuid primary key default gen_random_uuid(),
  company_id bigint not null references companies(id) on delete cascade,
  title text not null,
  normalized_title text not null,
  category text not null,
  term text,
  duration_months int,
  location_raw text not null default '',
  locations jsonb not null default '[]',
  country text not null check (country in ('CA','US','BOTH','UNKNOWN')),
  work_mode text not null default 'unknown' check (work_mode in ('onsite','hybrid','remote','unknown')),
  location_unclear boolean not null default false,
  pay_min numeric,
  pay_max numeric,
  pay_currency text,
  pay_period text check (pay_period in ('hour','year','month','week')),
  pay_hourly_min numeric,
  pay_hourly_max numeric,
  pay_raw text,
  visa_signals text[] not null default '{}',
  visa_status text not null check (visa_status in ('open','blocked','unknown')),
  flags text[] not null default '{}',
  evidence jsonb not null default '{}',
  fingerprint text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  source_posted_at timestamptz,
  status text not null default 'open' check (status in ('open','closed')),
  closed_at timestamptz,
  miss_count int not null default 0,
  freshness text not null default 'fresh'
    check (freshness in ('fresh','repost','reopened','refreshed','recurring')),
  repost_of uuid references jobs(id) on delete set null,
  repost_count int not null default 0,
  best_url text not null,
  updated_at timestamptz not null default now()
);
create index jobs_fingerprint_idx on jobs (fingerprint);
create index jobs_feed_idx on jobs (status, country, first_seen_at desc);
create index jobs_company_idx on jobs (company_id);

create table job_sources (
  id bigint generated always as identity primary key,
  job_id uuid not null references jobs(id) on delete cascade,
  company_id bigint not null references companies(id) on delete cascade,
  source text not null,
  source_job_id text not null,
  url text not null,
  source_posted_at timestamptz,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (source, source_job_id)
);
create index job_sources_company_idx on job_sources (company_id, source);
create index job_sources_job_idx on job_sources (job_id);

create table scrape_runs (
  id bigint generated always as identity primary key,
  workflow text not null,
  source text not null,
  started_at timestamptz not null,
  finished_at timestamptz not null,
  companies_polled int not null default 0,
  jobs_seen int not null default 0,
  jobs_new int not null default 0,
  jobs_closed int not null default 0,
  errors int not null default 0,
  error_samples jsonb not null default '[]'
);

create table source_state (
  source text primary key,
  cooldown_until timestamptz,
  backoff_seconds int not null default 0,
  last_commit_sha text,
  notes text
);

create view jobs_feed with (security_invoker = true) as
select j.*, c.name as company_name, c.domain as company_domain,
       c.h1b_count, c.h1b_fiscal_year
from jobs j
join companies c on c.id = j.company_id
where j.status = 'open';

-- Row-level security: the website's anon key may only read; the scraper connects as the
-- table owner (bypasses RLS).
alter table companies enable row level security;
alter table jobs enable row level security;
alter table job_sources enable row level security;
alter table scrape_runs enable row level security;
alter table source_state enable row level security;

create policy read_companies on companies for select to anon, authenticated using (true);
create policy read_open_jobs on jobs for select to anon, authenticated using (status = 'open');
create policy read_job_sources on job_sources for select to anon, authenticated using (true);
create policy read_scrape_runs on scrape_runs for select to anon, authenticated using (true);

grant usage on schema public to anon, authenticated;
grant select on companies, jobs, job_sources, scrape_runs, jobs_feed to anon, authenticated;
