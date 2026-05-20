---
name: Le Socrate · HR Dashboard
description: Operator-side visual system for the admin surface (HR Dashboard, formation pipeline, schedule config). Apprenant-side surfaces are out of scope and use a different system.
colors:
  primary: "#8B5CF6"
  primary-deep: "#7c3aed"
  primary-soft: "#a78bfa"
  primary-mist: "#c4b5fd"
  bg-canvas-dark: "#0f172a"
  bg-canvas-light: "#f8fafc"
  bg-surface-dark: "#1e293b"
  bg-surface-light: "#ffffff"
  bg-recessed-dark: "#0f172a"
  bg-recessed-light: "#f1f5f9"
  text-primary-dark: "#f1f5f9"
  text-primary-light: "#0f172a"
  text-secondary-dark: "#cbd5e1"
  text-secondary-light: "#334155"
  text-muted: "#64748b"
  border-dark: "#334155"
  border-light: "#e2e8f0"
  divider-light: "#cbd5e1"
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
  md: "12px"
  lg: "16px"
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

> **Scope.** This document describes the visual system for the **operator-side surface only** (`/hr-dashboard`, `/formation-pipeline`, `/schedule-config`, `/admin`, `/debug`). The apprenant-side surfaces (`/`, `/intro`, `/attente`, `/video`, `/recorder`) follow a different system rooted in Poppins/Fredoka and Spline-driven aesthetics — out of scope here. If a future task asks for a learner-facing screen, do **not** apply this DESIGN.md to it.

## 1. Overview

**Creative North Star: "The Examiner's Desk"**

The HR Dashboard is the desk of the RNCP examiner. Quiet authority, certifying paperwork, the dignity of a public-service tool that has to be right because it stamps people's careers. The interface should feel like the well-designed admin office of an institution that takes itself seriously, not like a SaaS product trying to charm the user into a free trial. References at the top of the lane: **gov.uk** and **France Identité** (civic minimalism done well), **Linear** and **Stripe Dashboard** (operator-first product calm), **Coursera** and **edX** (institutional edtech credibility). The pairing — civic register + product calm — is the whole spine.

Every element on this surface answers the question "would a national exam board approve of this rendering ?" before it answers "would a designer admire this on Dribbble ?". The dashboard is for an operator who runs the place, not a visitor who needs to be excited. Operator-first explicitly: if a UX choice serves the apprenant by inconveniencing the admin, the admin wins (per `PRODUCT.md` Principle 2).

This system **rejects**, by direct mandate of `PRODUCT.md` anti-references:

- **Edtech "playful" patterns.** No mascots, no streaks, no XP, no celebration confetti, no warm primary saturation, no "Bravo ! 🎉".
- **AI-slop logo marks.** No violet rounded-xl square containing an abstract Material Icon as a logo. (Real-world incident, April 2026 — refused.)
- **Hero-metric SaaS template.** No big-number/small-label/supporting-stat tiles with gradient accents.
- **Identical card grids.** Cards may share a kind only when their content visibly varies; reflex 3-up icon+title+text grids are slop tells.
- **Gradient text** and **default glassmorphism** (used decoratively).

**Key Characteristics:**

- Dark and light parity are both first-class. Neither is "default."
- Single primary accent (violet) carrying ≤ 10 % of any screen; everything else is slate-tinted neutral.
- Flat surfaces, tonal layering, near-zero shadow.
- Inter as the only typeface (operator side). The apprenant side's Poppins does not cross over.
- Slide-to-confirm as the signature interaction for irreversible actions (lock/unlock).
- Every modal must eventually match the violet shell — the Stitch-blue legacy in `AudiosModal` / `PDFModal` is **debt to be repaid**, not a documented role.

## 2. Colors

A single saturated accent (violet) sits in a slate-tinted neutral stack that mirrors itself in dark and light. Status colors (green, red, amber) appear sparingly, only when state semantics demand them.

### Primary

