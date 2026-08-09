# Recruiting Talent Workbench Design Contract

This file is the source of truth for the local web workbench UI. New screens must extend this contract instead of inventing a second visual language.

## Source Systems

- Open Design `application` package supplies the semantic color, type, spacing, elevation, and motion token model.
- Design OS supplies the application-shell pattern: compact sticky header, horizontal phase navigation, constrained work area, explicit current/upcoming states, and section-first implementation.
- React Bits supplies motion patterns only. The approved stage-one pattern is a restrained CountUp-style transition for loaded metrics.

The sources are references, not runtime dependencies. Their names and assets must not appear as product branding.

## Provenance

- Open Design: `https://github.com/nexu-io/open-design`, Apache-2.0. The local token names and values are adapted from its `design-systems/application` package.
- Design OS: `https://github.com/buildermethods/design-os`, MIT. The shell hierarchy and workflow-navigation behavior are adapted from `AppLayout` and `PhaseNav`.
- React Bits: `https://github.com/DavidHDev/react-bits`, MIT with Commons Clause. The metric transition is an original dependency-free adaptation of its CountUp interaction pattern; no React Bits runtime code or package is bundled.

Project constraints override source defaults where they conflict: letter spacing remains zero, radii do not exceed 8px, the workbench stays light-first, and decorative purple or animated backgrounds are prohibited.

## Product Intent

This is a Windows local-first recruiting operations tool. It must feel quiet, precise, trustworthy, and efficient during repeated scanning and split-screen work. It is not a marketing site and must not use hero composition inside the workbench.

## Application Shell

- Use a compact two-row top shell instead of a permanent wide sidebar.
- Row one owns product identity, local-service health, version metadata, and persistent utility actions such as settings.
- Row two owns workflow navigation and may scroll horizontally in narrow windows.
- Keep page content constrained to 1180px with 16-36px responsive gutters.
- Preserve visible current, disabled/upcoming, focus, loading, and error states.

## Color Roles

- Canvas: `#f6f7f9`.
- Primary surface: `#ffffff`.
- Subtle information surface: `#eef4ff`.
- Primary text: `#172033`; secondary text: `#3b4658`; muted text: `#6b7689`.
- Action blue: `#2563eb`, reserved for selection, focus, and primary commands.
- Success green: `#16a34a`, reserved for healthy or completed states.
- Warning amber and danger red are reserved for their semantic states.
- Do not introduce decorative gradients, purple accents, tinted shadows, or a one-hue page.

## Typography And Density

- Use Inter when locally available, then system UI and Microsoft YaHei.
- Use 12/14/16/18/22/30px as the working scale.
- Letter spacing is always zero.
- UI headings stay compact; 30px is the maximum workbench heading size.
- Use an 8px spacing rhythm with 4px optical adjustments where necessary.

## Components

- Radius scale is 4/6/8px. Cards never exceed 8px.
- Prefer borders and whitespace to shadows. Only setup or floating overlays may use a restrained neutral shadow.
- Repeated metrics may use individual cards; page sections remain unframed bands.
- Buttons and navigation use Lucide icons where a familiar symbol exists.
- Inputs retain visible labels and stable error regions.

## Motion

- Motion must communicate loading, state change, or navigation feedback.
- Approved durations are 140ms for control feedback and 220ms for page or section entry.
- CountUp-style metric motion may run once after data loads, for no more than 700ms.
- Do not use animated backgrounds, cursor effects, blur reveals, parallax, bouncing cards, or perpetual loops.
- `prefers-reduced-motion: reduce` disables every nonessential transition and displays final metric values immediately.

## Responsive Behavior

- At split-screen widths, retain the horizontal workflow rail and remove no primary content.
- Metrics collapse from three columns to one column below 760px.
- Status and data-path sections wrap before text collides.
- No fixed desktop-only minimum width beyond 320px.

## Voice

Use literal, concise Chinese labels. Status copy explains what happened and what the user can do next. Do not add visible design explanations, feature advertising, or tutorial prose inside operational pages.

## Acceptance Criteria

- The workbench remains usable at 1366x768, 900x700, and 390x844.
- No content overlaps or horizontal page overflow; only the workflow rail may scroll horizontally.
- Keyboard focus is visible and disabled navigation is unambiguous.
- Core information remains complete with motion disabled.
- Frontend tests, TypeScript build, and visual smoke checks pass.
