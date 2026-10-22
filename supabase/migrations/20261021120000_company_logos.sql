-- Whether a company's website shows a logo (Google's favicon service has one for it): null until
-- checked. The feed hands the site no domain for a site without one, so it shows the letter tile
-- instead of Google's generic globe (which browsers display like any other image).
alter table companies add column has_logo boolean;

-- j.* grew since the view was made, so it can't be replaced in place.
drop view jobs_feed;
create view jobs_feed with (security_invoker = true) as
select j.*, c.name as company_name,
       case when c.has_logo is false then null else c.domain end as company_domain,
       c.h1b_count, c.h1b_fiscal_year, c.groups as company_groups
from jobs j
join companies c on c.id = j.company_id
where j.status = 'open';

grant select on jobs_feed to anon, authenticated;
