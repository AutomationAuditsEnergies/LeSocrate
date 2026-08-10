---
name: Le Socrate · HR Dashboard
description: Operator-side visual system for the admin surface (HR Dashboard, formation pipeline, schedule config). Apprenant-side surfaces are out of scope and use a different system.
colors:
  primary: "#18181b"
  primary-deep: "#27272a"
  primary-soft: "#52525b"
  primary-mist: "#a1a1aa"
  bg-canvas-dark: "#09090b"
  bg-canvas-light: "#fafafa"
  bg-surface-dark: "#18181b"
  bg-surface-light: "#ffffff"
  bg-recessed-dark: "#09090b"
  bg-recessed-light: "#f4f4f5"
  text-primary-dark: "#fafafa"
  text-primary-light: "#18181b"
  text-secondary-dark: "#d4d4d8"
  text-secondary-light: "#3f3f46"
  text-muted: "#71717a"
  border-dark: "#3f3f46"
  border-light: "#e4e4e7"
  divider-light: "#d4d4d8"
  status-locked: "#10b981"
  status-error: "#dc2626"
  status-error-soft: "#fee2e2"
  status-warning: "#f59e0b"
typography:
  display:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: "2rem"
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: "1.5rem"
    letterSpacing: "-0.005em"
  body:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.4rem"
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: "1rem"
    letterSpacing: "normal"
  eyebrow:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.625rem"
    fontWeight: 600
    lineHeight: "1rem"
    letterSpacing: "0.2em"
rounded:
  sm: "8px"
  md: "10px"
  lg: "12px"
  modal: "14px"
  pill: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
    textColor: "#ffffff"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary-dark}"
    rounded: "{rounded.sm}"
    padding: "8px 14px"
  button-icon:
    backgroundColor: "transparent"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.sm}"
    size: "36px"
  card-platform:
    backgroundColor: "{colors.bg-surface-dark}"
    rounded: "{rounded.lg}"
    padding: "24px"
  status-pill-locked:
    backgroundColor: "{colors.status-locked}"
    textColor: "{colors.status-locked}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  audio-item:
    backgroundColor: "{colors.bg-recessed-dark}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
---

# Design System: Le Socrate · HR Dashboard

> **Scope.** This document describes the visual system for the **operator-side surface only** (`/dashboard-centre`, `/formation-pipeline`, `/schedule-config`, `/debug`). The apprenant-side surfaces (`/`, `/attente`, `/video`) follow a different system rooted in Poppins/Fredoka and Spline-driven aesthetics — out of scope here. If a future task asks for a learner-facing screen, do **not** apply this DESIGN.md to it.

## 1. Overview

**Creative North Star: "The Examiner's Desk"**

The HR Dashboard is the desk of the RNCP examiner. Quiet authority, certifying paperwork, the dignity of a public-service tool that has to be right because it stamps people's careers. The interface should feel like the well-designed admin office of an institution that takes itself seriously, not like a SaaS product trying to charm the user into a free trial. References at the top of the lane: **gov.uk** and **France Identité** (civic minimalism done well), **Linear** and **Stripe Dashboard** (operator-first product calm), **Coursera** and **edX** (institutional edtech credibility). The pairing — civic register + product calm — is the whole spine.

Every element on this surface answers the question "would a national exam board approve of this rendering ?" before it answers "would a designer admire this on Dribbble ?". The dashboard is for an operator who runs the place, not a visitor who needs to be excited. Operator-first explicitly: if a UX choice serves the apprenant by inconveniencing the admin, the admin wins (per `PRODUCT.md` Principle 2).

This system **rejects**, by direct mandate of `PRODUCT.md` anti-references:

- **Edtech "playful" patterns.** No mascots, no streaks, no XP, no celebration confetti, no warm primary saturation, no "Bravo ! 🎉".
- **AI-slop logo marks.** No colored rounded square containing an abstract icon as a logo. The wordmark and the restrained graphite `S` are the identity.
- **Hero-metric SaaS template.** No big-number/small-label/supporting-stat tiles with gradient accents.
- **Identical card grids.** Cards may share a kind only when their content visibly varies; reflex 3-up icon+title+text grids are slop tells.
- **Gradient text** and **default glassmorphism** (used decoratively).

**Key Characteristics:**

- Dark and light parity are both first-class. Neither is "default."
- Graphite ink is the primary action color; the interface does not use a decorative brand accent.
- Flat surfaces, tonal layering, near-zero shadow.
- Inter as the only typeface (operator side). The apprenant side's Poppins does not cross over.
- Slide-to-confirm as the signature interaction for irreversible actions (lock/unlock).
- Every modal uses the same neutral shell: black backdrop, white or graphite surface, divided header, no colored icon tile.

