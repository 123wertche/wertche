# Compact Workbench Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the local crawler workbench into a compact desktop two-column operations layout that remains a usable single-column page on small screens.

**Architecture:** Preserve every existing backend endpoint and front-end element ID. Restructure only `workbench/index.html`, style the new layout in `workbench/style.css`, and make minimal rendering adjustments in `workbench/app.js` where the compact creator rows need additional state or accessible labels.

**Tech Stack:** Static HTML5, CSS, vanilla JavaScript, Python `unittest`, in-app browser verification.

## Global Constraints

- Do not modify crawler, transcription, Feishu, pipeline, or file-processing behavior.
- Keep the service bound to `127.0.0.1` and do not add dependencies or external fonts.
- Preserve all existing API paths and the IDs used by `workbench/app.js`.
- Keep default video count `2` and device selection `auto`.
- Do not add Xiaohongshu support or enable deletion actions.
- Desktop breakpoint is `880px`; narrow-screen breakpoint is `560px`.

---

### Task 1: Compact semantic page structure

**Files:**
- Modify: `workbench/index.html`
- Modify: `tests/test_local_workbench.py`

**Interfaces:**
- Consumes: Existing element IDs referenced by `workbench/app.js`.
- Produces: `.workspace-grid`, `.workspace-primary`, `.workspace-rail`, `.status-strip`, and `.run-card` layout hooks while preserving every existing interactive ID.

- [ ] **Step 1: Add a failing markup contract test**

Add a test that requests `/`, decodes the HTML, and asserts the compact structural hooks exist while the current interactive IDs remain present:

```python
def test_root_uses_compact_two_column_workbench_structure(self):
    status, _, body = self.request("GET", "/")
    html = body.decode("utf-8")
    self.assertEqual(status, 200)
    for marker in ('class="workspace-grid"', 'class="workspace-primary"', 'class="workspace-rail"', 'class="status-strip"'):
        self.assertIn(marker, html)
    for element_id in ("creator-list", "video-count", "device", "run-pipeline", "pipeline-log"):
        self.assertIn(f'id="{element_id}"', html)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench.LocalWorkbenchHttpTests.test_root_uses_compact_two_column_workbench_structure -v`

Expected: `FAIL` because `.workspace-grid` is absent.

- [ ] **Step 3: Restructure the HTML without changing behavior**

Use this hierarchy inside `<main>`:

```html
<header class="app-header">...</header>
<div id="notice" role="status" aria-live="polite"></div>
<section class="status-strip" aria-label="工作台概况">...</section>
<div class="workspace-grid">
  <div class="workspace-primary">
    <section class="panel creator-panel">...</section>
    <section class="panel settings-panel">...</section>
  </div>
  <aside class="workspace-rail" aria-label="执行与结果">
    <section class="panel run-card">...</section>
    <section id="confirmation" class="panel confirm" hidden>...</section>
    <section class="panel progress-card">...</section>
  </aside>
</div>
<details class="panel advanced">...</details>
<details class="danger">...</details>
```

Keep `creator-urls`, `add-creators`, platform filter buttons, `video-count`, `model`, `device`, `transcribe`, `comments`, `run-pipeline`, confirmation IDs, progress IDs, health IDs, lifecycle buttons and artifact IDs unchanged.

- [ ] **Step 4: Run the markup contract test**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench.LocalWorkbenchHttpTests.test_root_uses_compact_two_column_workbench_structure -v`

Expected: `OK` with one passing test.

---

### Task 2: Dense responsive styling and interaction QA

**Files:**
- Modify: `workbench/style.css`
- Modify: `workbench/app.js`
- Modify: `tests/test_local_workbench.py`

**Interfaces:**
- Consumes: Structural classes from Task 1 and the existing creator/pipeline API response shapes.
- Produces: A 58/42 desktop grid, a single-column mobile grid, stable log sizing, semantic creator selection state, and visible keyboard focus.

- [ ] **Step 1: Add a failing static asset contract test**

Add a test that requests `/style.css` and `/app.js` and checks the responsive/accessibility hooks:

```python
def test_compact_assets_include_responsive_and_accessibility_contracts(self):
    css_status, _, css_body = self.request("GET", "/style.css")
    js_status, _, js_body = self.request("GET", "/app.js")
    css = css_body.decode("utf-8")
    javascript = js_body.decode("utf-8")
    self.assertEqual((css_status, js_status), (200, 200))
    self.assertIn("grid-template-columns:minmax(0,58fr) minmax(340px,42fr)", css.replace(" ", ""))
    self.assertIn("@media(max-width:880px)", css.replace(" ", ""))
    self.assertIn("prefers-reduced-motion", css)
    self.assertIn("aria-checked", javascript)
```

- [ ] **Step 2: Run the asset test and confirm it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench.LocalWorkbenchHttpTests.test_compact_assets_include_responsive_and_accessibility_contracts -v`

Expected: `FAIL` because the 58/42 grid and `aria-checked` state are absent.

- [ ] **Step 3: Implement compact styling**

Define semantic CSS tokens for background, surface, text, muted text, border, primary, success and danger. Apply:

```css
.workspace-grid{display:grid;grid-template-columns:minmax(0,58fr) minmax(340px,42fr);gap:16px;align-items:start}
.workspace-primary,.workspace-rail{display:grid;gap:12px;min-width:0}
.workspace-rail{position:sticky;top:12px}
#pipeline-log{height:280px;min-height:280px;margin:0}
@media(max-width:880px){.workspace-grid{grid-template-columns:1fr}.workspace-rail{position:static}}
@media(max-width:560px){.add-row,.settings,.header-actions{grid-template-columns:1fr}.shell{width:min(100% - 16px,1100px)}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition-duration:.01ms!important}}
```

Use a 4/8px spacing scale, 40px minimum control height, 14px minimum content text, an explicit `:focus-visible` ring, compact creator rows, and restrained shadows. Keep dangerous actions visually separate and collapsed.

- [ ] **Step 4: Improve creator selection semantics**

In `renderCreators()`, set the creator row state after assigning its class:

```javascript
label.setAttribute("aria-checked", selected.has(creator.local_id) ? "true" : "false");
label.title = creator.homepage_url;
```

Keep all API calls and pipeline polling behavior unchanged.

- [ ] **Step 5: Run focused and full automated tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expected: Both commands exit `0`; the full suite reports no failures or errors.

- [ ] **Step 6: Verify the rendered page**

Open `http://127.0.0.1:8765/` and verify:

- Desktop viewport displays left configuration and right execution/results columns.
- 375px viewport displays one column without horizontal scrolling.
- Four saved creators are visible and selectable.
- Default video count is `2`; device text indicates GPU-first automatic fallback.
- Advanced tools and dangerous actions remain collapsed.
- The one-click button, confirmation area and log remain discoverable.

- [ ] **Step 7: Commit only the layout files if Git identity is available**

```powershell
git add workbench/index.html workbench/style.css workbench/app.js tests/test_local_workbench.py docs/superpowers/specs/2026-07-20-compact-workbench-layout-design.md docs/superpowers/plans/2026-07-20-compact-workbench-layout.md
git commit -m "feat: compact local workbench layout"
```

If Git author identity remains unavailable, do not change local or global Git configuration; leave the changes uncommitted and report that limitation.
