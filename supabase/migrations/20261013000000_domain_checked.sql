-- When we last asked for a company's website (for its logo), so "unknown" is not asked again.
alter table companies add column domain_checked_at timestamptz;
