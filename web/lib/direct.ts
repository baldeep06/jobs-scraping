/** Companies we can't scrape (their sites block bots or have no readable job board), so the
 * site links to their career pages instead. Citadel and Two Sigma are partly covered
 * through the Simplify list, but only for postings Simplify has picked up. */
export const DIRECT_COMPANIES: { name: string; url: string }[] = [
  { name: "Citadel", url: "https://www.citadel.com/careers/open-opportunities/" },
  { name: "Citadel Securities", url: "https://www.citadelsecurities.com/careers/open-opportunities/" },
  { name: "Two Sigma", url: "https://www.twosigma.com/careers/" },
  { name: "Millennium", url: "https://www.mlp.com/careers/" },
  { name: "D. E. Shaw", url: "https://www.deshaw.com/careers" },
  { name: "Balyasny", url: "https://www.bamfunds.com/careers" },
  { name: "Bridgewater", url: "https://www.bridgewater.com/careers" },
  { name: "PEAK6", url: "https://www.peak6.com/careers" },
  { name: "Trexquant", url: "https://www.trexquant.com/careers" },
  { name: "Wolverine Trading", url: "https://www.wolve.com/" },
];
