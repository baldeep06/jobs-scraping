-- Company groups (FAANG+, quant, unicorn, ...) for the site's group toggles.
alter table companies add column groups text[] not null default '{}';
create index companies_groups_idx on companies using gin (groups);

-- j.* grew since the view was made, so it can't be replaced in place.
drop view jobs_feed;
create view jobs_feed with (security_invoker = true) as
select j.*, c.name as company_name, c.domain as company_domain,
       c.h1b_count, c.h1b_fiscal_year, c.groups as company_groups
from jobs j
join companies c on c.id = j.company_id
where j.status = 'open';

grant select on jobs_feed to anon, authenticated;
