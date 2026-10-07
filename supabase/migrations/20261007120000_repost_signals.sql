-- Repost detection: a freshness value for postings that were already open when we first
-- saw them, plus two fuzzy-match signals (title token set, description hash).
alter table jobs drop constraint jobs_freshness_check;
alter table jobs add constraint jobs_freshness_check
  check (freshness in ('fresh','repost','reopened','refreshed','recurring','existing'));

alter table jobs add column title_key text;
alter table jobs add column desc_hash text;
create index jobs_company_title_key_idx on jobs (company_id, title_key) where title_key is not null;
create index jobs_company_desc_hash_idx on jobs (company_id, desc_hash) where desc_hash is not null;

-- Backfill: jobs posted well before we first saw them were never "fresh".
update jobs set freshness = 'existing'
 where freshness = 'fresh' and source_posted_at < first_seen_at - interval '3 days';
