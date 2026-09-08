# ArguMap — Admin Guide

This guide covers what administrators can do beyond the [User Guide](/docs/user-guide) and [Teacher Guide](/docs/teacher-guide), both of which also apply to you. As an admin you see the teacher menus too (**My Courses**, **Templates**) plus **Admin** in the dashboard header.

---

## 1. Permission levels

ArguMap has five roles; each inherits the capabilities of the one below it.

| Role | Manual / guided | Pipeline | Debate-A-Bot | Course overview, templates & annotation | Admin panel |
|------|:---------------:|:--------:|:------------:|:---------------------------------------:|:-----------:|
| **basic** | ✓ | — | — | — | — |
| **standard** | ✓ | ✓ | — | — | — |
| **full** | ✓ | ✓ | ✓ | — | — |
| **teacher** | ✓ | ✓ | ✓ | ✓ | — |
| **admin** | ✓ | ✓ | ✓ | ✓ | ✓ |

The **course overview, templates & annotation** column is the teacher tier: reviewing and editing course maps, authoring/pushing guided templates, and running collaborative annotation. It is granted by the `view_course_maps` permission, which both **teacher** and **admin** hold.

### Role and course listing are two separate switches

This is the single most common source of confusion, so it is worth stating plainly. Teaching a course takes **both**:

1. the **teacher** (or **admin**) role on the account — *may this person teach at all*;
2. being listed as a **teacher of that course** (Courses → Manage → add teacher) — *which courses*.

Neither half works alone. Someone listed on a course with the **full** role gets *Forbidden* on the course page and on every student map — the listing is there, the permission is not. Conversely, a teacher listed on no course sees an empty **My Courses**.

**`teacher` is exactly `full` plus `view_course_maps`.** Promoting a colleague from **full** to **teacher** takes nothing away and grants no new spending: `pipeline` and `debate` are the two capabilities that consume the API key, and **full** already has both. If cost is the worry, the lever is the monthly budget (§5), not the role.

Note that adding a teacher to a course **requires the role first**: the form refuses an account that does not already hold `view_course_maps`. Change the role, then add them to the course.

### Who can open which map

| The map is… | Its owner | A teacher of its course | An admin |
|---|:--:|:--:|:--:|
| assigned to a course | ✓ | ✓ | ✓ |
| not assigned to any course | ✓ | — | — |

A map with no course is private to whoever wrote it, **admins included**. Assignment to a course is the hand-in, and there is no back door around it: to review a student's work, the student must have handed it in (User Guide §2). Anyone who can open a map can also edit it and run its annotation layer, class code and QR included.

**When to use each role:**
- **basic** — construct maps by hand only (e.g. introductory exercises where the pipeline would short-circuit the learning goal).
- **standard** — typical students: manual/guided construction + automated analysis.
- **full** — students who should also have Debate-A-Bot.
- **teacher** — course instructors: full student features + course review/edit, templates, and annotation sessions.
- **admin** — system administrators.

---

## 2. The admin panel

Click **Admin**. It has three sections: **Users**, **Usage & costs**, and **Courses**.

---

## 3. Managing users

- **Create** — fill name, email, temporary password, role → **Add user**.
- **Change role** — the role dropdown in the table; takes effect immediately.
- **Activate / deactivate** — suspend a user without deleting their data; deactivated users can't sign in.
- **Reset password** — enter a new password on the user's row → **Set**.
- **Delete** — irreversible; all maps owned by that user are deleted too.
- **Batch actions** — select rows with the checkboxes, then Activate / Deactivate / Delete from the batch bar.
- **Filter by course** — the dropdown above the table.

### Import users from Excel
Click **Import from Excel**. Columns:

| Column | Required | Notes |
|--------|----------|-------|
| `name` | Yes | — |
| `email` | Yes | Must be unique |
| `password` | No | Auto-generated if empty — shown once after import |
| `role` | No | Defaults to `standard` if omitted or unrecognised |
| `course` | No | Matched by name; the user is enrolled if the course is found |

After import, a results panel shows created users (auto-generated passwords highlighted in amber), skipped emails (already exist), and row errors. **Copy any auto-generated passwords before closing** — they are not stored in plain text.

---

## 4. Managing courses

- **Create** — enter a name in the Courses section → **Create**.
- **Manage** — open a course's detail page to add/remove **students** and add/remove **teachers**. A course can have several teachers (they all see it under *My Courses* and can review, edit, and annotate its maps). Give the account the **teacher** role before adding it here — the form rejects accounts that do not have it (§1).
- **Delete** — confirms twice if students are enrolled; users and their maps are kept, but the maps lose their course assignment.

---

## 5. Usage & costs

Per-user token consumption and estimated spend for the current month.

**Set a budget** — enter a monthly USD budget on a user's row → **Set**. When a user reaches it, pipeline and Debate-A-Bot calls are blocked until next month. Empty = no limit.

> Costs are estimated from Anthropic's published pricing at deployment time. Verify against your actual invoice for billing.

---

## 6. Typical setup for a new course

1. **Create the course** — Courses → name → Create.
2. **Create or import students** — single form or Excel import (put the course name in the `course` column for automatic enrollment). Enrolment lets a student *hand a map in*; it does not hand anything in by itself.
3. **Assign a teacher** — set their role to **teacher** first, then Manage the course → add them by email. Both steps, every time (§1).
4. **Set budgets** (optional) — Usage section.
5. **Share credentials** — distribute emails/passwords; remind students to change their password after first login.
6. **Prepare materials** — as a teacher yourself you can author guided **templates** and share their links, and open maps for **annotation** (see the Teacher Guide).

---

## 7. What admins cannot do

- **Recover a deleted user or map** — deletions are permanent.
- **Read map contents from the admin panel** — review maps via the course page (Manage → open) or `/map/{id}`.
- **Access another user's Debate-A-Bot history** — conversations aren't persisted server-side.

---

*ArguMap — built with FastAPI, AntV X6, and Claude (Anthropic)*
