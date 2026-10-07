# Design System

Visual reference for the internship job board UI. Based on the Refero style
[03e0e30c](https://styles.refero.design/style/03e0e30c-4c0f-4879-948a-9b501e530207)
(Grafana Labs marketing site). We borrow the visual language only — no Grafana
names, logos, or assets.

Tokens live in [`tokens.css`](./tokens.css).

## Color

### Brand
| Token | Hex | Use |
|---|---|---|
| `--signal` (Electric Signal) | `#1b55f5` | Filled CTA buttons, text links, arrows, active marks |

### Accents
| Token | Value | Use |
|---|---|---|
| `--apricot` (Apricot Fill) | `#fad8ac` | Warm feature-card surface |
| `--orchid-edge` | `#eeaafd` | Pastel purple card borders |
| `--sky-edge` | `#8ec0ff` | Pastel blue card borders |
| `--tangerine-edge` | `#ffae70` | Pastel orange card borders |
| `--horizon` (Horizon Wash) | `linear-gradient(120deg, #f7bfa3 10%, #e6b3e6 40%, #a3d8f7 75%, #7be7e7)` | Hero gradient |

### Neutrals
| Token | Hex | Use |
|---|---|---|
| `--ink` | `#000000` | Headlines, prominent body copy |
| `--charcoal` | `#2b2d32` | Dark preview panels |
| `--graphite` | `#454554` | Secondary body copy |
| `--slate` | `#67677e` | Nav labels, muted metadata |
| `--input-steel` | `#d8d8df` | Input borders |
| `--divider` | `#e6e6ea` | 1px structural dividers |
| `--peach-paper` | `#f4e5d9` | Warm card surfaces |
| `--lilac-wash` | `#f9e8ff` | Pale purple card surfaces |
| `--blue-mist` | `#eaf0ff` | Pale blue card fields |
| `--canvas` (Cloud Canvas) | `#f4f4f6` | Page background, footer bands |
| `--surface` | `#ffffff` | Header, inputs, elevated content |

## Typography

- **Display — Poppins** 500/600. Headings and section titles only.
- **Body — Inter** 400/500/600/700. Body, nav, links, inputs, buttons, table cells.

| Role | Font | Size | Weight | Line height | Tracking |
|---|---|---|---|---|---|
| display-hero | Poppins | 60px | 600 | 1.25 | -1.5px |
| display-section | Poppins | 48px | 600 | 1.13 | -1.2px |
| heading-centered | Poppins | 36px | 600 | 1.25 | 0 |
| heading | Poppins | 30px | 600 | 1.25 | -0.75px |
| heading-small | Poppins | 24px | 600 | 1.25 | -0.6px |
| body | Inter | 16px | 400 | 1.5 | 0 |
| ui | Inter | 16px | 500 | 1.5 | -0.4px |
| button | Inter | 14px | 500 | 20px | 0 |
| nav | Inter | 13px | 500 | 1.5 | -0.13px |

## Spacing & Shape

- Base unit **4px**. Scale: 4, 8, 12, 16, 20, 24, 32, 44, 48, 64, 80, 96, 240.
- Element gap 12px · card padding 12px · section gap 64px.
- Max content width **1280px**.

| Element | Radius |
|---|---|
| Cards | 24px |
| Images | 12px |
| Buttons, links, inputs | 8px |
| Navigation items | 4px |

### Shadows
- `--shadow-subtle`: `oklab(0 0 0 / 0.05) 0 0 0 1px, rgba(0,0,0,0.1) 0 1px 3px 0`
- `--shadow-subtle-2`: `rgba(0,0,0,0.1) 0 1px 3px 0`
- `--shadow-subtle-3`: `rgba(0,0,0,0.05) 0 1px 2px 0`

## Components

- **Primary button** — `--signal` fill, white Inter 14px/20px 500, 8px radius, padding `7px 14px 9px`.
- **Outline button** — transparent, `--ink` text, 1px `--divider` border, 0 radius, padding `8px 32px`.
- **Search field** — `--surface`, 1px `--input-steel` border, 8px radius, padding `13px 44px`, `--signal` submit icon.
- **Pastel card** — 24px radius, no shadow; `--lilac-wash` + `--orchid-edge` or `--blue-mist` + `--sky-edge` frame.
- **Nav bar** — `--surface`, Inter 13px/19.5px 500 `--slate` labels, 1px `--divider` bottom border.

## Do / Don't (from source)

**Do**
- Cloud Canvas as the dominant page field; White Surface for headers.
- Poppins 600 for display headings.
- Reserve Electric Signal for filled buttons, links, arrows, active accents.
- 24px-radius pastel cards with no shadow.
- 4px spacing base, 12px element gaps, 64px section gaps.

**Don't**
- Heavy drop shadows on cards.
- Replace 24px card corners with 8px.
- Use Electric Signal as a large background.
- Set large headings in Inter.

## Adaptations for the Job Table

The source style discourages dense dashboard grids; a job board needs one. Rules
for keeping the table on-brand:

- Table sits inside a single `--surface` card (24px radius, `--shadow-subtle`),
  on the `--canvas` page. The 64px section gap applies around the card, not
  between rows.
- Rows: Inter 14px, 12px vertical padding, 1px `--divider` between rows. Header
  row Inter 13px 500 `--slate`.
- Company / title in `--ink` 500; metadata (location, posted) in `--graphite`.
- Title is the link — `--signal` on hover only, to avoid a wall of blue.
- **Region tabs** (Canada / US) use nav-item styling: 4px radius, active tab
  gets `--signal` underline.
- **Flag badges** — pill (999px radius), Inter 12px 500, pastel fill + edge:
  | Flag | Fill | Border | Text |
  |---|---|---|---|
  | Sponsors visa | `--blue-mist` | `--sky-edge` | `--ink` |
  | No sponsorship / citizens only | `--peach-paper` | `--tangerine-edge` | `--ink` |
  | Repost | `--lilac-wash` | `--orchid-edge` | `--ink` |
  | New (< 24h) | `--signal` | `--signal` | `#fff` |
  | Pay listed | `--apricot` | `--tangerine-edge` | `--ink` |
- Hero: `--horizon` gradient band with Poppins 60px headline and the search
  field; the table follows below.
- Light theme only in the source. If dark mode is added later, base it on
  `--charcoal` panels with the same pastel badges at reduced opacity.
