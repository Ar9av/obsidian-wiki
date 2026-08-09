---
name: obsidian-layout-adjustment
description: >
  Workflow for working with the user on changing how Obsidian looks using CSS snippets.
  Use this whenever the user asks to restyle Obsidian, tune a vault's visual layout,
  adjust tabs, sidebars, note surfaces, properties, backlinks, graph panes, file
  explorer rows, icons, links, shadows, active states, or CSS snippets. Also use
  it when the user says a visual CSS change did nothing, still looks wrapped, is not
  lifted, is unreadable, or needs to be refactored without changing the current
  appearance.
---

# Obsidian Layout Adjustment

This skill is for changing how Obsidian looks with CSS files while working with the user's visual language.

Obsidian is always the same kind of environment: app frame, tab headers, side docks, view headers, pane shells, note surface, properties, file explorer, backlinks, graph, rendered markdown, and status bar. The vault, theme, snippets, plugins, and desired taste direction change, but the canvas stays Obsidian.

The core behavior is translation:

> the user names a visible Obsidian object. Translate that phrase into the stable Obsidian layer/backend object, edit the active snippets safely, screenshot the result, and keep iterating without losing good states.

This is not a general CSS workflow and not a fixed-theme generator.

## Normal Output Mode

This skill should make live styling work faster, not turn every small request into a report.

In normal use:

1. Say the mapping only when it prevents ambiguity.
2. Keep the mapping short: one sentence is usually enough.
3. Then act: inspect active snippets, checkpoint, patch, format, reload, screenshot.
4. Report the result concisely with changed files, checkpoint, and screenshot status.

Good normal update:

> "I’m treating 'tabs above the note' as workspace tab headers, not the arrows/book/dots view header. I’ll checkpoint active snippets, patch that selector family only, and screenshot the tab strip."

Do not write a long workflow report unless:

- the user asks for a plan, audit, review, or explanation.
- You are running evals or building this skill.
- You are refactoring without visual changes.
- The request is ambiguous enough that acting first would be risky.

The value is in preventing bad CSS loops while still moving quickly.

## Use The Reference

Read `references/workflow-reference.md` when:

- the user names a visible Obsidian object in natural language.
- The requested target could be more than one Obsidian layer.
- A screenshot shows "nothing changed," "still wrapped," "not lifted," uneven edges, washed-out surfaces, or unreadable icons.
- You are refactoring active snippets without changing the accepted look.
- You need the Obsidian surface map, change-type map, or failure-pattern list.

The reference is Obsidian-specific. Use it before treating the UI as an unknown web page.

## Operating Loop

1. Start from the live vault.
2. Read `<vault>/.obsidian/appearance.json`.
3. Treat `enabledCssSnippets` as the active styling source of truth.
4. Read active snippets before archives, backups, or old experiments.
5. Translate the user's phrase into an Obsidian object and owning layer.
6. Classify the change type: color, readability, lift, shape, structure, density, simplification, workflow, or refactor.
7. Save a named checkpoint before subjective edits: copy the active snippets to `.obsidian/snippet-archive/`, never into `.obsidian/snippets`, so the snippet picker stays clean.
8. Re-read the exact current block, then edit one owning layer: stage, shell, header, wrapper, or child. Formatting reshapes the file; a patch written from a remembered shape misses mechanically.
9. Format CSS.
10. Reload/focus Obsidian and screenshot the exact affected area.
11. Use the screenshot and the user's correction as evidence.
12. If it fails, inspect ownership or restore; do not keep piling CSS onto the same wrong target.
13. Refactor only after the user accepts the visual state.

## Translate Before Editing

The user will usually name what they see, not the selector:

- "tabs above the note"
- "arrows/book/dots above the note"
- "left side note buttons"
- "right sidebar"
- "links in those little areas"
- "the thing around the note"
- "selected icon"
- "top-left white corner"

Before editing, map the phrase:

```text
user phrase -> visible object -> Obsidian layer -> likely selector/settings surface -> change type -> owning layer
```

Say the mapping back when it could be ambiguous:

> "When you say the tabs above the note, I am treating that as the workspace tab headers, not the arrows/book/dots row inside the note pane."

This is the main mistake-prevention step. Most frustrating failures came from changing a plausible element that was not the object the user meant, or changing a child when the wrapper/header/stage owned the visible shape.

## Stable Layer Stack

Use this compact map first, then verify exact selectors in the live vault:

