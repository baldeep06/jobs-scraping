/** Companies we can't scrape (their sites block bots or have no readable job board), so the
 * site links to their career pages instead. Citadel is partly covered through the Simplify
 * list, but only for postings Simplify has picked up. */
export const DIRECT_COMPANIES: { name: string; url: string }[] = [
  { name: "Citadel", url: "https://www.citadel.com/careers/open-opportunities/" },
  { name: "Citadel Securities", url: "https://www.citadelsecurities.com/careers/open-opportunities/" },
  { name: "Millennium", url: "https://www.mlp.com/careers/" },
  { name: "Balyasny", url: "https://www.bamfunds.com/careers" },
];