## 2. Colors

Graphite ink sits in a true neutral stack that mirrors itself in dark and light. It is not a decorative accent: contrast, spacing and typography carry hierarchy. Status colors (green, red, amber) appear sparingly, only when state semantics demand them.

### Primary

- **Graphite Ink** (`#18181B`) — primary CTA, active navigation and strong focus treatment on light surfaces. It carries authority through contrast, never through saturation.
- **Graphite Hover** (`#27272A`) — hover state of a black primary CTA.
- **Graphite Soft** (`#52525B`) — secondary emphasis and dark-mode borders.
- **Graphite Mist** (`#A1A1AA`) — disabled labels and quiet iconography. Never substitute it for a disabled-state opacity treatment when contrast would suffer.
- **Graphite Tint** (`rgba(24, 24, 27, 0.06)`) — active navigation rows and selected neutral controls on light surfaces.

### Neutral

The neutral stack is zinc/graphite: nearly achromatic, cool and restrained. Use named tokens rather than improvised grays.

- **Canvas Dark** (`#09090B`) — outer page background in dark mode.
- **Canvas Light** (`#FAFAFA`) — outer page background in light mode.
- **Surface Dark** (`#18181B`) — elevated surfaces in dark mode (cards, navigation, modal containers).
- **Surface Light** (`#ffffff`) — elevated surfaces in light mode (cards, modals).
- **Recessed Dark** (`#09090B`, identical to canvas) — inset surfaces in dark mode. Depth comes from a border, not a decorative glow.
- **Recessed Light** (`#F4F4F5`) — selected rows, quiet wells and disabled surfaces in light mode.
- **Text Primary** (`#FAFAFA` dark / `#18181B` light) — h1, card titles, primary body.
- **Text Secondary** (`#D4D4D8` dark / `#3F3F46` light) — secondary copy, button labels.
- **Text Muted** (`#71717A`) — eyebrows, hints, timestamps and secondary chrome.
- **Border** (`#3F3F46` dark / `#E4E4E7` light) — default 1px border on cards, buttons and inputs.
- **Divider Light** (`#D4D4D8`) — section dividers in light mode when the default border is too quiet.

### Status (Tertiary)

State colors. Use only when semantics require, never decoratively.

- **Locked Green** (`#10b981`) on `rgba(16, 185, 129, 0.12)` tint — reserved for a confirmed successful lock or completion state, never for decoration.
- **Error Red** (`#dc2626`) on `#fee2e2` tint — destructive confirmation modals, error overlay icon background.
- **Warning Amber** (`#f59e0b`) on `rgba(245, 158, 11, 0.15)` tint — pipeline "Brouillon", non-blocking caution.

### Named Rules

**The One Voice Rule.** Graphite Ink is the single non-semantic action color. Use it for primary CTAs, active navigation and focus. Never add a decorative accent “to brighten things up”; hierarchy comes from weight, spacing and contrast.

**The No-Decorative-Color Rule.** Blue, violet and other saturated hues have no brand role on the operator surface. Existing colored chrome is migration debt. Use semantic colors only for an actual status, warning, success or destructive action.

**The Graphite-Spine Rule.** Reuse the zinc/graphite spine (`#09090B`, `#18181B`, `#3F3F46`, `#71717A`, `#A1A1AA`, `#D4D4D8`, `#E4E4E7`, `#F4F4F5`, `#FAFAFA`). Prefer named tokens over mixed `gray-*`, `slate-*` and arbitrary hex values.

## 3. Typography

**Display / Body / Label / Eyebrow:** Inter (`Inter, system-ui, -apple-system, sans-serif`).

The HR Dashboard uses **Inter exclusively**, set inline at the page root. This is a deliberate divergence from `index.css`'s `Poppins` global — Poppins serves the apprenant side (warmer, friendlier). The admin side is the examiner's desk and wants Inter's neutral institutional voice. The two systems do not cross.

Lucide is the preferred icon set for new or revised operator UI because its consistent stroke language fits the graphite system. Existing Material Icons may remain until their host component is touched; do not mix both families inside one control group.

### Hierarchy