| the user points at | Usually means |
| --- | --- |
| top-left white/native area | titlebar/native chrome or adjacent app header |
| tabs above note | workspace tab headers |
| plus next to tab | new tab control |
| green/top bar | app frame or tab header container |
| far-left icons | ribbon / side dock |
| selected side icon | active side-dock tab header plus icon state |
| buttons above file list | file explorer nav controls |
| left note/folder buttons | file explorer tree rows |
| vault name/footer | side dock profile/footer |
| arrows/book/dots above note | markdown view header |
| note/page/paper | markdown leaf, editor, or readable surface |
| note shadow/lift/edge | stage, shell, gutter, overflow, or pseudo-element relationship |
| properties | metadata container or Properties View workflow |
| links | internal link spans in reading/editing modes |
| right sidebar | right workspace split and utility leaves |
| linked mentions/backlinks | backlinks plugin result groups |
| graph | graph plugin leaf/canvas |
| bottom stats | status bar |

The visible object and backend layer should be treated as stable across Obsidian work. Exact class names can vary by theme/plugin/app version, so verify in the live vault before patching.

## Change-Type Split

The same object needs different work depending on the request:

- **Color/accent**: update background, text, border, icon stroke/fill, and active/hover/focus states together.
- **Readability**: check rendered contrast, especially for icons on colored toolbars.
- **Lift/depth**: decide foreground, stage, shell, gutter, overflow, and exterior shadow. Lift is a relationship, not just `box-shadow`.
- **Rounded corners**: check parent shell, child radius, overflow, and adjacent background.
- **Structure**: style the wrapper/header/shell that owns the visible shape.
- **Simplification**: remove wrappers, borders, gradients, shadows, or pseudo-elements before adding more treatment.
- **Properties/workflow**: consider Obsidian's Properties View or display settings before CSS-compressing metadata.
- **Refactor**: preserve cascade order and verify the screenshot does not change.

If a target needs two change types, do two passes. For example, make side-dock icons readable first, then tune the selected-state color.

## What To Change First

Start with:

- active CSS snippets from `appearance.json`
- Obsidian settings when the issue is a workspace behavior
- Style Settings or theme variables when the change should remain tunable
- stable Obsidian wrappers: tab headers, view headers, pane shells, side docks, file rows, note surface, backlinks groups

Avoid changing first:

- Obsidian app bundle files
- community plugin source files
- installed theme source files
- vault content just to force visual styling
- app internals/minified code before active snippets and theme CSS are ruled out

Ask for explicit confirmation before:

- switching themes
- disabling snippets or plugins
- hiding/moving properties as a workflow change
- changing global typography or editor density substantially
- deleting archived experiments
- changing files outside `.obsidian/snippets` or Obsidian settings

## Screenshot Gate

CSS validity is not visual success. The screenshot is product truth.

For every meaningful visual pass:

1. Save checkpoint.
2. Patch.
3. Format CSS.
4. Reload or focus Obsidian.
5. Screenshot the affected area.
6. Compare the screenshot to the complaint.

If another window covers Obsidian, retake the screenshot. Verify the verifier: confirm Obsidian is actually frontmost before trusting a capture (AppleScript can check the frontmost process). If the issue is tiny, capture just that region — `screencapture -R<x,y,w,h> out.png` — around the edge, icon, tab, row, or pane.

If the screenshot disproves the fix, keep working, restore, or say it failed. Do not close as if formatting proved success.

## Failure Signals

the user's corrections are selector evidence:

- "nothing changed" means wrong selector, wrong layer, clipping, coverage, or override.
- "still wrapped" usually means both wrapper and child are styled.
- "not lifted" means the stage/shell/gutter relationship is wrong or too subtle.
- "right side got lighter" points to an overlay or pseudo-element on top of the note.
- "icon is impossible to see" means active/inactive button fill and icon color must be handled together.
- "overdone" often means remove treatment before adding another one.

If a direction fails twice, restore the last good checkpoint and change the ownership model.

## Refactor Rule

Do not refactor during taste exploration.

When the user likes the look:

1. Save a baseline checkpoint.
2. Add or update a file map and section headers.
3. Preserve selector order unless changing it intentionally.
4. Format CSS.
5. Check the diff for accidental visual changes.
6. Screenshot Obsidian.
7. Archive inactive iterations outside `.obsidian/snippets`.

CSS size is usually less dangerous than cascade confusion and a messy active snippet picker.

## Closing Report

When done, keep the closeout short. Report:

- active snippet files changed
- checkpoint paths saved
- what user phrase mapped to which Obsidian layer
- what was screenshot-verified
- anything not verified or intentionally deferred

Avoid explaining the whole workflow after every small pass. The workflow should be visible in the actions: checkpoint, scoped edit, screenshot, and evidence-based next step.
