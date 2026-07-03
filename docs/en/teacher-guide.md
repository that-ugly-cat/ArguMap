# ArguMap — Teacher Guide

This guide covers what teachers can do beyond the [User Guide](/docs/user-guide), which also applies to you: course oversight, guided templates, editing student maps, and running collaborative annotation.

---

## 1. Your role

An administrator associates you with one or more courses. You can:

- Use ArguMap yourself (pipeline, guided, manual, viewer, Debate-A-Bot) — same as students.
- Open your course page to see enrolled students and their submitted maps.
- **Open and edit** any map submitted to your courses.
- Author **guided templates** and hand them to students.
- Open a map for **collaborative annotation** and moderate it.

You can't create/delete users or courses, or open the admin panel — contact the administrator for those.

In the dashboard header you have **My Courses** and **Templates** (and, if you're also an admin, **Admin**).

---

## 2. Your courses

Click **My Courses**, then **Manage** on a course. The course page shows:

- **Enrolled students** — the roster (adding/removing students is an admin action).
- **Submitted maps** — every map assigned to this course, with **Open →** for each.

---

## 3. Reviewing and editing student maps

Click **Open →** on a student's map. A banner marks whose map it is (*👁 Reviewing [Name]'s map*), but you can now **edit it** — fix a relation, restructure, correct a label — and your changes are saved (there's a Save button, and edits also autosave while the annotation layer is on). 

> Editing a student's map **overwrites their submission**. If you want to demonstrate without changing their work, do it on a copy.

What to look at: is the **claim** specific? Are **relations** (`supports` / `attacks` / `qualifies`) right? Are co-dependent premises grouped under a **∧ joiner**? Are **objections** (red) present and pointed at the right target? Are weak steps flagged with an accurate **fallacy/bias**? Are **references** in the node notes?

---

## 4. Guided templates

A template is a scaffold you author once and hand to a whole class. Open **Templates** in the header.

### Create a template
- **Claim** — the thesis. You can leave a blank in square brackets, e.g. *"`[criterion]` should be the primary criterion for triage"*; the student fills only that blank.
- **Empirical / Normative / Objection premises** — one entry per line. A plain line becomes a **preset option** the student picks from in guided mode; a line starting with **`*`** is **pre-seeded onto the student's map** — seeded premises land under a ∧ joiner supporting the claim, seeded objections are added as free nodes.
- **Course** — bind the template to a course (optional).

Click **Create**. You get a shareable link (`.../t/<id>`).

### Distribute it
Send the link. When a logged-in student opens it, ArguMap creates their own copy of the map in their dashboard (idempotent — reopening returns the same map, so their work is preserved) and drops them into guided construction. Their finished maps land in the bound course, where you review them (§3).

### Edit, push, delete
- **Edit** — change the claim, options, or seeds. Edits apply to *future* opens; students who already started keep their map (a still-untouched map is refreshed to the latest seed).
- **Push** — send a copy of a template to another teacher or admin; it appears in their Templates list.
- **Delete** — removes the template; maps students already created are kept.

### Example (Exercise: choosing an empirical premise)
Claim (locked): *"Old age should be an exclusionary criterion for triage"*; a `*` normative premise (given, under ∧); three plain empirical options (correlation / high statistical likelihood / strict causation) for the student to choose the one that makes the argument valid.

---

## 5. Collaborative annotation

You can open any map you can edit (your own, or a student's course map) for the whole class to annotate in real time.

### Open a session
Turn on **Annotate** in the viewer toolbar. In the panel:

- **Open annotation** — generates a shareable `.../annotate/...` link and starts accepting annotations. **Copy link** and share it (students need no account — an anonymous identity is used if they aren't logged in).
- **Anonymous sharing** — tick this to hide your name from annotators (they see *"someone's map"*).
- **New session (clear)** — archives the current annotations and starts a clean layer (nothing is deleted).
- **Detached** — review/clear annotations left orphaned when a node/edge was removed.

### During annotation
- Students click nodes/edges and add **plausibility (1–5)**, **comments**, and **fallacy/bias** flags (from the catalog). On the map you see a **distribution bar** of plausibility, a comment badge, and coloured fallacy/bias chips — refreshing live.
- Select a node yourself and its thread appears in the edit panel, alongside the edit fields — so you can read the comments and edit the node in one place.
- You can **delete any annotation** (moderation), not just your own.
- Because you can edit the map while annotation is on, your structural changes are **saved automatically and appear live** for everyone viewing the link.

---

## 6. Suggested workflows

- **Pipeline first draft** — students paste a text, get an auto-map, then refine and submit.
- **Manual / guided from scratch** — better for engaging with structure directly; use a **template** to give everyone the same starting point.
- **Live class annotation** — project a strong (or flawed) student map, open annotation, and have the class rate plausibility and flag fallacies together; discuss the aggregate.
- **Debate-A-Bot** — a formative check: students argue against the AI to stress-test a map before submitting.
- **Chain highlight** — click a node during discussion to isolate its inferential chain on the projector.

---

## 7. Contacting the administrator

For: adding/removing students, creating courses, resetting passwords, token budgets, or bulk Excel import.

---

*ArguMap — built with FastAPI, AntV X6, and Claude (Anthropic)*