- **Display** (Inter 700, 1.5 rem / 24 px, line-height 2 rem, letter-spacing −0.01 em): page-level h1 ("Dashboard Formations", and any future page title in the admin section).
- **Title** (Inter 600, 1.125 rem / 18 px, line-height 1.5 rem, letter-spacing −0.005 em): card and modal section titles ("Modules formation", platform names, "Nouvelle plateforme").
- **Body** (Inter 400, 0.875 rem / 14 px, line-height 1.4 rem): primary body, button labels, paragraph copy. Default density. Cap line length at 65–75 ch in any prose block (rare on this surface, but applies to descriptions in modals).
- **Label** (Inter 500, 0.75 rem / 12 px): secondary labels, hints, helper text, timestamps, footer copy.
- **Eyebrow** (Inter 600, 0.625 rem / 10 px, uppercase, letter-spacing 0.2 em): brand eyebrow ("LE SOCRATE · HR"), status pill text ("VERROUILLÉ", "OUVERT", "BIENTÔT DISPONIBLE"). Always uppercase, always tracked.

### Named Rules

**The Inter-Only Rule.** No other typeface inside the admin surface. No serif accents, no monospace exceptions, no Google-Fonts-of-the-week. Inter handles display, title, body, label and eyebrow.

**The Tracked-Eyebrow Rule.** Whenever a label sits *above* a heading or *inside* a status indicator, it is rendered as eyebrow (10 px, uppercase, letter-spacing 0.2 em). This signals "this is a marker, not content." Never use mixed-case body for an eyebrow role.

## 4. Elevation

**Flat by default with tonal layering.** Dark mode has no shadows on cards, headers or buttons — depth is conveyed by tonal contrast (`#09090B` canvas under `#18181B` surface, with `#3F3F46` border). Light mode may use a faint `shadow-sm` on a genuinely raised card. Navigation and inline panels stay opaque and divided; blur is reserved for no routine operator surface.

The slide-to-confirm thumb has a more present shadow during drag (`0 4px 12px rgba(0,0,0,0.2)`) — that is the **only place** a real lift exists, and only as a response to the user actively grabbing the affordance. State, not ornament.

### Shadow Vocabulary

- **Card lift (light only)** (`box-shadow: 0 1px 3px 0 rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1)`): platform cards at rest in light mode. Removed entirely in dark mode.
- **Drag lift (interaction)** (`box-shadow: 0 4px 12px rgba(0,0,0,0.2)`): slide-to-confirm thumb while being grabbed. Disappears on release.
- **Modal cast** (`box-shadow: 0 24px 60px rgba(0,0,0,0.24)`): modal container only, against a solid black backdrop. No blur is needed.

### Named Rules

**The Flat-by-Default Rule.** Dark surfaces never carry shadow at rest. Light surfaces carry only the faintest hint, and only on cards. If you find yourself adding a `shadow-md` or larger to make something "pop," you're working against the system — fix the tonal contrast or the border instead.

**The Lift-on-Grab-Only Rule.** A meaningful drop shadow appears only when the user is actively interacting (drag, focus). It is feedback, not decoration. Hover states use background tint (`hover:bg-black/5 dark:hover:bg-white/5`), not shadow shifts.

## 5. Components

For each component, lead with character, then specify shape, color assignment, states, and any distinctive behavior. Components are no-ceremony tools — efficient, sometimes dense, focused on operator productivity (Linear / Raycast register, not Material Design opulence).

### Buttons

- **Shape:** gentle 8 px radius (`rounded-lg`). No pill shapes for primary buttons. No square corners.
- **Primary** (`button-primary`): solid Graphite Ink, white text, 8 px / 16 px padding, Inter 500 14 px. Used **once or twice per screen maximum** for the most consequential action ("Nouvelle plateforme", "Créer la plateforme"). Hover changes only the fill to `#27272A`; no scale, translation or shadow shift.
- **Secondary / Outlined**: transparent background, 1 px neutral border, secondary-text foreground, same padding. Used for navigation buttons in chrome ("Modules", "Retour Admin") and inline actions.
- **Icon-only**: 36 px × 36 px square (`rounded-lg`), 1 px border, transparent fill. Used for dark/light toggle, pagination chevrons. Hover background `black/5` (light) or `white/5` (dark).
- **Destructive (red)**: `#dc2626` solid background, white text, used in the delete-confirmation modal. Never used on the dashboard surface itself — destructive intent is always behind a modal confirmation.

### Status Pills (eyebrow-style)

