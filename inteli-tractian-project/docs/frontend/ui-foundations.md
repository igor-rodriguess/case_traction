# UI foundations — AI Investigation Platform

## Stack

The frontend lives in `frontend/` and uses React 19, TypeScript, Vinext/Vite, Tailwind CSS 4 and the accessible Base UI primitives distributed by the project scaffold. The stack was chosen for typed contracts, reusable B2B components, fast local feedback and a future API integration boundary without coupling the Python backend to the view layer.

The interface currently uses `Table`, `Tabs`, `Sheet`, `Empty` and `Skeleton` primitives. Product layout and visual hierarchy are implemented in application CSS so the result does not inherit a component-library demo appearance.

## Skills used

- `sites:sites-building`: used for the project lifecycle, working-surface composition, component reuse, responsive behavior and validation gates.
- `computer-use:computer-use`: selected for browser review. The environment exposed no controllable browser surface during this run, so visual screenshots could not be captured without substituting an unapproved browser mechanism.

Other available skills were reviewed by relevance. Image generation was deliberately not used: this is a technical, data-dense product surface and decorative imagery would weaken the operational hierarchy.

## Official TRACTIAN references

- [Brand Book 2026](https://brand.tractian.com/)
- [Colors](https://brand.tractian.com/color)
- [Typography](https://brand.tractian.com/typography)
- [Logo rules](https://brand.tractian.com/logo)
- [Iconography](https://brand.tractian.com/iconography)
- [TRACTIAN website](https://tractian.com/)

The implementation follows the current official Slate and Blue families, uses complementary colors only for semantic state, and uses Inter Tight for headings plus Inter for body copy. It avoids gradients, glass effects, glow, mascots, chat UI and generic AI motifs.

The production icon source defined by the Brand Book is Atlas Icons. This pilot intentionally avoids introducing a competing icon library in product views. Compact textual/geometric markers provide status redundancy until the licensed official icon package or exported assets are made available. The header is a typographic product identifier, not a claim that a recreated asset is an official downloadable logo.

## Tokens

Primary tokens are centralized in `frontend/app/globals.css`:

- Blue 600 `#2563EB`, Blue 700 `#1D4ED8`, Blue 800 `#1E40AF`;
- Slate 50–950 for surfaces, dividers and text;
- green for complete/operational;
- amber/orange for partial, inconclusive and review;
- red for conflict/failure;
- compact radii from 2–8 px;
- 1 px dividers and restrained surface elevation;
- body text 14 px by default, 16 px or greater for narrative/report content and headings.

## Typography and density

Inter Tight creates a technical hierarchy for page titles, section headings and numeric indicators. Inter is used for controls, tables and body content. Monospace is reserved for stable identifiers, calls and paths. The desktop layout prioritizes tables, rows, timelines and split surfaces rather than one card per fact.

## State system

Terminal states always use text plus a distinct marker shape and color:

- `GROUNDED_COMPLETION` — circular checked marker;
- `SAFE_ESCALATION` — rotated review marker;
- `AWAITING_REQUIRED_INFORMATION` — dashed marker;
- `FAILED` — failure marker.

Evidence statuses use a label, icon character, border and color. Transport status is rendered separately from semantic evidence status. Evidence quality is qualitative (`HIGH`, `MEDIUM`, `LOW`, `INSUFFICIENT EVIDENCE`) with a deterministic signal breakdown; no confidence percentage is invented.

## Accessibility and motion

The application uses semantic headings, navigation, tables, ordered lists and buttons; labelled dialogs/sheets; keyboard-openable rows; visible focus rings; accessible status labels; and reduced-motion support. Color is never the sole status signal. Horizontal table overflow is intentional below the desktop priority range.
