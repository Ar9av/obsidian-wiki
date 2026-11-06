# Obsidian Layout Workflow Reference

Use this reference when working with the user on changing how Obsidian looks using CSS snippets.

This file is intentionally Obsidian-specific. The design direction can change, but the canvas stays Obsidian: app frame, tab headers, side docks, view headers, pane shells, note surface, metadata, rendered markdown, file explorer, utility panes, graph, and status bar.

## User Language To Obsidian Backend

the user names the visible object. Translate it into the Obsidian object before editing.

For live styling work, this translation should usually be brief and operational:

> "I’m treating 'right sidebar' as the right workspace split/backlinks pane, and 'side icons' as side-dock tab/header icon states."

Then inspect, checkpoint, patch, format, reload, and screenshot. Long translation tables belong in evals, audits, or planning notes, not in every small visual pass.

| the user might say | Usually means | Backend / selector family to inspect |
| --- | --- | --- |
| tabs above the note | open workspace tab headers | `.workspace-tab-header-container`, `.workspace-tab-header`, `.workspace-tab-header-inner` |
| plus next to the tab | new tab button in tab strip | `.workspace-tab-header-new-tab`, tab header `.clickable-icon` |
| green bar / top bar / row across top | app frame or workspace tab header strip | `.workspace-tab-header-container`, titlebar variables |
| top-left corner is white | native titlebar area or neighboring app row | `--titlebar-background`, `--titlebar-background-focused`, adjacent tab header container |
| icons on far left | ribbon / side dock | `.workspace-ribbon`, `.side-dock-ribbon`, `.workspace-ribbon.mod-left` |
| selected icon | active side-dock tab header, not only the SVG | side-dock `.workspace-tab-header.is-active`, nested icon |
| secondary icons | view action buttons in pane headers | `.view-actions .clickable-icon`, `.view-header .clickable-icon` |
| buttons above the file list | file explorer nav buttons | `.nav-buttons-container`, `.nav-action-button`, `.clickable-icon` |
| left side note buttons | file explorer note/folder rows | `.nav-file-title`, `.nav-folder-title`, `.tree-item-self` |
| folder/note color | explicit file explorer row mapping or fallback | `data-path` selectors, track variables |
| bottom vault name | vault switcher / left footer | `.workspace-sidedock-vault-profile` |
| arrows/book/dots above the note | markdown view header | `.view-header`, `.view-header-nav-buttons`, `.view-actions` |
| stripe below the header | view header, markdown body layer, or pseudo-element | `.view-header`, markdown leaf, `::before` / `::after` |
| the note / page / paper | markdown pane or readable/editor surface | markdown leaf, preview sizer, editor content container |
| note shadow / right edge | stage, shell, gutter, or parent clipping | workspace split, markdown shell, pseudo-elements, overflow |
| right side got lighter | overlay or pseudo-element over note surface | markdown pane `::before` / `::after`, gradients |
| properties at the top | metadata container or Properties View | `.metadata-container`, `.metadata-properties`, Properties plugin/settings |
| right sidebar | right utility split | `.workspace-split.mod-right-split`, right pane leaves |
| backlinks pane / linked mentions | backlink plugin content and groups | backlink pane, search result wrappers |
| links to other pages | internal links in reading/editing modes | `.internal-link`, `.cm-hmd-internal-link`, unresolved link selectors |
| graph view | graph plugin pane/canvas | `.workspace-leaf-content[data-type='graph']`, graph canvas/container |
| bottom stats | status bar | `.status-bar`, status bar items |

If the phrase could mean more than one layer, say the mapping back before editing.

## Stable Obsidian Surface Map

| Visible area | Obsidian layer | What can usually be changed | Caution |
| --- | --- | --- | --- |
| native/titlebar area | native/window chrome and titlebar-adjacent app row | exposed titlebar variables, adjacent row color | native chrome may not be fully reachable |
| top strip with open note tabs | workspace tab header layer | active/inactive tab shape, background, text, close icon, plus button, spacing | different from markdown view header |
| left vertical icon rail | ribbon / side dock | rail background, icon button shape, active/inactive states, icon contrast | active state needs fill and icon color |
| file explorer action buttons | file explorer nav controls | icon buttons, spacing, selected/hover states | should not fight file rows |
| file/folder list | file explorer tree | row shape, explicit color mapping, fallback color, selected/hover state, density | avoid accidental meaning from positional cycling |
| vault name/footer | side dock footer/profile | background, text/icon contrast, spacing | should belong to side rail/frame |
| arrows/book/dots row | markdown view header | shelf color, icon readability, border/stripe removal | "header" may mean tab header or view header |
| note/page/paper | markdown leaf and readable/editor surface | paper color, width, padding, rounded corners, editor/reader parity | lift belongs to shell/stage relationship |
| note edge/shadow/lift | stage, pane shell, split gutter | background, spacing, exterior shadow, overflow/gutter | too much gutter becomes a slab |
| properties block | metadata/properties layer | compacting, card treatment, muted labels, or moving workflow to Properties View | often a setting/workflow question |
| rendered markdown | headings, links, callouts, lists, code, embeds | semantic styling | persistent surfaces should carry identity first |
| internal links | rendered and editor link spans | color, underline, background, editor/reader parity | links are high-value objects |
| right utility panes | right workspace split and utility leaves | pane shell, header shelf, group spacing, background, icon states | utility panes usually need less treatment |
| backlinks/search results | plugin result tree | group wrappers, excerpt rows, match highlights, link color | avoid wrapper plus child card treatment |
| graph view | graph plugin leaf/canvas | pane shell, background, reachable graph colors | canvas internals may be limited |
| status bar | bottom app status layer | background, text/icon color, spacing | should belong to app frame language |
| Style Settings/theme variables | theme control layer | global colors, density, typography, radius, plugin-exposed controls | use when future tuning matters |