- **Examiner's Violet** (`#8B5CF6`) — the only saturated color in the system. Used on the primary CTA (`Nouvelle plateforme`), brand accents (the dot before `LE SOCRATE · HR`, the `:focus-visible` ring), the play-button on audio items, the active state of slide-to-confirm. Carries the brand identity by **rarity**, not surface area. Named "Examiner's" because its role is to mark the *single most consequential* action on a screen — the way an examiner's stamp does.
- **Violet Deep** (`#7c3aed`) — hover state of the primary CTA only. Never used at rest.
- **Violet Soft** (`#a78bfa`) — disabled state of the primary CTA, and accent text inside violet-tinted chips when readability requires.
- **Violet Mist** (`#c4b5fd`) — accent text on dark-mode tinted backgrounds (e.g. an active "Audios" tile on a dark card). Never used as a fill.
- **Violet Tint** (`rgba(139, 92, 246, 0.10)` — frontmatter doesn't carry alpha so this lives only in component definitions) — chip backgrounds when an action group is "currently engaged" without using full primary fill.

### Neutral

The neutral stack is slate-tinted (chroma drift toward the violet hue). Never use `#000` or `#fff` directly.

- **Canvas Dark** (`#0f172a`) — outer page background in dark mode.
- **Canvas Light** (`#f8fafc`) — outer page background in light mode.
- **Surface Dark** (`#1e293b`) — elevated surfaces in dark mode (cards, sticky nav with translucency, modal containers).
- **Surface Light** (`#ffffff`) — elevated surfaces in light mode (cards, modals).
- **Recessed Dark** (`#0f172a`, identical to canvas) — inset surfaces in dark mode (input bg, audio item bg, recessed action tiles). The collision with canvas is intentional: depth is conveyed by border, not contrast.
- **Recessed Light** (`#f1f5f9`) — inset surfaces in light mode.
- **Text Primary** (`#f1f5f9` dark / `#0f172a` light) — h1, card titles, primary body.
- **Text Secondary** (`#cbd5e1` dark / `#334155` light) — secondary copy, button labels.
- **Text Muted** (`#64748b`) — same value in both modes; eyebrows, hints, timestamps, `Page X / Y` chrome.
- **Border** (`#334155` dark / `#e2e8f0` light) — default 1px border on cards, buttons, inputs.
- **Divider Light** (`#cbd5e1`) — section dividers in light mode (slightly more present than border, for footer/nav splits).

### Status (Tertiary)

State colors. Use only when semantics require, never decoratively.

- **Locked Green** (`#10b981`) on `rgba(16, 185, 129, 0.12)` tint — the "Verrouillé" pill, success states. Mirrors the slide-to-confirm fill in light mode.
- **Error Red** (`#dc2626`) on `#fee2e2` tint — destructive confirmation modals, error overlay icon background.
- **Warning Amber** (`#f59e0b`) on `rgba(245, 158, 11, 0.15)` tint — pipeline "Brouillon", non-blocking caution.

### Named Rules

**The One Voice Rule.** Examiner's Violet is the *only* saturated color on screen. Use it for the primary CTA, the brand accent dot, the focus ring, and the slide-to-confirm fill at confirmation. Never as filler, decoration, or "to brighten things up." If a screen has more than one violet element competing for attention, one of them is wrong.

**The No-Stitch-Blue Rule.** `#137fec` (the legacy bandeau color in `AudiosModal` and `PDFModal`) is **debt**, not a role. Do not introduce blue elsewhere. When touching those modals, migrate them to violet header chrome or to a quieter neutral header. There is no "info" blue in this system.

**The Slate-Drift Rule.** Every neutral has a faint chroma drift toward the violet hue (slate, not pure gray). Never use Tailwind's `gray-*` family, `zinc-*`, `stone-*`, or hardcoded `#888` / `#aaa`. Slate or nothing.

## 3. Typography

**Display / Body / Label / Eyebrow:** Inter (`Inter, system-ui, -apple-system, sans-serif`).

The HR Dashboard uses **Inter exclusively**, set inline at the page root. This is a deliberate divergence from `index.css`'s `Poppins` global — Poppins serves the apprenant side (warmer, friendlier). The admin side is the examiner's desk and wants Inter's neutral institutional voice. The two systems do not cross.

Material Icons are self-hosted (`/static/fonts/MaterialIcons-Regular.woff2`) and rendered through the local `<Icon name="..." />` helper. Lucide-react is available as a dependency but currently unused on this surface.

### Hierarchy

- **Display** (Inter 700, 1.5 rem / 24 px, line-height 2 rem, letter-spacing −0.01 em): page-level h1 ("Dashboard Formations", and any future page title in the admin section).
- **Title** (Inter 600, 1.125 rem / 18 px, line-height 1.5 rem, letter-spacing −0.005 em): card and modal section titles ("Modules formation", platform names, "Nouvelle plateforme").
- **Body** (Inter 400, 0.875 rem / 14 px, line-height 1.4 rem): primary body, button labels, paragraph copy. Default density. Cap line length at 65–75 ch in any prose block (rare on this surface, but applies to descriptions in modals).
- **Label** (Inter 500, 0.75 rem / 12 px): secondary labels, hints, helper text, timestamps, footer copy.
- **Eyebrow** (Inter 600, 0.625 rem / 10 px, uppercase, letter-spacing 0.2 em): brand eyebrow ("LE SOCRATE · HR"), status pill text ("VERROUILLÉ", "OUVERT", "BIENTÔT DISPONIBLE"). Always uppercase, always tracked.

### Named Rules

**The Inter-Only Rule.** No other typeface inside the admin surface. No serif accents, no monospace exceptions, no Google-Fonts-of-the-week. Inter handles display, title, body, label, eyebrow. Material Icons handles iconography. That's the entire type stack.

**The Tracked-Eyebrow Rule.** Whenever a label sits *above* a heading or *inside* a status indicator, it is rendered as eyebrow (10 px, uppercase, letter-spacing 0.2 em). This signals "this is a marker, not content." Never use mixed-case body for an eyebrow role.

## 4. Elevation

**Flat by default with tonal layering.** Dark mode has no shadows on cards, headers, or buttons — depth is conveyed entirely by tonal contrast (`#0f172a` canvas under `#1e293b` surface, with `#334155` border). Light mode adds the faintest shadow on cards (`box-shadow: 0 1px 3px 0 rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1)`) — barely there, the same shadow Tailwind ships as `shadow-sm`. The sticky top nav uses backdrop-blur (`12px`) for translucency over the page background pattern, which counts as elevation through optical separation, not under-cast shadow.

The slide-to-confirm thumb has a more present shadow during drag (`0 4px 12px rgba(0,0,0,0.2)`) — that is the **only place** a real lift exists, and only as a response to the user actively grabbing the affordance. State, not ornament.

### Shadow Vocabulary

- **Card lift (light only)** (`box-shadow: 0 1px 3px 0 rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1)`): platform cards at rest in light mode. Removed entirely in dark mode.
- **Drag lift (interaction)** (`box-shadow: 0 4px 12px rgba(0,0,0,0.2)`): slide-to-confirm thumb while being grabbed. Disappears on release.
- **Top-nav blur** (`backdrop-filter: blur(8px)` on `#1e293b` / `#ffffff`): translucent sticky header. The blur, not a shadow, separates the nav from the scrolling content.

### Named Rules

**The Flat-by-Default Rule.** Dark surfaces never carry shadow at rest. Light surfaces carry only the faintest hint, and only on cards. If you find yourself adding a `shadow-md` or larger to make something "pop," you're working against the system — fix the tonal contrast or the border instead.

**The Lift-on-Grab-Only Rule.** A meaningful drop shadow appears only when the user is actively interacting (drag, focus). It is feedback, not decoration. Hover states use background tint (`hover:bg-black/5 dark:hover:bg-white/5`), not shadow shifts.

## 5. Components

For each component, lead with character, then specify shape, color assignment, states, and any distinctive behavior. Components are no-ceremony tools — efficient, sometimes dense, focused on operator productivity (Linear / Raycast register, not Material Design opulence).

### Buttons

- **Shape:** gentle 8 px radius (`rounded-lg`). No pill shapes for primary buttons. No square corners.
- **Primary** (`button-primary`): solid Examiner's Violet, white text, 8 px / 16 px padding, Inter 500 14 px. Used **once or twice per screen maximum** for the most consequential action ("Nouvelle plateforme", "Créer la plateforme"). Hover scale `1.02` on transform, depress `0.98` on active. No translation, no shadow shift.
- **Secondary / Outlined**: transparent background, 1 px slate border, secondary-text foreground, same padding. Used for navigation buttons in chrome ("Modules", "Retour Admin"), inline link chips inside cards.
- **Icon-only**: 36 px × 36 px square (`rounded-lg`), 1 px border, transparent fill. Used for dark/light toggle, pagination chevrons. Hover background `black/5` (light) or `white/5` (dark).
- **Destructive (red)**: `#dc2626` solid background, white text, used in the delete-confirmation modal. Never used on the dashboard surface itself — destructive intent is always behind a modal confirmation.

### Status Pills (eyebrow-style)

- **Shape:** `rounded-full` (pill).
- **Locked / Success**: `rgba(16, 185, 129, 0.12)` background, `#10b981` text, eyebrow type, lock icon prefix. Renders "VERROUILLÉ" in the platform card header.
- **Open / Neutral**: transparent background, 1 px slate border, muted text, lock-open icon prefix. Renders "OUVERT".
- **Caution / Warning**: `rgba(245, 158, 11, 0.15)` background, `#f59e0b` text, eyebrow type. Renders "BROUILLON" on draft modules.
- **Error**: a circle icon container (`#fee2e2` bg with `#dc2626` icon) used in the platform card error overlay. Not a pill in the same family.

### Cards / Containers

- **Corner Style:** generous 16 px radius (`rounded-2xl`) for the principal platform cards. 12 px (`rounded-xl`) for secondary containers (action tiles inside cards, audio items). 8 px (`rounded-lg`) for small chrome elements (buttons, inputs).
- **Background:** `#1e293b` in dark, `#ffffff` in light. The platform card carries a 1 px slate border at rest, switching to a 1 px violet border (`#8B5CF6`) when the platform is `active === true` — this is the *only* time the violet border-as-status pattern appears (and only because activeness here is a binding business state, not a hover effect).
- **Shadow Strategy:** see Elevation. Flat in dark, faint shadow in light. Never elevated in hover.
- **Border:** always 1 px, always slate (`#334155` dark / `#e2e8f0` light) unless violet is signaling "active platform."
- **Internal Padding:** 24 px (`p-6`).
- **Inactive overlay:** semi-opaque slate cover (`rgba(15, 23, 42, 0.85)` dark / `rgba(248, 250, 252, 0.95)` light) with `backdrop-filter: blur(4px)`, centered "BIENTÔT DISPONIBLE" eyebrow over a circular muted icon.

### Inputs / Fields

- **Style:** `rounded-lg` (8 px), 1 px slate border, recessed background (`#0f172a` dark / `#f8fafc` light). 12 px / 16 px padding for full-size, 8 px / 12 px for compact.
- **Focus:** Tailwind's `focus:ring-2 focus:ring-gray-500` is the current default. Future migration target: `focus:ring-2 focus:ring-violet-500/40` so focus carries the brand accent without screaming. Either way, no `focus:outline-none` without a visible alternative — that breaks the keyboard contract.
- **Disabled / Loading:** opacity 0.6, cursor not-allowed, background falls back to a flatter slate.

### Navigation / Chrome

- **Sticky top nav:** translucent `#1e293b` (dark) / `#ffffff` (light) with `backdrop-filter: blur(8px)`, 1 px bottom border. Vertical padding `py-4`. Wraps a flex row at `max-w-7xl px-6`.
- **Title block:** brand eyebrow ("LE SOCRATE · HR") tracked 0.2 em uppercase 10 px, h1 below at display scale (24 px / 700). No logo mark — see The No-Logo-Slop Rule below.
- **Right cluster:** dark/light icon-only toggle, "Modules" outlined button, "Nouvelle plateforme" primary button, "Retour Admin" outlined button. The primary CTA is the only filled button.

### Slide-to-Confirm (Signature)

The signature interaction. Used for irreversible state changes (lock platform / unlock + backup).

- **Track:** `rounded-full` 44 px tall, slate background that tints toward violet (`rgba(139, 92, 246, 0.15)` dark / `rgba(16, 185, 129, 0.08)` light) when locked, slate-neutral when unlocked. 1 px tinted border in same family.
- **Thumb:** 36 px × 36 px white circle with subtle shadow (`0 2px 6px rgba(0,0,0,0.12)` at rest, `0 4px 12px rgba(0,0,0,0.2)` when grabbed), `cursor: grab` / `grabbing`. Lock / lock-open / check icon inside.
- **Fill:** the area swept by the thumb fills with violet (or green in light) at progressively higher alpha as the user crosses the 85 % threshold.
- **Feedback:** label inside the track ("Glisser pour verrouiller / déverrouiller →") fades out as progress climbs, replaced by "✓ Confirmé" at completion.
- **Easing:** `cubic-bezier(0.34, 1.56, 0.64, 1)` — the *one* exception to "no bounce" allowed in the system. The slight overshoot signals lock-in. 350 ms duration. Do not propagate this curve to other components.

### Audio Item

- **Shape:** `rounded-lg`, recessed background (`#0f172a` dark / `#f1f5f9` light), 8 px / 12 px padding.
- **Play button:** 28 px × 28 px violet circle with white play / pause icon. The single tactile expression of the violet primary inside the audio panel.
- **Filename:** truncated body text, `title` attribute carries the full string for tooltip on overflow.
- **Size:** muted 10 px label, right-aligned.
- **Delete icon:** muted at rest, fades to rose (`#f87171`) on hover with a soft rose tint background. Single-step destructive — there is **no** confirmation modal at the audio-item level (decision: micro-action, undo via re-upload).

### Modal

- **Shape:** `rounded-2xl` (16 px), `#1e293b` (dark) / `#ffffff` (light) background, no shadow but `box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25)` is acceptable on the modal itself only (`shadow-2xl` Tailwind default — the *one* place in the system where a dramatic shadow is allowed because the modal is genuinely lifted off the page).
- **Header bar:** 24 px / 20 px padding, 1 px bottom divider in border color, title block on the left (icon-in-violet-square + h3 + helper text below), close button ("×") icon-only on the right.
- **Body:** scrollable, `max-height: calc(85vh − header)`, 24 px padding.
- **Backdrop:** `rgba(0, 0, 0, 0.6)`, click-outside dismisses (unless an irreversible operation is in progress).
- **Migration target:** `AudiosModal` and `PDFModal` currently render their headers in legacy `#137fec` (Stitch blue). Both must migrate to either the standard violet-square + slate header used by `Modules` and `Nouvelle plateforme` modals, **or** to a quieter neutral header. **Until migrated, the blue is technical debt, not a role.**

### Pagination

- **Shape:** "Page X / Y" muted body text + two icon-only chevron buttons. Right-aligned above the cards grid.
- **Buttons:** 40 px × 40 px (`rounded-xl`, 12 px), 1 px slate border, transparent fill, secondary-text icon. Hover `bg-black/5` / `bg-white/5`. Disabled at 30 % opacity. No filled circles, no numbered page list.
- **Threshold:** pagination renders only when `platforms.length > CARDS_PER_PAGE` (currently 3).

## 6. Do's and Don'ts

Concrete guardrails. Quote PRODUCT.md anti-references by name so the visual spec carries the strategic line through.

### Do:

- **Do** use Examiner's Violet (`#8B5CF6`) for the single most consequential action on each screen. Once or twice per surface. Earned by rarity, not repetition.
- **Do** keep neutrals on the slate spine (`#0f172a` / `#1e293b` / `#334155` / `#cbd5e1` / `#f1f5f9`). Faint chroma drift toward violet, never pure gray.
- **Do** treat dark and light as equally first-class. If you only design one of the two and shrug at the other, you're shipping a half-system.
- **Do** prefer tonal layering over shadows. Border + tonal shift conveys depth in dark mode; faint shadow on cards only in light mode.
- **Do** track all eyebrow labels (10 px, uppercase, letter-spacing 0.2 em). The eyebrow is the institutional voice of the system — give it room.
- **Do** confirm irreversible actions through the slide-to-confirm pattern, not a modal "Are you sure ?" dialog. The drag is the contract.
- **Do** use Material Icons via the local `<Icon name="..." />` helper. Inline-SVG one-offs are acceptable only for shapes Material Icons don't carry (rare).
- **Do** write microcopy as if it were going on a printed certificate: posée, claire, factuelle. No "Boost your career !", no "Tu peux le faire !", no exclamations except literal validation ("✓ Confirmé").
- **Do** migrate `AudiosModal` / `PDFModal` headers off Stitch blue (`#137fec`) on next touch.

### Don't:

- **Don't** ever ship a violet rounded-xl square with an abstract Material Icon (`hub`, `auto_awesome`, `bolt`, `category`) as a logo mark. This is the canonical AI-slop signature. (Real-world incident, April 2026 — refused on the dashboard chrome and removed.)
- **Don't** introduce edtech "playful" patterns: gamification, mascots, streaks, XP, level-up animations, celebration confetti, "Bravo ! 🎉", saturated yellow / orange / red primaries. Quote `PRODUCT.md` Anti-references by name.
- **Don't** use the hero-metric SaaS template (big number / small label / supporting stats / gradient accent). It is the cliché.
- **Don't** ship identical card grids — three or four equally-weighted cards with icon + title + paragraph in a 3-up row is the AI mockup tell. If two cards on screen have the same shape, their content must visibly distinguish them.
- **Don't** apply `background-clip: text` with a gradient to any heading, anywhere. Solid color, weight contrast, scale contrast — those carry hierarchy without ornament.
- **Don't** use glassmorphism (`backdrop-filter: blur(...)` over translucent surfaces) decoratively. The sticky top nav and the inactive-platform overlay are the only justified uses; do not extend the pattern.
- **Don't** use Tailwind's `gray-*`, `zinc-*`, `stone-*` palettes. Slate or nothing — and prefer the named tokens above over raw Tailwind colors.
- **Don't** introduce blue (`#137fec` or any `blue-*` from Tailwind) outside the documented Stitch debt in `AudiosModal` / `PDFModal`. There is no "info" blue in this system. The legacy blue is debt to repay, not a role to formalize.
- **Don't** add `hover:-translate-y-0.5` (or any layout-property animation) on hover. The system uses `transition-colors` and `transition-transform` (scale only) — moving an element on hover causes layout reflow and looks SaaS-default.
- **Don't** silence focus rings without an alternative. Keyboard users exist; the `focus-visible` outline is the contract.
- **Don't** scatter Examiner's Violet across the screen as decoration. If a screen has more than one or two violet elements competing, tone the lesser ones to slate and re-anchor on the single most consequential action.
- **Don't** mix Inter and Poppins on the admin surface. The apprenant side has Poppins; the admin side has Inter. The two systems do not cross. If you find yourself reaching for `font-family: 'Poppins'` inside `/hr-dashboard`, the answer is no.
- **Don't** add a "Layout" or "Motion" or "Responsive" top-level section to this DESIGN.md. The Stitch spec has six sections, not nine. Layout / motion / responsive content folds into Overview (philosophy) or Components (per-component behavior).
