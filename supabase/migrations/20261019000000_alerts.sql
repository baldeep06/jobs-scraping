-- When a priority alert email covered this job (null = not alerted).
alter table jobs add column alerted_at timestamptz;
create index jobs_unalerted_idx on jobs (first_seen_at) where alerted_at is null;
