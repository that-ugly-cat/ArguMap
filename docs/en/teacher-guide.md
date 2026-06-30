# AutoMap — Teacher Guide

This guide covers the features available to teachers. Everything in the [User Guide](/docs/user-guide) also applies to you — this document focuses on course management and student oversight.

---

## 1. Your role

As a teacher you are associated with one or more courses by the administrator. You can:

- Use AutoMap yourself (pipeline, manual construction, viewer, Debate-A-Bot) — same as students.
- Access your course page to see enrolled students and their maps.
- Open any student's map in **read-only mode**.

You cannot create or delete users, create courses, or access the admin panel. Contact the administrator for those operations.

---

## 2. Accessing your course

Click **My Courses** in the top-right header of the dashboard. This opens a page listing all courses you are associated with as a teacher. Click **Manage** next to a course to open its detail page.

The course page shows:

- **Enrolled students** — list of all students in the course, with options to add or remove them (admin-only action).
- **Submitted maps** — all maps assigned to this course by any student, with an **Open →** link for each.

---

## 3. Reviewing student maps

Click **Open →** next to any student's map. The viewer opens in **read-only mode**:

- A banner at the top identifies whose map you are viewing: *👁 Reviewing [Name]'s map*.
- The **Save** button is hidden — you cannot modify the map.
- All viewer features are available for your own reading: chain highlight, edge details, node notes, reference browser, Debate-A-Bot.

### What to look for
- **Claim** (dark blue): is the thesis clearly stated and specific?
- **Inferential steps**: are the relations (`supports` / `attacks` / `qualifies`) assigned correctly?
- **Linked premises**: are co-dependent premises grouped (∧ joiner) rather than listed separately?
- **Validity and annotation**: has the student flagged weak steps with fallacy or bias labels? Are the labels accurate?
- **Node notes**: are bibliographic references included where expected?

---

## 4. Using AutoMap in a course

### Suggested workflow — automatic pipeline
1. **Prepare** — provide students with a 300–800 word argumentative text (policy document, editorial, bioethics case).
2. **Generate** — students run the automatic pipeline and receive a first-draft map.
3. **Refine** — students review the draft in the viewer, correct errors, adjust relations, add annotations.
4. **Submit** — students assign the map to your course (via the course dropdown in the dashboard or viewer toolbar).
5. **Review** — you open each map from the course page and assess it.

### Suggested workflow — manual construction
1. **Prepare** — assign a reading or present an argument in class.
2. **Construct** — students click **Manual construction** and build the map from scratch: add nodes by type (left panel), connect them in Connect mode (`c`), edit relations and annotations in the right panel.
3. **Submit** — students assign the map to your course.
4. **Review** — you open each map from the course page and assess it.

The manual workflow is better suited for in-class exercises where you want students to engage with argument structure directly, without a pipeline draft as a starting point. The two workflows can also be combined: generate a draft with the pipeline, then have students reconstruct or challenge it manually.

### Tips
- The pipeline is a starting point, not a final product. Encourage students to treat the draft critically.
- The **Debate-A-Bot** (Pro/Con) works well as a formative exercise: students argue against the AI to stress-test their map before submission.
- The **chain highlight** is useful during in-class discussion: click a node to show only that inferential chain on the projector.
- Students can export maps as PNG or SVG for inclusion in written assignments.

### Common student errors to watch for
| Error | What it looks like in the map |
|-------|-------------------------------|
| Missing warrant | Edge with no `rule` label, or `rule` = "not specified" |
| Convergent vs. linked confusion | Two premises attacking/supporting separately when they are actually co-dependent |
| Circular step | A node appears as both source and target in a chain |
| Overcrowded claim | Multiple distinct theses merged into one Claim node |

---

## 5. Contacting the administrator

For any of the following, reach out to your course administrator:

- Adding or removing students from the course
- Creating a new course or reassigning students
- Resetting a student's password
- Adjusting token budgets (if the course uses LLM budget limits)
- Importing students in bulk from an Excel file

---

*AutoMap — built with FastAPI, AntV X6, and Claude (Anthropic)*
