# AutoMap — Admin Guide

This guide covers everything available to administrators. Everything in the [User Guide](user-guide.md) and [Teacher Guide](teacher-guide.md) also applies to you.

---

## 1. Permission levels

AutoMap has five roles. Each role inherits the capabilities of the one below it.

| Role | Manual construction | Pipeline | Debate-A-Bot | Course overview | Admin panel |
|------|:-------------------:|:--------:|:------------:|:---------------:|:-----------:|
| **basic** | ✓ | — | — | — | — |
| **standard** | ✓ | ✓ | — | — | — |
| **full** | ✓ | ✓ | ✓ | — | — |
| **teacher** | ✓ | ✓ | ✓ | ✓ | — |
| **admin** | ✓ | ✓ | ✓ | ✓ | ✓ |

**When to use each role:**
- **basic** — participants who should only construct maps by hand (e.g. introductory exercises where the pipeline would short-circuit the learning goal).
- **standard** — typical students: manual construction + automated analysis.
- **full** — students who should also have access to Debate-A-Bot.
- **teacher** — course instructors: full student access + can view all maps submitted to their courses.
- **admin** — system administrators only.

---

## 2. Accessing the admin panel

Click **Admin** in the top-right header of the dashboard. The panel has three sections: **Users**, **Usage & costs**, and **Courses**.

---

## 3. Managing users

### Create a user
Fill in the form at the top of the Users section: name, email, temporary password, and role. Click **Add user**.

### Change role
Use the role dropdown directly in the users table. The change takes effect immediately.

### Activate / deactivate
Click **Deactivate** to suspend a user without deleting their data. Deactivated users cannot sign in. Click **Activate** to restore access.

### Reset a password
Enter a new password in the password field on the user's row and click **Set**.

### Delete a user
Click **Delete** on the user's row and confirm. This is irreversible — all maps owned by that user are deleted as well.

### Batch actions
Select multiple users with the checkboxes, then use the batch bar that appears: **Activate**, **Deactivate**, or **Delete**.

### Filter by course
Use the **Filter by course** dropdown above the table to show only users enrolled in a specific course.

### Import users from Excel
Click **Import from Excel**. The file must have the following columns:

| Column | Required | Notes |
|--------|----------|-------|
| `name` | Yes | — |
| `email` | Yes | Must be unique |
| `password` | No | Auto-generated if empty — shown once after import |
| `role` | No | Defaults to `standard` if omitted or unrecognised |
| `course` | No | Matched by name; user is enrolled if the course is found |

After import, a results panel shows: created users (with auto-generated passwords highlighted in amber), skipped emails (already exist), and row-level errors. Copy any auto-generated passwords before closing — they are not stored in plain text and cannot be retrieved later.

---

## 4. Managing courses

### Create a course
Enter the course name in the **Courses** section and click **Create**.

### Manage a course
Click **Manage** next to a course to open its detail page. From there you can:
- Add or remove **students** enrolled in the course.
- Add or remove **teachers** associated with the course (teachers see the course in their *My Courses* page and can review submitted maps).

### Delete a course
Click **Delete** next to the course. If students are enrolled, you will be asked to confirm twice. Deleting a course does not delete the users or their maps — maps lose their course assignment.

---

## 5. Usage & costs

The **Usage & costs** section shows per-user token consumption and estimated spend for the current month.

### Set a budget
Enter a monthly budget (in USD) in the budget field on a user's row and click **Set**. Once a user reaches their budget, pipeline and Debate-A-Bot calls are blocked until the next month. Leave the field empty for no limit.

> Token costs are estimated based on Anthropic's published pricing at the time of deployment. Verify against your actual Anthropic invoice for billing purposes.

---

## 6. Typical setup for a new course

1. **Create the course** — Courses section → enter name → Create.
2. **Create or import students** — use the single form or Excel import (with the course name in the `course` column for automatic enrollment).
3. **Assign a teacher** — open the course via Manage → add the teacher by email.
4. **Set budgets** (optional) — Usage section → set per-user monthly limits.
5. **Share credentials** — distribute emails and passwords to students. Remind them to change their password after first login (**Change password** in the dashboard header).

---

## 7. What admins cannot do

- **Recover a deleted user or map** — deletions are permanent.
- **See map contents from the admin panel** — map review happens via the course page (Manage → open a map) or by navigating directly to `/map/{id}`.
- **Access another user's Debate-A-Bot history** — conversations are not persisted server-side.

---

*AutoMap — built with FastAPI, AntV X6, and Claude (Anthropic)*
