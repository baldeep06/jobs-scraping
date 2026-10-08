-- Companies with their own career sites (no standard job-board system).
alter table companies drop constraint companies_ats_check;
alter table companies add constraint companies_ats_check
  check (ats in ('greenhouse','lever','ashby','workday','smartrecruiters','workable',
                 'amazon','microsoft','apple','google','meta'));

-- Postings we opened and rejected (not an internship / not US-CA), so sites that need one
-- request per posting (Meta) are not re-read on every poll. Private: no anon/authenticated access.
create table checked_postings (
  source text not null,
  source_job_id text not null,
  checked_at timestamptz not null default now(),
  primary key (source, source_job_id)
);
alter table checked_postings enable row level security;
revoke all on checked_postings from anon, authenticated;
