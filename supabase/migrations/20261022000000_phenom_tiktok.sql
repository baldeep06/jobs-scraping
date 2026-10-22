-- Phenom career sites (BCG, Trane, MITRE, Battelle, Bell, ...) and TikTok's careers API.
alter table companies drop constraint companies_ats_check;
alter table companies add constraint companies_ats_check
  check (ats in ('greenhouse','lever','ashby','workday','smartrecruiters','workable',
                 'amazon','microsoft','apple','google','meta',
                 'eightfold','eightfold_v2','oraclehcm','icims','lever_eu','jibe','talentbrew',
                 'jobvite','gem','rippling','simplify','internlist',
                 'avature','successfactors','pinpoint','deshaw','shopify','phenom','tiktok'));