- **Shape:** `rounded-full` (pill).
- **Locked / Success**: `rgba(16, 185, 129, 0.12)` background, `#10b981` text, eyebrow type, lock icon prefix. Renders "VERROUILLÉ" in the platform card header.
- **Open / Neutral**: transparent background, 1 px neutral border, muted text, lock-open icon prefix. Renders "OUVERT".
- **Caution / Warning**: `rgba(245, 158, 11, 0.15)` background, `#f59e0b` text, eyebrow type. Renders "BROUILLON" on draft modules.
- **Error**: a circle icon container (`#fee2e2` bg with `#dc2626` icon) used in the platform card error overlay. Not a pill in the same family.

### Cards / Containers

- **Corner Style:** 12 px for principal data cards, 8 px for secondary containers, buttons and inputs. A 14 px radius is reserved for modal shells. Avoid nesting several rounded containers when dividers express the same structure more clearly.
- **Background:** `#18181B` in dark, `#FFFFFF` in light. Platform cards carry a 1 px neutral border; active state is communicated by content, a status label or a stronger neutral border, never a decorative color.
- **Shadow Strategy:** see Elevation. Flat in dark, faint shadow in light. Never elevated in hover.
- **Border:** always 1 px, neutral (`#3F3F46` dark / `#E4E4E7` light).
- **Internal Padding:** 24 px (`p-6`).
- **Inactive overlay:** opaque tonal cover (`rgba(9, 9, 11, 0.92)` dark / `rgba(250, 250, 250, 0.96)` light), centered "BIENTÔT DISPONIBLE" label. Do not blur the content underneath.

### Inputs / Fields

- **Style:** `rounded-lg` (8 px), 1 px neutral border, recessed background (`#09090B` dark / `#FAFAFA` light). 12 px / 16 px padding for full-size, 8 px / 12 px for compact.
- **Focus:** 2 px graphite focus ring with sufficient offset and contrast. Never use `focus:outline-none` without a visible alternative.
- **Disabled / Loading:** opacity 0.55, cursor not-allowed, background falls back to a flatter neutral.

### Navigation / Chrome

- **Sticky top nav:** opaque `#18181B` (dark) / `#FFFFFF` (light), with a 1 px bottom border. Vertical padding `py-4`. Wraps a flex row at `max-w-7xl px-6`.
- **Title block:** restrained graphite `S` mark plus product label where brand context is useful; page title remains the dominant element. Never place the mark in a colored tile.
- **Right cluster:** dark/light icon-only toggle, "Modules" outlined button, "Nouvelle plateforme" primary button, "Retour Admin" outlined button. The primary CTA is the only filled button.

### Slide-to-Confirm (Signature)

The signature interaction. Used for irreversible state changes (lock platform / unlock + backup).

- **Track:** `rounded-full` 44 px tall, neutral background (`rgba(63, 63, 70, 0.55)` dark / `#E4E4E7` light), with a 1 px neutral border.
- **Thumb:** 36 px × 36 px white circle with subtle shadow (`0 2px 6px rgba(0,0,0,0.12)` at rest, `0 4px 12px rgba(0,0,0,0.2)` when grabbed), `cursor: grab` / `grabbing`. Lock / lock-open / check icon inside.
- **Fill:** the area swept by the thumb fills with graphite; green appears only after completion when it communicates a real successful state.
- **Feedback:** label inside the track ("Glisser pour verrouiller / déverrouiller →") fades out as progress climbs, replaced by "✓ Confirmé" at completion.
- **Easing:** `cubic-bezier(0.34, 1.56, 0.64, 1)` — the *one* exception to "no bounce" allowed in the system. The slight overshoot signals lock-in. 350 ms duration. Do not propagate this curve to other components.

### Audio Item

- **Shape:** `rounded-lg`, recessed background (`#09090B` dark / `#F4F4F5` light), 8 px / 12 px padding.
- **Play button:** 28 px × 28 px graphite circle with white play / pause icon.
- **Filename:** truncated body text, `title` attribute carries the full string for tooltip on overflow.
- **Size:** muted 10 px label, right-aligned.
- **Delete icon:** muted at rest, fades to rose (`#f87171`) on hover with a soft rose tint background. Single-step destructive — there is **no** confirmation modal at the audio-item level (decision: micro-action, undo via re-upload).

### Modal

- **Shape:** 14 px radius, `#18181B` (dark) / `#FFFFFF` (light) background, with `box-shadow: 0 24px 60px rgba(0,0,0,0.24)` on the shell only.
- **Header bar:** 20 px / 24 px padding, 1 px bottom divider, concise title and helper text on the left, 36 px icon-only close control on the right. Icons stay unboxed or use a quiet neutral 8 px container when identification genuinely benefits.
- **Body:** scrollable, `max-height: calc(85vh − header)`, 24 px padding.
- **Backdrop:** `rgba(9, 9, 11, 0.55)`, without blur. Click-outside dismisses unless an irreversible operation is in progress.
- **Consistency:** nested tabs and tools reuse this shell and its header rhythm. No bespoke colored bandeau, oversized title or full-screen rounded card for each tool.

