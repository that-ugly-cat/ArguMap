# ArguMap — User Guide

ArguMap helps you build and analyse **argument maps**: a claim, the premises that support it, the objections against it, and the inferential steps that connect them. You can generate a map automatically from a text, build one step by step with a guided walkthrough, or draw one by hand — then explore it, annotate it collaboratively, and debate it with an AI.

---

## 1. Signing in

Go to the ArguMap URL provided by your instructor. Enter your email and password. To change the interface language, use the selector in the top-right corner (EN / IT / DE).

---

## 2. My Maps

After signing in you land on your personal dashboard.

- **Each card** shows a map title, creation date, and course (if assigned).
- **Open →** opens the map in the viewer.
- **Reasoning** shows the step-by-step reasoning the AI produced when the map was generated (pipeline maps only).
- **Text** shows the original source text (pipeline maps only).
- **✕** deletes the map (asks for confirmation).

**Filter by course** — if you have maps in several courses, a dropdown above the list lets you show only one course's maps.
**Move a map** — each card has a small course dropdown on the right to reassign the map, no reload needed.

---

## 3. Three ways to build a map

The dashboard offers three cards:

- **⚡ Analyse a text** — paste a text (or upload a `.docx`, `.txt` or `.pdf`) and an LLM pipeline extracts the argument map automatically. It runs four steps (Claim → Nodes → Metaphysical commitments → Inferential steps) and streams its reasoning; when done the map opens in the viewer. Best on 300–800 words of argumentative text. PDFs are converted to clean text first (references and end matter are dropped) — this can take up to a minute, tracked by a progress bar.
- **🧭 Guided construction** — build the map step by step, starting from a claim (see §4).
- **✏️ Empty map** — start from a blank canvas and build entirely by hand (see §5).

You may also receive a **template link** from your instructor (see §6) — opening it drops you straight into guided construction with the claim already set.

---

## 4. Guided construction

Guided mode walks you down from the thesis, one inferential step at a time.

1. **State your claim** — the central thesis. (If you opened a template, the claim is already there; you may only need to fill in a highlighted blank.)
2. **Justify it** — for the highlighted node, answer *"What does this rest on?"*. Choose the kind of support and add it:
   - **Empirical premise** — a factual claim.
   - **Normative premise** — an ethical principle or value judgement.
   - **Intermediate conclusion** — a sub-conclusion that you'll then justify in turn.
   - **Metaphysical commitment** — a deep background assumption.
   - **Objection** — a counter-consideration *against* the node (added as a free node; you connect it where it belongs in free editing).
   Each type comes with a short explanation and an example.
3. **Co-dependency is automatic** — as soon as you add a *second* support to the same node, they are joined under a **∧ joiner** (they jointly support the target). Add more and they join the same ∧.
4. **Intermediate conclusions** queue up: when you have one to justify, a **"Done with this node →"** button moves you to it.
5. **Finish** — once the map holds at least one empirical *and* one normative premise, **Switch to free editing** lights up: click it to unlock the full editor (§5) and refine, reposition, or annotate.

---

## 5. The viewer

### Toolbar
| Button | Action |
|--------|--------|
| **Dashboard ←** | Return to My Maps |
| **Select / Connect / Guided / Annotate** | Interaction modes (below) |
| **Save** | Save the current state |
| **Recap** | Show all fallacies and biases in the map, in two tables |
| **Import JSON / Clear all** | Load a map file / empty the canvas |
| **Share / Export** | Read-only link · download as JSON, SVG, or PNG |
| **?** | Help panel |

### Panels
- **Left panel** — add nodes by type; set the edge router style (Metro / Normal / ER).
- **Right panel** — edit the selected node or edge (content, notes, relation, validity, fallacy, bias, inferential rule, strength) and browse a searchable **reference catalog** of inferential rules, fallacies, and biases.
- Collapse either panel with the **◄ / ►** tab on its inner edge.

### Interaction modes
| Mode | How | What you do |
|------|-----|-------------|
| **Select** (default) | — | Click to select, drag to reposition, `Delete` to remove |
| **Connect** | press `c` | Click a source node, then a target, to create an edge (`Esc` to exit). If either end is an **objection**, the edge defaults to `attacks`. |
| **Annotate** | toolbar button | Collaborative annotation layer (§7) |

### Node types
| Type | Colour | Role | Key |
|------|--------|------|:---:|
| Claim | Dark blue | The main thesis (one per map) | `t` |
| Normative premise | Ochre | Ethical / normative assumption | `n` |
| Empirical premise | Burgundy | Factual / empirical claim | `e` |
| Metaphysical commitment | Olive | Background philosophical assumption | `m` |
| Intermediate conclusion | Mid blue | A sub-conclusion in the chain | `i` |
| **Objection** | **Red** | A counter-consideration; connects via `attacks` | `o` |
| Co-premise joiner (∧) | Grey | Marks premises as jointly required | `j` |

### Edges
- **Relation**: `supports`, `attacks`, or `qualifies`.
- **Validity**: valid (solid) / invalid (dashed) / not evaluated (faded).
- **Strength** (0–1): line thickness.
- A bias or fallacy on a step shows an orange **⚠** chip.

### Other
- **Chain highlight** — click a node/edge to fade everything except its inferential chain; click again to reset.
- **Recap** — the toolbar Recap button lists every step carrying a fallacy or a bias, with the reason, in two tables.
- Each node shows its **ID** (e.g. `N1`, `O2`) in the bottom-right corner.

---

## 6. Opening a template link

Your instructor may send you a link like `.../t/12`. Opening it:

- creates your own copy of the map in your dashboard (one per template — reopening returns the same map);
- starts you in **guided construction** with the claim pre-filled (you may fill a blank in it);
- may offer **preset options** to pick from for a premise, and may already show some **given premises** (under a ∧) or **objections** on the map.

From there you build as in §4.

---

## 7. Annotating a shared map

Your instructor may open a map for annotation and share an `.../annotate/...` link. Opening it puts you in annotation mode (you can't move or edit the map, only annotate it):

- **Click a node or edge** to open its annotation thread.
- **Plausibility (1–5)** — rate how plausible you find it; the aggregate shows on the map as a small distribution bar.
- **Comment** — add a free-text remark.
- **Fallacy / Bias** — flag one, typing or picking a name from the catalog. It appears as a coloured chip on the map.
- You can delete your own annotations. Everyone's annotations refresh live every couple of seconds, and you'll also see the owner's edits to the map appear live.

---

## 8. Debate-A-Bot

Open a map and click **Debate**.

- Choose **Pro** (the AI defends the argument) or **Con** (the AI challenges it).
- The AI opens with an analytical reading, then responds to your messages.
- The conversation isn't saved — it resets when you close the map. The bot stays focused on the argument.

---

## 9. Account

Click **Change password** in the dashboard header: current password, new password, confirm. If you forget it, contact your instructor.

---

*ArguMap — built with FastAPI, AntV X6, and Claude (Anthropic)*