## Change-Type Map

The same visible object can require different backend work depending on what the user asks for.

### Color or accent

Usually adjust background, text color, border color, icon stroke/fill, active state, hover state, focused state, and muted/disabled state together.

Failure pattern: changing only the background makes icons or text unreadable.

### Readability

Usually adjust rendered contrast, button background and icon color together, selected/unselected states, hover/focus states, and muted text.

Failure pattern: a subtle top border or theoretically nice palette fails in the actual toolbar.

### Lift or depth

Usually adjust stage color, shell spacing, parent overflow, exposed gutter, exterior shadow, and pseudo-elements only when they sit outside the content surface.

Failure pattern: adding more shadow does nothing because it is behind the object, clipped, or covered. Interior highlights can wash out the note.

### Rounded corners

Usually adjust parent shell radius, child radius, overflow behavior, and adjacent surface color.

Failure pattern: the inner child becomes rounded but the parent still clips square.

### Structure

Usually adjust pane shell, wrapper, header shelf, or group container.

Failure pattern: bordering an inner element makes the UI look double-wrapped.

### Simplification

Usually remove borders, wrappers, gradients, shadows, pseudo-elements, or nested card styling.

Failure pattern: adding more treatment makes an already overdone area worse.

### Properties and metadata

First consider Obsidian's built-in Properties View, display settings, or sidebar workflow. Use CSS compacting after deciding the workflow.

Failure pattern: treating properties as only a CSS block ignores that the object may belong somewhere else.

### Refactor

Save a baseline, preserve selector order, add section headers/file map, format, screenshot, and archive inactive experiments outside `.obsidian/snippets`.

Failure pattern: reordering or deleting during refactor changes the look.

## Ownership Model

Pick the object that owns the visible shape:

- **Stage**: background an object lifts off from.
- **Shell**: pane, note surface, or card container.
- **Header**: tab strip, view toolbar, or pane shelf.
- **Wrapper**: repeated group such as file row or backlink group.
- **Child**: text, icon, link, match span, or excerpt.

Prefer the highest layer that owns the visible object. If both wrapper and child are styled, the UI often looks double-wrapped.

## Specific Mistake Patterns

Because Obsidian's layer map is stable, the mistakes can be specific:

- Confusing workspace tab headers with markdown view headers.
- Styling a result row when the backlink group wrapper owns the shape.
- Trying to create note lift from inside the note surface instead of the stage/gutter.
- Treating side-dock icon color as only SVG color instead of active tab state plus icon contrast.
- Changing child radius while the parent shell still clips square.
- Assuming native titlebar area can always be styled directly.
- Treating properties as only a CSS block instead of a possible workspace/sidebar workflow.
- Chasing app internals before ruling out active snippets.
- Patching from a remembered file shape after the formatter reshaped it, so the edit misses mechanically.

## Failure Signals

the user's corrections are diagnostic:

- **"Nothing changed"**: wrong selector, wrong layer, clipping, coverage, override, or not reloaded.
- **"Still wrapped"**: wrapper and child both styled; pick one.
- **"Not lifted"**: wrong stage/shell/gutter model, clipped shadow, insufficient surface contrast, or overly subtle effect.
- **"Right side got lighter"**: overlay or pseudo-element sits over the content surface.
- **"Icon is impossible to see"**: active/inactive fill and icon color must be tested together.
- **"Overdone"**: remove treatment before adding another.
- **"Wrong side"**: mapping was not restated; stop and remap.

If the same failure repeats twice, restore the last good checkpoint and change the ownership model.

## Breakthrough Concepts

- The screenshot is product truth.
- the user's corrections are selector evidence.
- Obsidian is layered furniture, not a flat page.
- The owning wrapper matters more than the prettiest selector.
- Lift is a relationship, not a shadow.
- Accent works when it becomes architecture.
- Navigation can carry mental model.
- Refactor only after the look lands.

## Snippet Organization

For a mature active snippet, prefer sections like:

1. Design tokens and Style Settings controls.
2. Theme/app variables.
3. App frame and titlebar.
4. Workspace panes and gutters.
5. Tabs and side-dock controls.
6. Main note/editor surface.
7. Properties and metadata.
8. Left explorer.
9. Right utility panes.
10. Rendered markdown objects.
11. Track or note/folder mappings.
12. Utilities and compatibility overrides.

Keep experiments outside `.obsidian/snippets` so the snippet picker stays clean. Active snippets should be the live design, not the archive.

## What Usually Should Not Be Changed First

Avoid these as first moves:

- Obsidian app bundle files.
- Community plugin source files.
- Installed theme source files.
- Vault content just to force visual styling.
- Large typography changes bundled with unrelated layout changes.
- Rare markdown components used as the main identity system.
- App internals/minified code before active snippets and theme CSS are ruled out.
- Broad snippet rewrites before a stable visual state exists.
- Deleting old experiments before the accepted look is checkpointed.

## Explicit Confirmation Zone

Ask before:

- switching themes
- disabling snippets or plugins
- hiding or moving properties/metadata as a workflow change
- changing global typography or editor density substantially
- changing file/folder color logic from explicit mapping to automatic cycling
- deleting or archive-cleaning old snippet iterations
- changing anything outside `.obsidian/snippets` or Obsidian settings files