### Pagination

- **Shape:** "Page X / Y" muted body text + two icon-only chevron buttons. Right-aligned above the cards grid.
- **Buttons:** 40 px × 40 px, 8 px radius, 1 px neutral border, transparent fill, secondary-text icon. Hover `bg-black/5` / `bg-white/5`. Disabled at 30 % opacity. No filled circles, no numbered page list.
- **Threshold:** pagination renders only when `platforms.length > CARDS_PER_PAGE` (currently 3).

## 6. Do's and Don'ts

Concrete guardrails. Quote PRODUCT.md anti-references by name so the visual spec carries the strategic line through.

### Do:

- **Do** use Graphite Ink (`#18181B`) for the single most consequential action on each light screen. Once or twice per surface; hierarchy comes from rarity.
- **Do** keep neutrals on the graphite spine (`#09090B` / `#18181B` / `#3F3F46` / `#71717A` / `#A1A1AA` / `#D4D4D8` / `#F4F4F5` / `#FAFAFA`).
- **Do** treat dark and light as equally first-class. If you only design one of the two and shrug at the other, you're shipping a half-system.
- **Do** prefer tonal layering over shadows. Border + tonal shift conveys depth in dark mode; faint shadow on cards only in light mode.
- **Do** track all eyebrow labels (10 px, uppercase, letter-spacing 0.2 em). The eyebrow is the institutional voice of the system — give it room.
- **Do** confirm irreversible actions through the slide-to-confirm pattern, not a modal "Are you sure ?" dialog. The drag is the contract.
- **Do** use Lucide for new operator controls; keep legacy Material Icons contained until their host group is migrated.
- **Do** write microcopy as if it were going on a printed certificate: posée, claire, factuelle. No "Boost your career !", no "Tu peux le faire !", no exclamations except literal validation ("✓ Confirmé").
- **Do** use the shared neutral modal shell for every nested tool and settings view.

### Don't:

- **Don't** ship a colored rounded square with an abstract icon as a logo mark. This is the canonical AI-slop signature; use the graphite `S` mark or a wordmark.
- **Don't** introduce edtech "playful" patterns: gamification, mascots, streaks, XP, level-up animations, celebration confetti, "Bravo ! 🎉", saturated yellow / orange / red primaries. Quote `PRODUCT.md` Anti-references by name.
- **Don't** use the hero-metric SaaS template (big number / small label / supporting stats / gradient accent). It is the cliché.
- **Don't** ship identical card grids — three or four equally-weighted cards with icon + title + paragraph in a 3-up row is the AI mockup tell. If two cards on screen have the same shape, their content must visibly distinguish them.
- **Don't** apply `background-clip: text` with a gradient to any heading, anywhere. Solid color, weight contrast, scale contrast — those carry hierarchy without ornament.
- **Don't** use glassmorphism (`backdrop-filter: blur(...)` over translucent surfaces) decoratively. Operator navigation, cards and modal backdrops stay opaque.
- **Don't** mix `gray-*`, `slate-*`, `zinc-*`, `stone-*` and arbitrary hex values in one surface. Prefer the named graphite tokens.
- **Don't** introduce blue, violet or another brand accent on the operator surface. Saturated colors are reserved for semantic state.
- **Don't** add `hover:-translate-y-0.5` (or any layout-property animation) on hover. The system uses `transition-colors` and `transition-transform` (scale only) — moving an element on hover causes layout reflow and looks SaaS-default.
- **Don't** silence focus rings without an alternative. Keyboard users exist; the `focus-visible` outline is the contract.
- **Don't** scatter colored icon boxes, tinted panels or glowing illustrations across the screen. Tone decorative assets to graphite and let the task content lead.
- **Don't** mix Inter and Poppins on the admin surface. The apprenant side has Poppins; the admin side has Inter. The two systems do not cross. If you find yourself reaching for `font-family: 'Poppins'` inside `/hr-dashboard`, the answer is no.
- **Don't** add a "Layout" or "Motion" or "Responsive" top-level section to this DESIGN.md. The Stitch spec has six sections, not nine. Layout / motion / responsive content folds into Overview (philosophy) or Components (per-component behavior).
