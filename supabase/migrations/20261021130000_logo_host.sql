-- The host Google's favicon service has a logo for: often the www. host when the bare domain
-- has none (bny.com has no icon there, www.bny.com does). The feed hands the site this host.
alter table companies add column logo_host text;

drop view jobs_feed;
create view jobs_feed with (security_invoker = true) as
select j.*, c.name as company_name,
       case when c.has_logo is false then null else coalesce(c.logo_host, c.domain) end
         as company_domain,
       c.h1b_count, c.h1b_fiscal_year, c.groups as company_groups
from jobs j
join companies c on c.id = j.company_id
where j.status = 'open';

grant select on jobs_feed to anon, authenticated;
