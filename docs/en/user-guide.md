# AutoMap — User Guide

AutoMap helps you build and analyse argument maps. You can generate a map automatically from a text, or construct one by hand, then explore it interactively and debate it with an AI.

---

## 1. Signing in

Go to the AutoMap URL provided by your instructor. Enter your email and password. To change the interface language, use the language selector in the top-right corner (EN / IT / DE).

---

## 2. My Maps

After signing in you land on your personal dashboard.

- **Each card** shows a map title, creation date, and course (if assigned).
- **Open →** opens the map in the viewer.
- **Reasoning** shows the step-by-step reasoning the AI produced when the map was generated (only available for pipeline maps).
- **Text** shows the original source text (only available for pipeline maps).
- **✕** deletes the map (asks for confirmation).

### Filter by course
If you are enrolled in more than one course and have maps in multiple courses, a **Filter by course** dropdown appears above the list. Select a course to show only those maps.

### Move a map to a different course
Each map card has a small course dropdown on the right. Change it to reassign the map — no page reload needed.

---

## 3. Creating a map — Automatic pipeline

Click **Automatic analysis** on the dashboard.

1. Paste your text in the text area, **or** upload a `.docx` / `.txt` file.
2. Enter a title for the map.
3. If you are enrolled in multiple courses, select which course to assign the map to (or leave it unassigned).
4. Click **Analyse**.

The pipeline runs four steps: Claim → Nodes → Metaphysical commitments → Inferential steps — and streams its reasoning in real time. When finished, the map opens automatically in the viewer.

> The pipeline is geared towards argumentative text. Very short texts may produce sparse maps; very long texts may lose detail.

---

## 4. Creating a map — Manual

Click **Manual construction** on the dashboard. A blank canvas opens immediately. Build the map node by node using the left panel.

---

## 5. The viewer

### Toolbar (top)
| Button | Action |
|--------|--------|
| **Dashboard ←** | Return to My Maps |
| **Course** dropdown | Assign or change the course |
| **Save** | Save the current state |
| **Share** | Generate a read-only link |
| **Export** | Download as JSON, SVG, or PNG |
| **?** | Toggle the help panel |

### Panels
- **Left panel** — add nodes by type (Claim, Normative premise, Empirical premise, Metaphysical commitment, Intermediate conclusion). Also sets the edge router style (Metro / Normal / ER).
- **Right panel** — edit the selected node or edge: text content, notes, relation type, validity, fallacy, bias, inferential rule, strength. Also contains a searchable reference browser for inferential rules, fallacies, and biases.
- Collapse either panel with the **◄ / ►** tab on its inner edge.

### Interaction modes
| Mode | How to activate | What you can do |
|------|----------------|-----------------|
| **Select** (default) | Always active unless in Connect mode | Click to select, drag to reposition, `Delete` to remove |
| **Connect** | Press `c` or click the Connect button | Click a source node, then a target node to create an edge. `Esc` to exit. |

### Node types and colours
| Type                    | Colour      | Role                                |
| ----------------------- | ----------- | ----------------------------------- |
| Claim                   | Dark blue   | The main thesis                     |
| Normative premise       | Ochre       | Ethical or normative assumption     |
| Empirical premise       | Burgundy    | Factual or empirical claim          |
| Metaphysical commitment | Olive green | Background philosophical assumption |
| Intermediate conclusion | Mid blue    | A sub-conclusion in the chain       |

### Edge properties
- **Relation**: `supports`, `attacks`, or `qualifies`
- **Linked**: marks co-dependent premises (joint argument, not convergent)
- **Validity**: valid (solid line) / invalid (dashed) / not evaluated (faded)
- **Strength** (0–1): controls line thickness
- Edges with a bias or fallacy show an orange ⚠ chip

### Chain highlight
Click any node or edge to highlight only the inferential chain it belongs to — everything else fades. Click again to reset.

### Node IDs
Each node displays a small ID (e.g. `N1`, `E2`) in its bottom-right corner for easy reference.

---

## 6. Debate-A-Bot

Open a map in the viewer and click **Debate** in the toolbar.

- Choose **Pro** (the AI defends the argument) or **Con** (the AI challenges it).
- The AI opens with an analytical reading of the map, then responds to your messages.
- The conversation is not saved — it resets when you close the map.

> The bot stays focused on the argument map. It will not engage with off-topic questions.

---

## 7. Account

Click **Change password** in the top-right header of the dashboard. Enter your current password, your new password, and confirm it. If you forget your password, contact your instructor or course administrator.

---

*AutoMap — built with FastAPI, AntV X6, and Claude (Anthropic)*
