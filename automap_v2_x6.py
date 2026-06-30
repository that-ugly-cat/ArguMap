"""
AutoMap v2 — X6-based interactive visualizer with editing.

This module has two distinct parts:

1. Python functions (top and bottom of file):
   - to_x6_data(): converts the abstract ArgumentMapV2 schema to X6 graph data.
   - generate_html_x6(): embeds that data into the HTML template and returns a
     self-contained, standalone HTML page with no external Python dependencies.

2. The HTML template (_HTML string, middle of file):
   A complete single-page application using AntV X6 (graph library) and Dagre
   (auto-layout). The template contains embedded CSS, HTML, and JavaScript.
   Backend values are injected via sentinel string substitution (see generate_html_x6).

Sentinel substitution: generate_html_x6() replaces tokens like AUTOMAP_NODES_JSON
with JSON-encoded data. These sentinels must not appear in user-generated content
(node text, titles, etc.). json.dumps() with ensure_ascii=False is used; the sentinels
are uppercase identifiers unlikely to collide with academic text.

Joiner nodes: 'linked_joiner' nodes represent co-premise groups (∧ symbol).
They are virtual — generated from steps with linked=True during render (to_x6_data,
_loadState in JS) and captured back to steps in _captureState in JS.
The joiner node ID on the graph is 'joiner_{step_id}'; positions are saved under
both the actual ID and the prefixed form to survive the save/reload cycle.
"""
from __future__ import annotations

import html as _html
import json
import math
from pathlib import Path
from typing import Optional, Union

from automap_v2_pipeline import ArgumentMapV2

# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

_NODE_WIDTH     = 220
_CHARS_PER_LINE = 33
_LINE_HEIGHT    = 16
_NODE_PADDING   = 24
_JOINER_SIZE    = 30

_SCHEMES_PATH = Path(__file__).parent / 'schemes.json'

import locales as _locales


def _get_x6_t(lang: str) -> dict:
    full = _locales.get_t(lang)
    return {k: v for k, v in full.items() if k.startswith(('x6_', 'nt_'))}


# --- DEAD CODE BELOW (kept for reference only, never executed in deploy) ---
_X6_TRANSLATIONS: dict[str, dict[str, str]] = {
    'en': {
        'x6_add_node': 'Add node', 'x6_edge_routing': 'Edge routing',
        'x6_nodes': 'Nodes', 'x6_edges': 'Edges',
        'x6_supports': 'Supports', 'x6_attacks': 'Attacks', 'x6_qualifies': 'Qualifies',
        'x6_invalid_style': 'Invalid', 'x6_thickness': 'Thickness = strength',
        'x6_pan_zoom': 'Drag canvas to pan · Scroll to zoom',
        'x6_edit_node': 'Edit node', 'x6_type': 'Type',
        'x6_content': 'Content', 'x6_notes': 'Notes',
        'x6_notes_ph': 'Shown on hover...',
        'x6_edit_edge': 'Edit edge', 'x6_relation': 'Relation',
        'x6_strength': 'Strength (thickness)',
        'x6_rule': 'Inferential rule', 'x6_rule_ph': 'e.g. modus ponens',
        'x6_rule_reason': 'Rule — reason (optional)',
        'x6_rule_reason_ph': 'How this step instantiates the rule...',
        'x6_validity': 'Validity',
        'x6_valid': 'Valid', 'x6_invalid_opt': 'Invalid', 'x6_not_evaluated': 'Not evaluated',
        'x6_bias_label': 'Bias — label', 'x6_bias_label_ph': 'e.g. availability heuristic',
        'x6_bias_reason': 'Bias — reason',
        'x6_bias_reason_ph': 'Why this step has this bias...',
        'x6_fallacy_label': 'Fallacy — label', 'x6_fallacy_label_ph': 'e.g. false dichotomy',
        'x6_fallacy_reason': 'Fallacy — reason',
        'x6_fallacy_reason_ph': 'Why this step has this fallacy...',
        'x6_update': 'Update', 'x6_delete': 'Delete',
        'x6_import_json': 'Import JSON', 'x6_clear_all': 'Clear all',
        'x6_select_mode': 'Select', 'x6_connect_mode': 'Connect',
        'x6_mode_hint': 'Click source → click target',
        'x6_help_title': 'AutoMap v2 — Reference',
        'x6_node_types_h': 'Node types', 'x6_edge_props_h': 'Edge properties',
        'x6_shortcuts_h': 'Keyboard shortcuts',
        'x6_prop_col': 'Property', 'x6_values_col': 'Values', 'x6_meaning_col': 'Meaning',
        'x6_search_ph': '🔍 Search…',
        'x6_new_node_prefix': 'New',
        'nt_claim': 'Claim (thesis)', 'nt_normative': 'Normative premise',
        'nt_empirical': 'Empirical premise', 'nt_metaphysical': 'Metaphysical commitment',
        'nt_intermediate': 'Intermediate conclusion', 'nt_joiner': 'Co-premise joiner (∧)',
        # help modal — node type descriptions
        'x6_nt_desc_claim':        'Central thesis. Exactly one per map; all other nodes support, attack, or qualify it.',
        'x6_nt_desc_normative':    'An ethical or normative claim: a principle, right, duty, or value judgment.',
        'x6_nt_desc_metaphysical': "Deep background assumption that grounds normative premises (Toulmin's backing).",
        'x6_nt_desc_empirical':    'A factual or empirical claim supported by evidence or data.',
        'x6_nt_desc_intermediate': 'A sub-conclusion within the inferential chain, derived from premises and feeding into the claim.',
        'x6_nt_desc_joiner':       'Links premises that are co-dependent: all connected premises are jointly required for the inference (linked argument, not convergent).',
        # help modal — edge properties table
        'x6_prop_relation':     'Relation',    'x6_prop_validity':  'Validity',
        'x6_prop_strength':     'Strength',    'x6_prop_rule':      'Rule',
        'x6_prop_bias':         'Bias',         'x6_prop_fallacy':   'Fallacy',
        'x6_rel_values':        'Supports / Attacks / Qualifies',
        'x6_val_values':        'Valid · Invalid · Not evaluated',
        'x6_free_text':         'Free text',
        'x6_meaning_relation':  'Whether the source strengthens, undermines, or constrains the target.',
        'x6_meaning_validity':  'Solid = valid; dashed = invalid or fallacious; faded = not yet assessed.',
        'x6_meaning_strength':  'Evidential weight of the inference. Controls edge thickness.',
        'x6_meaning_rule':      'Explicit inferential rule, e.g. modus ponens, specification. Shown as label on the edge.',
        'x6_meaning_bias':      'Potential bias in the inference. Shown as ⚠ chip on the edge and in the hover tooltip.',
        'x6_meaning_fallacy':   'Logical fallacy, e.g. appeal to authority. Shown as ⚠ chip on the edge and in the hover tooltip.',
        # help modal — keyboard shortcuts
        'x6_sc_add_nodes':      'Add nodes (canvas must be focused, not an input field)',
        'x6_sc_add_claim':      'Add Claim (Thesis)',
        'x6_sc_add_normative':  'Add Normative premise',
        'x6_sc_add_empirical':  'Add Empirical premise',
        'x6_sc_add_metaphysical':'Add Metaphysical commitment',
        'x6_sc_add_intermediate':'Add Intermediate conclusion',
        'x6_sc_add_joiner':     'Add Co-premise joiner (∧)',
        'x6_sc_canvas_mode':    'Canvas & mode',
        'x6_sc_toggle_connect': 'Toggle Connect mode',
        'x6_sc_exit_connect':   'Exit Connect mode / deselect',
        'x6_sc_general':        'General',
        'x6_sc_undo':           'Undo',           'x6_sc_redo':    'Redo',
        'x6_sc_delete_sel':     'Remove selected node or edge',
        'x6_sc_zoom':           'Zoom in / out',  'x6_sc_pan':     'Pan the view',
    },
    'it': {
        'x6_add_node': 'Aggiungi nodo', 'x6_edge_routing': 'Stile archi',
        'x6_nodes': 'Nodi', 'x6_edges': 'Archi',
        'x6_supports': 'Sostiene', 'x6_attacks': 'Attacca', 'x6_qualifies': 'Qualifica',
        'x6_invalid_style': 'Non valido', 'x6_thickness': 'Spessore = forza',
        'x6_pan_zoom': 'Trascina per spostare · Scorri per ingrandire',
        'x6_edit_node': 'Modifica nodo', 'x6_type': 'Tipo',
        'x6_content': 'Contenuto', 'x6_notes': 'Note',
        'x6_notes_ph': 'Mostrato al passaggio del cursore...',
        'x6_edit_edge': 'Modifica arco', 'x6_relation': 'Relazione',
        'x6_strength': 'Forza (spessore)',
        'x6_rule': 'Regola inferenziale', 'x6_rule_ph': 'es. modus ponens',
        'x6_rule_reason': 'Regola — motivazione (opzionale)',
        'x6_rule_reason_ph': 'Come questo passo istanzia la regola...',
        'x6_validity': 'Validità',
        'x6_valid': 'Valido', 'x6_invalid_opt': 'Non valido', 'x6_not_evaluated': 'Non valutato',
        'x6_bias_label': 'Bias — etichetta', 'x6_bias_label_ph': 'es. euristica della disponibilità',
        'x6_bias_reason': 'Bias — motivazione',
        'x6_bias_reason_ph': 'Perché questo passo ha questo bias...',
        'x6_fallacy_label': 'Fallacia — etichetta', 'x6_fallacy_label_ph': 'es. falso dilemma',
        'x6_fallacy_reason': 'Fallacia — motivazione',
        'x6_fallacy_reason_ph': 'Perché questo passo ha questa fallacia...',
        'x6_update': 'Aggiorna', 'x6_delete': 'Elimina',
        'x6_import_json': 'Importa JSON', 'x6_clear_all': 'Cancella tutto',
        'x6_select_mode': 'Seleziona', 'x6_connect_mode': 'Connetti',
        'x6_mode_hint': 'Clicca sorgente → clicca destinazione',
        'x6_help_title': 'AutoMap v2 — Riferimento',
        'x6_node_types_h': 'Tipi di nodo', 'x6_edge_props_h': 'Proprietà degli archi',
        'x6_shortcuts_h': 'Scorciatoie da tastiera',
        'x6_prop_col': 'Proprietà', 'x6_values_col': 'Valori', 'x6_meaning_col': 'Significato',
        'x6_search_ph': '🔍 Cerca…',
        'x6_new_node_prefix': 'Nuovo',
        'nt_claim': 'Claim (tesi)', 'nt_normative': 'Premessa normativa',
        'nt_empirical': 'Premessa empirica', 'nt_metaphysical': 'Impegno metafisico',
        'nt_intermediate': 'Conclusione intermedia', 'nt_joiner': 'Connettore co-premesse (∧)',
        # help modal — descrizioni tipi di nodo
        'x6_nt_desc_claim':        'Tesi centrale. Esattamente una per mappa; tutti gli altri nodi la sostengono, attaccano o qualificano.',
        'x6_nt_desc_normative':    "Un'affermazione etica o normativa: un principio, un diritto, un dovere o un giudizio di valore.",
        'x6_nt_desc_metaphysical': "Assunzione di sfondo profonda che fonda le premesse normative (backing di Toulmin).",
        'x6_nt_desc_empirical':    "Un'affermazione fattuale o empirica supportata da prove o dati.",
        'x6_nt_desc_intermediate': 'Una sotto-conclusione nella catena inferenziale, derivata dalle premesse e che confluisce nel claim.',
        'x6_nt_desc_joiner':       "Collega premesse co-dipendenti: tutte le premesse connesse sono congiuntamente necessarie per l'inferenza (argomento linked, non convergente).",
        # help modal — tabella proprietà archi
        'x6_prop_relation':     'Relazione',   'x6_prop_validity':  'Validità',
        'x6_prop_strength':     'Forza',        'x6_prop_rule':      'Regola',
        'x6_prop_bias':         'Bias',          'x6_prop_fallacy':   'Fallacia',
        'x6_rel_values':        'Sostiene / Attacca / Qualifica',
        'x6_val_values':        'Valido · Non valido · Non valutato',
        'x6_free_text':         'Testo libero',
        'x6_meaning_relation':  'Se la sorgente rafforza, indebolisce o vincola il nodo target.',
        'x6_meaning_validity':  'Linea intera = valido; tratteggiata = non valido o fallace; semi-trasparente = non ancora valutato.',
        'x6_meaning_strength':  "Peso inferenziale dell'arco. Controlla lo spessore.",
        'x6_meaning_rule':      "Regola inferenziale esplicita, es. modus ponens, specification. Mostrata come etichetta sull'arco.",
        'x6_meaning_bias':      "Potenziale bias nell'inferenza. Mostrato come chip ⚠ sull'arco e nel tooltip al passaggio del cursore.",
        'x6_meaning_fallacy':   "Fallacia logica, es. appeal to authority. Mostrata come chip ⚠ sull'arco e nel tooltip al passaggio del cursore.",
        # help modal — scorciatoie da tastiera
        'x6_sc_add_nodes':      'Aggiungi nodi (la canvas deve essere attiva, non un campo di testo)',
        'x6_sc_add_claim':      'Aggiungi Claim (Tesi)',
        'x6_sc_add_normative':  'Aggiungi Premessa normativa',
        'x6_sc_add_empirical':  'Aggiungi Premessa empirica',
        'x6_sc_add_metaphysical':'Aggiungi Impegno metafisico',
        'x6_sc_add_intermediate':'Aggiungi Conclusione intermedia',
        'x6_sc_add_joiner':     'Aggiungi Connettore di co-premesse (∧)',
        'x6_sc_canvas_mode':    'Canvas e modalità',
        'x6_sc_toggle_connect': 'Attiva/disattiva modalità Connetti',
        'x6_sc_exit_connect':   'Esci dalla modalità Connetti / deseleziona',
        'x6_sc_general':        'Generale',
        'x6_sc_undo':           'Annulla',        'x6_sc_redo':    'Ripeti',
        'x6_sc_delete_sel':     'Rimuovi nodo o arco selezionato',
        'x6_sc_zoom':           'Zoom in / out',  'x6_sc_pan':     'Sposta la vista',
    },
}
# --- END DEAD CODE ---


def _wrap_text(text: str) -> str:
    words = text.split()
    lines, current, cur_len = [], [], 0
    for word in words:
        if current and cur_len + 1 + len(word) > _CHARS_PER_LINE:
            lines.append(' '.join(current))
            current, cur_len = [word], len(word)
        else:
            current.append(word)
            cur_len += (1 if len(current) > 1 else 0) + len(word)
    if current:
        lines.append(' '.join(current))
    return '\n'.join(lines)


def _height(wrapped: str) -> int:
    n = wrapped.count('\n') + 1
    return max(55, n * _LINE_HEIGHT + _NODE_PADDING)


def _validity(v) -> str:
    if v is True:  return "valid"
    if v is False: return "invalid"
    return "unknown"


def to_x6_data(argmap: Union[ArgumentMapV2, dict]) -> dict:
    """Convert ArgumentMapV2 to {nodes: [...], edges: [...]} for X6."""
    if isinstance(argmap, ArgumentMapV2):
        argmap = argmap.model_dump()

    nodes, edges = [], []

    for node in argmap["nodes"]:
        label = _wrap_text(node["content"])
        nodes.append({
            "id":      node["id"],
            "type":    node["type"],
            "content": node["content"],
            "label":   label,
            "notes":   node.get("notes") or "",
            "width":   _NODE_WIDTH,
            "height":  _height(label),
        })

    for step in argmap["steps"]:
        ann = step.get("annotation") or {}
        edge_base = {
            "step_id":        step["id"],
            "relation":       step.get("relation", "supports"),
            "rule":           step.get("rule") or "",
            "rule_reason":    step.get("rule_reason") or "",
            "validity":       _validity(ann.get("valid")),
            "bias_label":     ann.get("bias_label") or "",
            "bias_reason":    ann.get("bias_reason") or "",
            "fallacy_label":  ann.get("fallacy_label") or "",
            "fallacy_reason": ann.get("fallacy_reason") or "",
            "strength":       step.get("strength", 0.5),
        }

        # Linked steps (co-premise / ∧ joiner): expand into a virtual joiner node
        # with N incoming edges (one per source) and one outgoing edge to the target.
        # Only expand in to_x6_data when sources > 1; partial joiners (0-1 sources)
        # are handled exclusively in the JS _loadState to avoid rendering dangling nodes.
        if step.get("linked") and len(step["sources"]) > 1:
            joiner_id = f"joiner_{step['id']}"
            nodes.append({
                "id":      joiner_id,
                "type":    "linked_joiner",
                "content": "Both premises required",
                "notes":   "",
                "width":   _JOINER_SIZE,
                "height":  _JOINER_SIZE,
            })
            for i, src in enumerate(step["sources"]):
                edges.append({"id": f"{step['id']}_in_{i}", "source": src,
                               "target": joiner_id, **edge_base,
                               "rule": "", "bias_label": "", "fallacy_label": "",
                               "bias_reason": "", "fallacy_reason": ""})
            edges.append({"id": f"{step['id']}_out", "source": joiner_id,
                           "target": step["target"], **edge_base})
        else:
            for i, src in enumerate(step["sources"]):
                edges.append({"id": f"{step['id']}_{i}", "source": src,
                               "target": step["target"], **edge_base})

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="AUTOMAP_LANG">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AUTOMAP_TITLE — ArguMap</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { width: 100%; height: 100%; overflow: hidden;
                 font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }

    /* --- Fixed shell --- */
    #toolbar {
      position: fixed; top: 0; left: 0; right: 0; height: 44px; z-index: 200;
      background: white; border-bottom: 1px solid #dde1e7;
      padding: 0 14px; display: flex; align-items: center; gap: 10px;
      box-shadow: 0 1px 3px rgba(0,0,0,.08);
    }
    #add-panel {
      position: fixed; top: 44px; left: 0; width: 172px; bottom: 0; z-index: 100;
      background: #f7fafc; border-right: 1px solid #dde1e7;
      padding: 12px 10px; overflow-y: auto;
    }
    #graph-container {
      position: fixed; top: 44px; left: 172px; right: 256px; bottom: 0; z-index: 1;
      background: #f0f2f5;
    }
    #edit-panel {
      position: fixed; top: 44px; right: 0; width: 256px; bottom: 0; z-index: 100;
      background: white; border-left: 1px solid #dde1e7;
      padding: 14px 12px; overflow-y: auto;
    }
    #panel-resize-handle {
      position: absolute; left: 0; top: 0; bottom: 0; width: 5px; cursor: col-resize;
      z-index: 10; background: transparent; transition: background .15s;
    }
    #panel-resize-handle:hover, #panel-resize-handle.dragging { background: #63b3ed; }

    /* --- Toolbar --- */
    #map-title {
      font-size: 13px; font-weight: 600; color: #1a202c; flex: 1; min-width: 60px;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      border-radius: 4px; padding: 2px 5px; cursor: text; outline: none;
    }
    #map-title:focus {
      background: #f7fafc; box-shadow: 0 0 0 2px #63b3ed;
      white-space: normal; overflow: visible; text-overflow: clip;
    }
    #map-title:empty::before { content: 'Untitled map'; color: #a0aec0; font-style: italic; }
    .mode-btn {
      padding: 4px 10px; border-radius: 5px; border: 1px solid #cbd5e0;
      background: white; font-size: 12px; cursor: pointer; color: #4a5568;
    }
    .mode-btn.active { background: #2980b9; color: white; border-color: #2980b9; }
    .tb-btn {
      padding: 4px 10px; border-radius: 5px; border: 1px solid #cbd5e0;
      background: #2d3748; color: white; font-size: 12px; cursor: pointer; white-space: nowrap;
    }
    .tb-btn:hover { background: #1a202c; }
    .tb-btn:disabled { opacity: 0.35; cursor: not-allowed; }
    .tb-btn:disabled:hover { background: #2d3748; }
    .tb-btn.tb-help {
      background: white; color: #4a5568; font-weight: 700;
    }
    .tb-btn.tb-help:hover { background: #edf2f7; }
    .panel-toggle {
      position: fixed; top: 50%; transform: translateY(-50%);
      width: 14px; height: 44px; z-index: 150; cursor: pointer;
      background: #f7fafc; border: 1px solid #dde1e7;
      display: flex; align-items: center; justify-content: center;
      font-size: 9px; color: #718096; user-select: none;
      transition: background .12s, color .12s;
    }
    .panel-toggle:hover { background: #edf2f7; color: #2d3748; }
    #left-panel-toggle  { left: 172px; border-left: none;  border-radius: 0 5px 5px 0; }
    #right-panel-toggle { right: 256px; border-right: none; border-radius: 5px 0 0 5px; }
    #mode-hint {
      font-size: 11px; color: #e67e22; font-style: italic; display: none;
      padding: 3px 8px; background: #fef3cd; border-radius: 4px;
    }

    /* --- Guided construction --- */
    #guided-indicator {
      display: none;
      font-size: 12px; font-weight: 600; color: #2980b9;
      padding: 3px 10px; background: #ebf5fb; border-radius: 4px;
    }
    #guided-panel {
      position: fixed; top: 44px; left: 0; width: 340px; bottom: 0; z-index: 130;
      background: #f7fafc; border-right: 1px solid #dde1e7;
      padding: 16px 16px 28px; overflow-y: auto; display: none;
    }
    body.guided #guided-panel { display: block; }
    body.guided #add-panel,
    body.guided #left-panel-toggle,
    body.guided #edit-panel,
    body.guided #right-panel-toggle,
    body.guided #btn-select,
    body.guided #btn-connect,
    body.guided #btn-guided { display: none; }
    body.guided #graph-container { left: 340px; right: 0; }
    body.guided #guided-indicator { display: inline-block; }
    #guided-panel h2 { font-size: 15px; color: #1a202c; margin-bottom: 4px; }
    #guided-panel .g-sub { font-size: 11px; color: #718096; margin-bottom: 14px; line-height: 1.5; }
    .g-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
    .g-card h3 { font-size: 12px; color: #2d3748; margin-bottom: 6px; }
    .g-target { background: #ebf5fb; border: 1px solid #bee3f8; border-radius: 6px; padding: 8px 10px; margin-bottom: 12px; }
    .g-target-lbl { font-size: 9px; text-transform: uppercase; letter-spacing: .05em; color: #2980b9; font-weight: 700; margin-bottom: 2px; }
    .g-target-txt { font-size: 12px; color: #1a202c; line-height: 1.4; }
    .g-q { font-size: 12px; font-weight: 600; color: #2d3748; margin: 4px 0 8px; }
    .g-help { font-size: 11px; color: #718096; line-height: 1.5; margin-bottom: 10px; }
    .g-type-btn { display: block; width: 100%; text-align: left; border: none; border-radius: 6px;
      padding: 8px 10px; margin-bottom: 6px; cursor: pointer; color: white; font-size: 11px; font-weight: 600; }
    .g-type-btn:hover { filter: brightness(1.12); }
    .g-type-btn.sel { box-shadow: 0 0 0 2px #1a202c; }
    .g-type-btn[data-type="empirical_premise"]       { background: #630541; }
    .g-type-btn[data-type="normative_premise"]       { background: #a88614; }
    .g-type-btn[data-type="intermediate_conclusion"] { background: #1683ab; }
    .g-type-btn[data-type="metaphysical_commitment"] { background: #a3b51b; }
    .g-type-desc { font-size: 10px; color: #4a5568; line-height: 1.45; margin: -2px 0 10px; padding: 0 2px; }
    .g-type-desc .g-ex { color: #718096; font-style: italic; display: block; margin-top: 3px; }
    .g-chips { display: flex; gap: 8px; margin-bottom: 12px; }
    .g-chip { flex: 1; font-size: 10px; text-align: center; padding: 5px 4px; border-radius: 5px;
      border: 1px solid #e2e8f0; background: white; color: #a0aec0; }
    .g-chip.on { border-color: #38a169; background: #f0fff4; color: #276749; font-weight: 600; }
    .g-added { list-style: none; margin: 6px 0 0; padding: 0; }
    .g-added li { font-size: 11px; color: #2d3748; padding: 4px 0; border-top: 1px solid #edf2f7;
      display: flex; align-items: center; gap: 6px; }
    .g-dot { width: 9px; height: 9px; border-radius: 2px; flex-shrink: 0; }
    .g-btn { display: block; width: 100%; padding: 9px; border-radius: 6px; border: none;
      font-size: 12px; font-weight: 600; cursor: pointer; margin-top: 8px; }
    .g-btn-primary { background: #2980b9; color: white; }
    .g-btn-primary:hover { background: #2471a3; }
    .g-btn-ghost { background: #edf2f7; color: #4a5568; }
    .g-btn-ghost:hover { background: #e2e8f0; }
    .g-btn-unlock { background: #38a169; color: white; }
    .g-btn-unlock:hover { background: #2f855a; }
    .g-btn-unlock.muted { background: #cbd5e0; color: #4a5568; }
    .g-btn:disabled { opacity: .45; cursor: not-allowed; }
    #guided-panel textarea, #guided-panel input[type="text"] { width: 100%; padding: 7px 9px;
      border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; font-family: inherit;
      background: white; margin-bottom: 6px; resize: vertical; box-sizing: border-box; }
    #guided-panel textarea:focus, #guided-panel input[type="text"]:focus { outline: none; border-color: #63b3ed; }
    .g-fill-preview { font-size: 12px; color: #2d3748; line-height: 1.5; margin-bottom: 10px;
      padding: 8px 10px; background: #f7fafc; border-radius: 6px; }
    .g-blank { background: #fef3cd; color: #975a16; font-weight: 700; padding: 0 4px;
      border-radius: 3px; border: 1px dashed #d69e2e; }
    .g-queue { font-size: 11px; color: #718096; margin-top: 12px; }
    .g-link-row { display: flex; gap: 8px; }
    .g-link-row .g-btn { margin-top: 0; }

    /* --- Add panel --- */
    #add-panel h3 { font-size: 10px; font-weight: 700; color: #718096;
                    text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
    .type-btn {
      display: block; width: 100%; padding: 7px 10px; margin-bottom: 5px;
      border-radius: 6px; border: none; text-align: left; font-size: 11px;
      font-weight: 500; cursor: pointer; color: white;
    }
    .type-btn:hover { filter: brightness(1.12); }
    .type-btn[data-type="claim"]                   { background: #0a3c8a; }
    .type-btn[data-type="normative_premise"]       { background: #a88614; }
    .type-btn[data-type="empirical_premise"]        { background: #630541; }
    .type-btn[data-type="metaphysical_commitment"]  { background: #a3b51b; }
    .type-btn[data-type="intermediate_conclusion"]  { background: #1683ab; }
    .type-btn[data-type="linked_joiner"]            { background: #4a5568; }
    .add-sep { border: none; border-top: 1px solid #dde1e7; margin: 8px 0; }
    .tb-btn.tb-danger { background: #e74c3c; border-color: #e74c3c; }
    .tb-btn.tb-danger:hover { background: #c0392b; }

    /* --- Edit panel --- */
    #edit-panel h3 { font-size: 12px; font-weight: 700; color: #2d3748; margin-bottom: 10px; }
    .field-label { font-size: 10px; font-weight: 700; text-transform: uppercase;
                   letter-spacing: .05em; color: #718096; margin-bottom: 3px;
                   margin-top: 8px; display: block; }
    .field-label:first-child { margin-top: 0; }
    select, input[type="text"], textarea {
      width: 100%; padding: 6px 8px; border: 1px solid #e2e8f0;
      border-radius: 5px; font-size: 12px; color: #2d3748;
      font-family: inherit; background: #f7fafc;
    }
    select:focus, input:focus, textarea:focus {
      outline: none; border-color: #63b3ed; background: white;
    }
    textarea { resize: vertical; }
    /* Strength slider */
    .slider-row { display: flex; align-items: center; gap: 8px; }
    .slider-row input[type="range"] {
      flex: 1; padding: 0; border: none; background: none;
      accent-color: #2980b9; cursor: pointer;
    }
    .slider-val { font-size: 11px; color: #4a5568; min-width: 28px; text-align: right; }
    /* Buttons */
    .action-row { display: flex; gap: 6px; margin-top: 10px; }
    .btn-primary {
      flex: 1; padding: 7px; border-radius: 5px; border: none;
      background: #2980b9; color: white; font-size: 12px; cursor: pointer;
    }
    .btn-primary:hover { background: #2471a3; }
    .btn-danger {
      padding: 7px 10px; border-radius: 5px; border: none;
      background: #e74c3c; color: white; font-size: 12px; cursor: pointer;
    }
    .btn-danger:hover { background: #c0392b; }

    /* --- Reference browser --- */
    #ref-browser { font-size: 12px; }
    #ref-search {
      width: 100%; padding: 6px 8px; border: 1px solid #e2e8f0;
      border-radius: 5px; font-size: 12px; color: #2d3748;
      font-family: inherit; background: #f7fafc; margin-bottom: 10px;
    }
    #ref-search:focus { outline: none; border-color: #63b3ed; background: white; }
    .ref-section { margin-bottom: 5px; }
    .ref-section-hd {
      display: flex; align-items: center; gap: 5px; padding: 5px 7px;
      border-radius: 5px; cursor: pointer; user-select: none;
      font-size: 10px; font-weight: 700; text-transform: uppercase;
      letter-spacing: .05em; color: #4a5568; background: #edf2f7;
    }
    .ref-section-hd:hover { background: #e2e8f0; }
    .ref-chev { font-size: 8px; display: inline-block; transition: transform .15s; }
    .ref-chev.closed { transform: rotate(-90deg); }
    .ref-count { margin-left: auto; font-size: 10px; color: #a0aec0; font-weight: 400;
                 text-transform: none; letter-spacing: 0; }
    .ref-body { display: none; }
    .ref-body.open { display: block; }
    .ref-item { border-bottom: 1px solid #f0f2f5; }
    .ref-item-hd {
      padding: 5px 6px; cursor: pointer; font-size: 11px; color: #2d3748;
      border-radius: 3px; line-height: 1.4;
    }
    .ref-item-hd:hover { background: #f7fafc; color: #2980b9; }
    .ref-item-detail {
      display: none; padding: 2px 6px 8px 6px; font-size: 11px;
      line-height: 1.55; color: #4a5568;
    }
    .ref-item-detail.open { display: block; }
    .ref-item-desc { margin-bottom: 5px; }
    .ref-item-ex {
      color: #718096; font-style: italic; font-size: 11px; line-height: 1.5;
      padding-left: 8px; border-left: 2px solid #e2e8f0;
    }
    .ref-item-ex::before { content: "e.g. — "; font-weight: 600;
                            font-style: normal; color: #a0aec0; }
    .ref-item-src {
      color: #a0aec0; font-style: normal; font-size: 10px; line-height: 1.4;
      margin-top: 5px; padding-left: 8px;
    }
    .ref-item-src::before { content: "src: "; font-weight: 600; }
    .ref-item-src a { color: #2980b9; text-decoration: none; }
    .ref-item-src a:hover { text-decoration: underline; }
    .ref-no-results { font-size: 11px; color: #a0aec0; padding: 8px 6px;
                      font-style: italic; display: none; }
    .ref-subfam-hd {
      display: flex; align-items: center; gap: 5px; padding: 4px 7px 4px 12px;
      cursor: pointer; user-select: none; font-size: 9px; font-weight: 700;
      text-transform: uppercase; letter-spacing: .05em; color: #718096;
      border-bottom: 1px solid #f0f2f5;
    }
    .ref-subfam-hd:hover { background: #f7fafc; }
    .ref-subfam-body { display: none; }
    .ref-subfam-body.open { display: block; }

    /* --- Legend --- */
    #legend {
      position: absolute; bottom: 12px; left: 12px; z-index: 10;
      background: white; padding: 10px 12px; border-radius: 7px;
      box-shadow: 0 2px 8px rgba(0,0,0,.12); font-size: 10px; color: #4a5568;
      pointer-events: none;
    }
    #legend h4 { font-size: 10px; font-weight: 700; margin-bottom: 5px; color: #718096; }
    .l-row { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
    .l-dot  { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
    .l-line { width: 18px; height: 2px; flex-shrink: 0; border-radius: 1px; }
    .l-sep  { border: none; border-top: 1px solid #edf2f7; margin: 5px 0; }

    /* --- Claim ripple --- */
    @keyframes claim-pulse {
      0%   { opacity: 0.6; transform: scale(1);    }
      70%  { opacity: 0;   transform: scale(1.18); }
      100% { opacity: 0;   transform: scale(1.18); }
    }
    .claim-ring {
      fill: none; stroke: #0a3c8a; stroke-width: 2.5; pointer-events: none;
      transform-box: fill-box; transform-origin: 50% 50%;
      animation: claim-pulse 2.2s ease-out infinite;
    }

    /* --- Tooltip --- */
    #tooltip {
      position: fixed; display: none; z-index: 400; pointer-events: none;
      background: #2d3748; color: #e2e8f0; padding: 8px 12px;
      border-radius: 6px; font-size: 11px; max-width: 280px; line-height: 1.6;
      box-shadow: 0 3px 10px rgba(0,0,0,.3);
    }
    #tooltip .tt-label { font-size: 9px; font-weight: 700; text-transform: uppercase;
                         letter-spacing: .06em; color: #a0aec0; margin-bottom: 3px; }
    #tooltip .tt-warn  { color: #fbd38d; }
    #tooltip .tt-err   { color: #fc8181; }

    /* --- Help modal --- */
    #help-overlay {
      display: none; position: fixed; inset: 0; z-index: 500;
      background: rgba(0,0,0,.45); align-items: center; justify-content: center;
    }
    #help-overlay.open { display: flex; }
    #help-modal {
      background: white; border-radius: 10px; padding: 24px 28px;
      max-width: 560px; width: 90%; max-height: 80vh; overflow-y: auto;
      box-shadow: 0 8px 32px rgba(0,0,0,.25);
    }
    #help-modal h2 { font-size: 16px; font-weight: 700; color: #1a202c; margin-bottom: 16px; }
    #help-modal h3 { font-size: 11px; font-weight: 700; text-transform: uppercase;
                     letter-spacing: .05em; color: #718096; margin: 16px 0 8px; }
    #help-modal .h-row { display: flex; gap: 10px; align-items: flex-start;
                         margin-bottom: 8px; font-size: 12px; line-height: 1.6; color: #2d3748; }
    #help-modal .h-dot { width: 12px; height: 12px; border-radius: 2px;
                         flex-shrink: 0; margin-top: 3px; }
    #help-modal .h-key { font-weight: 700; }
    #help-modal table { width: 100%; border-collapse: collapse; font-size: 12px; color: #2d3748; }
    #help-modal td, #help-modal th { padding: 5px 8px; border-bottom: 1px solid #edf2f7;
                                      text-align: left; vertical-align: top; }
    #help-modal kbd { display: inline-block; padding: 1px 5px; background: #edf2f7;
      border: 1px solid #cbd5e0; border-radius: 3px; font-size: 10px; font-family: monospace;
      color: #2d3748; margin-left: 4px; vertical-align: middle; }
    #help-modal th { font-weight: 700; color: #718096; font-size: 10px;
                     text-transform: uppercase; letter-spacing: .04em; }
    .close-btn {
      float: right; background: none; border: none; font-size: 20px; line-height: 1;
      cursor: pointer; color: #718096; margin-top: -4px;
    }
    .close-btn:hover { color: #2d3748; }

    /* --- Toolbar select --- */
    .tb-select {
      padding: 4px 6px; border-radius: 5px; border: 1px solid #cbd5e0;
      background: white; font-size: 12px; color: #4a5568; cursor: pointer;
      height: 28px; width: auto;
    }
    .tb-select:focus { outline: none; border-color: #63b3ed; }
  </style>
</head>
<body>

<div id="toolbar">
  <h1 id="map-title" contenteditable="true" spellcheck="false">AUTOMAP_TITLE</h1>
  <div style="display:flex;gap:4px;flex-shrink:0">
    <button class="tb-btn" id="btn-undo" onclick="undo()" disabled title="Undo (Ctrl+Z)">&#x21A9;</button>
    <button class="tb-btn" id="btn-redo" onclick="redo()" disabled title="Redo (Ctrl+Y)">&#x21AA;</button>
  </div>
  <div style="display:flex;gap:4px;flex-shrink:0" id="mode-group">
    <button class="mode-btn active" id="btn-select"  onclick="setMode('select')" data-i18n="x6_select_mode">Select</button>
    <button class="mode-btn"        id="btn-connect" onclick="setMode('connect')" data-i18n="x6_connect_mode">Connect</button>
    <button class="mode-btn"        id="btn-guided"  onclick="startGuided()" data-i18n="x6_guided_btn">Guided</button>
  </div>
  <span id="guided-indicator" data-i18n="x6_guided_title">Guided construction</span>
  <span id="mode-hint" data-i18n="x6_mode_hint">Click source &#x2192; click target</span>
  <div style="display:flex;gap:4px;flex-shrink:0;margin-left:auto">
    <button class="tb-btn" onclick="importJSON()" data-i18n="x6_import_json">Import JSON</button>
    <button class="tb-btn tb-danger" onclick="clearAll()" data-i18n="x6_clear_all">Clear all</button>
    <button class="tb-btn tb-help" onclick="openHelp()">?</button>
  </div>
</div>

<div id="add-panel">
  <h3 data-i18n="x6_add_node">Add node</h3>
  <button class="type-btn" data-type="claim" onclick="addNode('claim')" data-i18n="nt_claim">Claim (thesis)</button>
  <hr class="add-sep">
  <button class="type-btn" data-type="metaphysical_commitment" onclick="addNode('metaphysical_commitment')" data-i18n="nt_metaphysical">Metaphysical commitment</button>
  <button class="type-btn" data-type="normative_premise"       onclick="addNode('normative_premise')" data-i18n="nt_normative">Normative premise</button>
  <button class="type-btn" data-type="empirical_premise"       onclick="addNode('empirical_premise')" data-i18n="nt_empirical">Empirical premise</button>
  <button class="type-btn" data-type="intermediate_conclusion" onclick="addNode('intermediate_conclusion')" data-i18n="nt_intermediate">Intermediate conclusion</button>
  <button class="type-btn" data-type="linked_joiner"           onclick="addNode('linked_joiner')" data-i18n="nt_joiner">Co-premise joiner (∧)</button>
  <hr class="add-sep">
  <h3 data-i18n="x6_edge_routing">Edge routing</h3>
  <select class="tb-select" style="width:100%;margin-top:4px" title="Edge routing" onchange="setRouter(this.value)">
    <option value="metro">Metro</option>
    <option value="normal">Normal</option>
    <option value="er">ER</option>
  </select>
</div>
<div id="left-panel-toggle" class="panel-toggle" onclick="toggleLeftPanel()" title="Toggle left panel">&#x25C4;</div>

<div id="guided-panel">
  <h2 data-i18n="x6_guided_title">Guided construction</h2>
  <div class="g-sub" data-i18n="x6_guided_subtitle">Build your argument one inferential step at a time.</div>
  <div id="guided-body"></div>
</div>

<div id="graph-container">
  <div id="legend">
    <h4 data-i18n="x6_nodes">Nodes</h4>
    <div class="l-row"><div class="l-dot" style="background:#0a3c8a"></div><span data-i18n="nt_claim">Claim (thesis)</span></div>
    <div class="l-row"><div class="l-dot" style="background:#a88614"></div><span data-i18n="nt_normative">Normative premise</span></div>
    <div class="l-row"><div class="l-dot" style="background:#630541"></div><span data-i18n="nt_empirical">Empirical premise</span></div>
    <div class="l-row"><div class="l-dot" style="background:#a3b51b"></div><span data-i18n="nt_metaphysical">Metaphysical commitment</span></div>
    <div class="l-row"><div class="l-dot" style="background:#1683ab"></div><span data-i18n="nt_intermediate">Intermediate conclusion</span></div>
    <div class="l-row"><div class="l-dot" style="background:#4a5568;border-radius:50%"></div><span data-i18n="nt_joiner">Co-premise joiner (∧)</span></div>
    <hr class="l-sep">
    <h4 data-i18n="x6_edges">Edges</h4>
    <div class="l-row"><div class="l-line" style="background:#27ae60"></div><span data-i18n="x6_supports">Supports</span></div>
    <div class="l-row"><div class="l-line" style="background:#e74c3c"></div><span data-i18n="x6_attacks">Attacks</span></div>
    <div class="l-row"><div class="l-line" style="background:#718096"></div><span data-i18n="x6_qualifies">Qualifies</span></div>
    <div class="l-row"><div style="width:18px;border-top:2px dashed #a0aec0;flex-shrink:0"></div><span data-i18n="x6_invalid_style">Invalid</span></div>
    <div class="l-row" style="margin-top:3px;color:#a0aec0" data-i18n="x6_thickness">Thickness = strength</div>
    <hr class="l-sep">
    <div style="color:#a0aec0" data-i18n="x6_pan_zoom">Drag canvas to pan · Scroll to zoom</div>
  </div>
</div>

<div id="right-panel-toggle" class="panel-toggle" onclick="toggleRightPanel()" title="Toggle right panel">&#x25BA;</div>
<div id="edit-panel">
  <div id="panel-resize-handle"></div>
  <div id="ref-browser"></div>

  <div id="edit-node" style="display:none">
    <h3 data-i18n="x6_edit_node">Edit node</h3>
    <label class="field-label" data-i18n="x6_type">Type</label>
    <select id="edit-type">
      <option value="claim" data-i18n="nt_claim">Claim</option>
      <option value="normative_premise" data-i18n="nt_normative">Normative premise</option>
      <option value="empirical_premise" data-i18n="nt_empirical">Empirical premise</option>
      <option value="metaphysical_commitment" data-i18n="nt_metaphysical">Metaphysical commitment</option>
      <option value="intermediate_conclusion" data-i18n="nt_intermediate">Intermediate conclusion</option>
      <option value="linked_joiner" data-i18n="nt_joiner">Co-premise joiner (∧)</option>
    </select>
    <label class="field-label" data-i18n="x6_content">Content</label>
    <textarea id="edit-content" rows="6"></textarea>
    <label class="field-label" data-i18n="x6_notes">Notes</label>
    <textarea id="edit-notes" rows="2" data-i18n-ph="x6_notes_ph" placeholder="Shown on hover..."></textarea>
    <div class="action-row">
      <button class="btn-primary" onclick="updateNode()" data-i18n="x6_update">Update</button>
      <button class="btn-danger"  onclick="deleteSelected()" data-i18n="x6_delete">Delete</button>
    </div>
  </div>

  <div id="edit-edge" style="display:none">
    <h3 data-i18n="x6_edit_edge">Edit edge</h3>
    <label class="field-label" data-i18n="x6_relation">Relation</label>
    <select id="edit-relation">
      <option value="supports" data-i18n="x6_supports">Supports</option>
      <option value="attacks" data-i18n="x6_attacks">Attacks</option>
      <option value="qualifies" data-i18n="x6_qualifies">Qualifies</option>
    </select>
    <label class="field-label" data-i18n="x6_strength">Strength (thickness)</label>
    <div class="slider-row">
      <input type="range" id="edit-strength" min="0" max="1" step="0.05" value="0.5"
             oninput="onStrengthInput(this.value)">
      <span class="slider-val" id="strength-val">0.50</span>
    </div>
    <label class="field-label" data-i18n="x6_rule">Inferential rule</label>
    <textarea id="edit-rule" rows="2" data-i18n-ph="x6_rule_ph" placeholder="e.g. modus ponens"></textarea>
    <label class="field-label" data-i18n="x6_rule_reason">Rule — reason (optional)</label>
    <textarea id="edit-rule-reason" rows="2" data-i18n-ph="x6_rule_reason_ph" placeholder="How this step instantiates the rule..."></textarea>
    <label class="field-label" data-i18n="x6_validity">Validity</label>
    <select id="edit-validity">
      <option value="unknown" data-i18n="x6_not_evaluated">Not evaluated</option>
      <option value="valid" data-i18n="x6_valid">Valid ✓</option>
      <option value="invalid" data-i18n="x6_invalid_opt">Invalid ✗</option>
    </select>
    <label class="field-label" data-i18n="x6_bias_label">Bias — label</label>
    <textarea id="edit-bias-label" rows="1" data-i18n-ph="x6_bias_label_ph" placeholder="e.g. availability heuristic"></textarea>
    <label class="field-label" data-i18n="x6_bias_reason">Bias — reason</label>
    <textarea id="edit-bias-reason" rows="2" data-i18n-ph="x6_bias_reason_ph" placeholder="Why this step has this bias..."></textarea>
    <label class="field-label" data-i18n="x6_fallacy_label">Fallacy — label</label>
    <textarea id="edit-fallacy-label" rows="1" data-i18n-ph="x6_fallacy_label_ph" placeholder="e.g. false dichotomy"></textarea>
    <label class="field-label" data-i18n="x6_fallacy_reason">Fallacy — reason</label>
    <textarea id="edit-fallacy-reason" rows="2" data-i18n-ph="x6_fallacy_reason_ph" placeholder="Why this step has this fallacy..."></textarea>
    <div class="action-row">
      <button class="btn-primary" onclick="updateEdge()" data-i18n="x6_update">Update</button>
      <button class="btn-danger"  onclick="deleteSelected()" data-i18n="x6_delete">Delete</button>
    </div>
  </div>
</div>

<div id="tooltip"></div>

<div id="help-overlay" onclick="if(event.target===this)closeHelp()">
  <div id="help-modal">
    <button class="close-btn" onclick="closeHelp()">&#x2715;</button>
    <h2 data-i18n="x6_help_title">ArguMap &mdash; Reference</h2>

    <h3 data-i18n="x6_node_types_h">Node types</h3>
    <div class="h-row"><div class="h-dot" style="background:#0a3c8a"></div><div><span class="h-key" data-i18n="nt_claim">Claim (thesis)</span> <kbd>T</kbd> &mdash; <span data-i18n="x6_nt_desc_claim">Central thesis. Exactly one per map; all other nodes support, attack, or qualify it.</span></div></div>
    <div class="h-row"><div class="h-dot" style="background:#a88614"></div><div><span class="h-key" data-i18n="nt_normative">Normative premise</span> <kbd>N</kbd> &mdash; <span data-i18n="x6_nt_desc_normative">An ethical or normative claim: a principle, right, duty, or value judgment.</span></div></div>
    <div class="h-row"><div class="h-dot" style="background:#a3b51b"></div><div><span class="h-key" data-i18n="nt_metaphysical">Metaphysical commitment</span> <kbd>M</kbd> &mdash; <span data-i18n="x6_nt_desc_metaphysical">Deep background assumption that grounds normative premises (Toulmin&rsquo;s backing).</span></div></div>
    <div class="h-row"><div class="h-dot" style="background:#630541"></div><div><span class="h-key" data-i18n="nt_empirical">Empirical premise</span> <kbd>E</kbd> &mdash; <span data-i18n="x6_nt_desc_empirical">A factual or empirical claim supported by evidence or data.</span></div></div>
    <div class="h-row"><div class="h-dot" style="background:#1683ab"></div><div><span class="h-key" data-i18n="nt_intermediate">Intermediate conclusion</span> <kbd>I</kbd> &mdash; <span data-i18n="x6_nt_desc_intermediate">A sub-conclusion within the inferential chain, derived from premises and feeding into the claim.</span></div></div>
    <div class="h-row"><div class="h-dot" style="background:#4a5568;border-radius:50%"></div><div><span class="h-key" data-i18n="nt_joiner">Co-premise joiner (&#x2227;)</span> <kbd>J</kbd> &mdash; <span data-i18n="x6_nt_desc_joiner">Links premises that are co-dependent: all connected premises are jointly required for the inference (linked argument, not convergent).</span></div></div>

    <h3 data-i18n="x6_edge_props_h">Edge properties</h3>
    <table>
      <tr><th data-i18n="x6_prop_col">Property</th><th data-i18n="x6_values_col">Values</th><th data-i18n="x6_meaning_col">Meaning</th></tr>
      <tr><td><strong data-i18n="x6_prop_relation">Relation</strong></td><td data-i18n="x6_rel_values">Supports / Attacks / Qualifies</td><td data-i18n="x6_meaning_relation">Whether the source strengthens, undermines, or constrains the target.</td></tr>
      <tr><td><strong data-i18n="x6_prop_validity">Validity</strong></td><td data-i18n="x6_val_values">Valid &middot; Invalid &middot; Not evaluated</td><td data-i18n="x6_meaning_validity">Solid = valid; dashed = invalid or fallacious; faded = not yet assessed.</td></tr>
      <tr><td><strong data-i18n="x6_prop_strength">Strength</strong></td><td>0 &ndash; 1</td><td data-i18n="x6_meaning_strength">Evidential weight of the inference. Controls edge thickness.</td></tr>
      <tr><td><strong data-i18n="x6_prop_rule">Rule</strong></td><td data-i18n="x6_free_text">Free text</td><td data-i18n="x6_meaning_rule">Explicit inferential rule, e.g. modus ponens, specification. Shown as label on the edge.</td></tr>
      <tr><td><strong data-i18n="x6_prop_bias">Bias</strong></td><td data-i18n="x6_free_text">Free text</td><td data-i18n="x6_meaning_bias">Potential bias in the inference. Shown as &#x26a0; chip on the edge and in the hover tooltip.</td></tr>
      <tr><td><strong data-i18n="x6_prop_fallacy">Fallacy</strong></td><td data-i18n="x6_free_text">Free text</td><td data-i18n="x6_meaning_fallacy">Logical fallacy, e.g. appeal to authority. Shown as &#x26a0; chip on the edge and in the hover tooltip.</td></tr>
    </table>

    <h3 data-i18n="x6_shortcuts_h">Keyboard shortcuts</h3>
    <table>
      <tr><th colspan="2" data-i18n="x6_sc_add_nodes">Add nodes (canvas must be focused, not an input field)</th></tr>
      <tr><td><strong>T</strong></td><td data-i18n="x6_sc_add_claim">Add Claim (Thesis)</td></tr>
      <tr><td><strong>N</strong></td><td data-i18n="x6_sc_add_normative">Add Normative premise</td></tr>
      <tr><td><strong>E</strong></td><td data-i18n="x6_sc_add_empirical">Add Empirical premise</td></tr>
      <tr><td><strong>M</strong></td><td data-i18n="x6_sc_add_metaphysical">Add Metaphysical commitment</td></tr>
      <tr><td><strong>I</strong></td><td data-i18n="x6_sc_add_intermediate">Add Intermediate conclusion</td></tr>
      <tr><td><strong>J</strong></td><td data-i18n="x6_sc_add_joiner">Add Co-premise joiner (&#x2227;)</td></tr>
      <tr><th colspan="2" data-i18n="x6_sc_canvas_mode">Canvas &amp; mode</th></tr>
      <tr><td><strong>C</strong></td><td data-i18n="x6_sc_toggle_connect">Toggle Connect mode</td></tr>
      <tr><td><strong>Escape</strong></td><td data-i18n="x6_sc_exit_connect">Exit Connect mode / deselect</td></tr>
      <tr><th colspan="2" data-i18n="x6_sc_general">General</th></tr>
      <tr><td><strong>Ctrl+Z</strong></td><td data-i18n="x6_sc_undo">Undo</td></tr>
      <tr><td><strong>Ctrl+Y &nbsp;/&nbsp; Ctrl+Shift+Z</strong></td><td data-i18n="x6_sc_redo">Redo</td></tr>
      <tr><td><strong>Delete / Backspace</strong></td><td data-i18n="x6_sc_delete_sel">Remove selected node or edge</td></tr>
      <tr><td><strong>Scroll</strong></td><td data-i18n="x6_sc_zoom">Zoom in / out</td></tr>
      <tr><td><strong>Drag canvas</strong></td><td data-i18n="x6_sc_pan">Pan the view</td></tr>
    </table>
  </div>
</div>

<script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@antv/x6@2.18.1/dist/index.js"></script>

<script>
const NODES_DATA   = AUTOMAP_NODES_JSON;
const EDGES_DATA   = AUTOMAP_EDGES_JSON;
const TITLE        = "AUTOMAP_TITLE";
const SCHEMES_DATA = AUTOMAP_SCHEMES_JSON;
const LAYOUT_DATA  = AUTOMAP_LAYOUT_JSON;
const T            = AUTOMAP_T_JSON;
const GUIDED_START = AUTOMAP_GUIDED;
const LANG         = "AUTOMAP_LANG";

if (typeof X6 === 'undefined') {
  document.getElementById('graph-container').innerHTML =
    '<div style="padding:24px;color:#e74c3c">Error: X6 failed to load from CDN.</div>';
  throw new Error('X6 is not defined');
}

var selectedCell  = null;
var connectSource = null;
var _undoStack    = [];
var _redoStack    = [];
var _MAX_HISTORY  = 20;
var mode          = 'select';
var _nodeCounter  = 1000;
var _JOINER_SIZE  = 30;
var _leftVisible  = true;
var _rightVisible = true;
var _resizing     = false;
var _resizeStartX = 0;
var _resizeStartW = 0;
var _LEFT_W       = 172;
var _RIGHT_W      = 256;
var _MIN_RIGHT_W  = 180;
var _MAX_RIGHT_W  = 520;

const NODE_COLORS = {
  claim:                   '#0a3c8a',
  normative_premise:       '#a88614',
  empirical_premise:       '#630541',
  metaphysical_commitment: '#a3b51b',
  intermediate_conclusion: '#1683ab',
  linked_joiner:           '#4a5568',
};
const TYPE_LABELS = {
  claim:                   T.nt_claim,
  normative_premise:       T.nt_normative,
  empirical_premise:       T.nt_empirical,
  metaphysical_commitment: T.nt_metaphysical,
  intermediate_conclusion: T.nt_intermediate,
  linked_joiner:           T.nt_joiner,
};
const EDGE_COLORS    = { supports: '#27ae60', attacks: '#e74c3c', qualifies: '#718096' };
const VALIDITY_LABEL = { valid: '✓ ' + T.x6_valid, invalid: '✗ ' + T.x6_invalid_opt, unknown: '? ' + T.x6_not_evaluated };
var   EDGE_ROUTER    = { name: 'metro' };
const EDGE_CONNECTOR = { name: 'rounded', args: { radius: 4 } };

// Apply UI translations to elements with data-i18n / data-i18n-ph attributes.
function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(function(el) {
    var key = el.getAttribute('data-i18n');
    if (T[key] !== undefined) el.textContent = T[key];
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(function(el) {
    var key = el.getAttribute('data-i18n-ph');
    if (T[key] !== undefined) el.placeholder = T[key];
  });
}
applyTranslations();

// --- History (undo / redo) ---
function _captureState() {
  const nodes = [], steps = [];
  const joinerIds = new Set(
    graph.getNodes().filter(n => (n.getData() || {}).type === 'linked_joiner').map(n => n.id)
  );
  graph.getNodes().forEach(function(node) {
    if (joinerIds.has(node.id)) return;
    const d = node.getData() || {};
    nodes.push({ id: node.id, type: d.type || 'normative_premise',
                 content: d.content || '', notes: d.notes || null });
  });
  graph.getEdges().forEach(function(edge) {
    const src = edge.getSourceCellId(), tgt = edge.getTargetCellId();
    if (joinerIds.has(src) || joinerIds.has(tgt)) return;
    const d = edge.getData() || {};
    steps.push({
      id: edge.id, sources: [src], target: tgt, linked: false,
      relation: d.relation || 'supports', rule: d.rule || null,
      rule_reason: d.rule_reason || null,
      strength: d.strength !== undefined ? d.strength : 0.5,
      annotation: {
        valid: d.validity === 'valid' ? true : d.validity === 'invalid' ? false : null,
        bias_label: d.bias_label || null, bias_reason: d.bias_reason || null,
        fallacy_label: d.fallacy_label || null, fallacy_reason: d.fallacy_reason || null,
      }
    });
  });
  graph.getNodes().filter(function(n) { return joinerIds.has(n.id); }).forEach(function(joiner) {
    const ins  = graph.getIncomingEdges(joiner) || [];
    const outs = graph.getOutgoingEdges(joiner) || [];
    const d = outs.length ? (outs[0].getData() || {}) : {};
    steps.push({
      id: joiner.id.replace('joiner_', ''), sources: ins.map(function(e) { return e.getSourceCellId(); }),
      target: outs.length ? outs[0].getTargetCellId() : null, linked: true,
      relation: d.relation || 'supports', rule: d.rule || null,
      rule_reason: d.rule_reason || null,
      strength: d.strength !== undefined ? d.strength : 0.5,
      annotation: {
        valid: d.validity === 'valid' ? true : d.validity === 'invalid' ? false : null,
        bias_label: d.bias_label || null, bias_reason: d.bias_reason || null,
        fallacy_label: d.fallacy_label || null, fallacy_reason: d.fallacy_reason || null,
      }
    });
  });
  const titleEl = document.getElementById('map-title');
  const currentTitle = titleEl ? titleEl.textContent.trim() : TITLE;
  const layout = {};
  graph.getNodes().forEach(function(n) {
    const pos = n.getPosition();
    if (!pos) return;
    layout[n.id] = { x: pos.x, y: pos.y };
    if (joinerIds.has(n.id)) {
      const stepId = n.id.replace('joiner_', '');
      layout['joiner_' + stepId] = { x: pos.x, y: pos.y };
    }
  });
  return { id: 'snapshot', title: currentTitle, nodes: nodes, steps: steps, _layout: layout };
}

function _updateHistoryBtns() {
  document.getElementById('btn-undo').disabled = !_undoStack.length;
  document.getElementById('btn-redo').disabled = !_redoStack.length;
}

function _pushUndo() {
  _undoStack.push(_captureState());
  if (_undoStack.length > _MAX_HISTORY) _undoStack.shift();
  _redoStack = [];
  _updateHistoryBtns();
}

function undo() {
  if (!_undoStack.length) return;
  _redoStack.push(_captureState());
  rebuildFromMap(_undoStack.pop());
  _updateHistoryBtns();
}

function redo() {
  if (!_redoStack.length) return;
  _undoStack.push(_captureState());
  rebuildFromMap(_redoStack.pop());
  _updateHistoryBtns();
}

// --- Helpers ---
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderMdLinks(s) {
  return escHtml(s).replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/(?:[^)(]|\\([^)]*\\))*)\\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function strengthToWidth(s) {
  s = (s === undefined || s === null) ? 0.5 : parseFloat(s);
  return 1 + s * 5;   // range 1–6 px
}

function markerFor(stroke, strength) {
  const sw = strengthToWidth(strength);
  const s  = Math.max(10, sw * 2.5);
  const w  = Math.round(s * 0.55);
  const ox = sw;
  return {
    tagName: 'path',
    d: 'M ' + (s - ox) + ' -' + w + ' -' + ox + ' 0 ' + (s - ox) + ' ' + w + ' Z',
    fill: stroke,
    stroke: 'none',
  };
}

function edgeAttrs(relation, validity, strength) {
  const stroke = EDGE_COLORS[relation] || '#a0aec0';
  return {
    line: {
      stroke,
      strokeWidth:     strengthToWidth(strength),
      targetMarker:    markerFor(stroke, strength),
      strokeDasharray: validity === 'invalid' ? '6,3' : null,
      opacity:         validity === 'unknown'  ? 0.6   : 1,
    }
  };
}

// --- Dagre layout ---
function computeLayout(nodes, edges) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'BT', nodesep: 50, ranksep: 90 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) g.setNode(n.id, { width: n.width, height: n.height });
  for (const e of edges) { try { g.setEdge(e.source, e.target); } catch(_) {} }
  dagre.layout(g);
  const pos = {};
  g.nodes().forEach(id => {
    const n = g.node(id);
    if (n) pos[id] = { x: n.x - n.width / 2, y: n.y - n.height / 2 };
  });
  return pos;
}

// --- X6 graph ---
const container = document.getElementById('graph-container');
const graph = new X6.Graph({
  container,
  autoResize:  true,
  grid:        { visible: true, type: 'dot', args: { color: '#d9d9d9', thickness: 1 } },
  background:  { color: '#f0f2f5' },
  mousewheel:  { enabled: true, zoomAtMousePosition: true },
  panning:     { enabled: true },
  interacting: { nodeMovable: true, edgeMovable: false },
});

// --- Word wrap (mirrors Python _wrap_text) ---
function wrapText(text, charsPerLine) {
  charsPerLine = charsPerLine || 33;
  const words = String(text).trim().split(/\\s+/);
  const lines = [];
  let current = [], curLen = 0;
  for (const word of words) {
    if (current.length && curLen + 1 + word.length > charsPerLine) {
      lines.push(current.join(' '));
      current = [word]; curLen = word.length;
    } else {
      current.push(word);
      curLen += (current.length > 1 ? 1 : 0) + word.length;
    }
  }
  if (current.length) lines.push(current.join(' '));
  return lines.join('\\n');
}

// --- Edge labels (rule + bias/fallacy warning) ---
function makeEdgeLabels(rule, biasLabel, fallacyLabel) {
  const labels = [];
  const hasWarn = !!(biasLabel || fallacyLabel);
  if (rule) labels.push({
    position: hasWarn ? 0.3 : 0.5,
    attrs: {
      label: { text: rule, fontSize: 9, fill: '#4a5568', textAnchor: 'middle' },
      body:  { fill: 'white', stroke: '#e2e8f0', strokeWidth: 1, rx: 3, ry: 3 },
    }
  });
  if (hasWarn) {
    const txt = (biasLabel && fallacyLabel)
      ? '⚠ ' + biasLabel + ' · ' + fallacyLabel
      : biasLabel ? '⚠ ' + biasLabel : '⚠ ' + fallacyLabel;
    labels.push({
      position: rule ? 0.7 : 0.5,
      attrs: {
        label: { text: txt, fontSize: 9, fill: '#b7440a', fontWeight: '600', textAnchor: 'middle' },
        body:  { fill: '#fff4e6', stroke: '#e67e22', strokeWidth: 1, rx: 3, ry: 3 },
      }
    });
  }
  return labels;
}

// --- Node definition ---
function makeNodeDef(n, pos) {
  const isJoiner = n.type === 'linked_joiner';
  const displayLabel = isJoiner ? '∧' : (n.label || wrapText(n.content || ''));
  const idText = isJoiner ? '' : n.id;
  return {
    id: n.id, x: pos.x, y: pos.y, width: n.width, height: n.height, shape: 'rect',
    label: displayLabel,
    markup: [
      { tagName: 'rect', selector: 'body' },
      { tagName: 'text', selector: 'label' },
      { tagName: 'text', selector: 'id-tag' },
    ],
    attrs: {
      body: {
        fill: NODE_COLORS[n.type] || '#aaa', stroke: 'none',
        rx: isJoiner ? n.width / 2 : 6, ry: isJoiner ? n.height / 2 : 6,
      },
      label: {
        fill: '#ffffff', fontSize: isJoiner ? 16 : 11, fontFamily: 'inherit',
        textAnchor: 'middle', textVerticalAnchor: 'middle',
        lineHeight: 16,
      },
      'id-tag': {
        text: idText,
        fontSize: 8, fontFamily: 'inherit',
        fill: 'rgba(255,255,255,0.45)',
        textAnchor: 'end', dominantBaseline: 'auto',
        refX: 0.97, refY: 0.95,
      },
    },
    data: { type: n.type, content: n.content || displayLabel, notes: n.notes || '' },
  };
}

// --- Render ---
function renderAll() {
  const positions = computeLayout(NODES_DATA, EDGES_DATA);
  for (const n of NODES_DATA) {
    const pos = (LAYOUT_DATA && LAYOUT_DATA[n.id]) || positions[n.id] || { x: 60, y: 60 };
    graph.addNode(makeNodeDef(n, pos));
  }
  for (const e of EDGES_DATA) {
    graph.addEdge({
      id: e.id, source: { cell: e.source }, target: { cell: e.target },
      router: EDGE_ROUTER, connector: EDGE_CONNECTOR,
      attrs:  edgeAttrs(e.relation, e.validity, e.strength),
      labels: makeEdgeLabels(e.rule, e.bias_label, e.fallacy_label),
      data:   { relation: e.relation, rule: e.rule, rule_reason: e.rule_reason,
                validity: e.validity,
                bias_label: e.bias_label, bias_reason: e.bias_reason,
                fallacy_label: e.fallacy_label, fallacy_reason: e.fallacy_reason,
                strength: e.strength || 0.5 },
      zIndex: 0,
    });
  }
  setTimeout(() => { graph.centerContent(); addClaimRipple(); _bringLabelsToFront(); }, 80);
  buildRefBrowser();
}

// --- Claim ripple ---
function addClaimRipple(targetNode) {
  const claimNode = targetNode || graph.getNodes().find(n => (n.getData()||{}).type === 'claim');
  if (!claimNode) return;
  const view = graph.findViewByCell(claimNode);
  if (!view) return;
  const { width, height } = claimNode.getSize();
  const ns = 'http://www.w3.org/2000/svg';
  [0, 1].forEach(function(i) {
    const ring = document.createElementNS(ns, 'rect');
    ring.setAttribute('width', width);
    ring.setAttribute('height', height);
    ring.setAttribute('rx', 6);
    ring.setAttribute('ry', 6);
    ring.setAttribute('fill', 'none');
    ring.setAttribute('stroke', '#0a3c8a');
    ring.setAttribute('stroke-width', '2.5');
    ring.setAttribute('pointer-events', 'none');
    ring.setAttribute('class', 'claim-ring');
    ring.style.animationDelay = (i * -1.1) + 's';
    view.container.appendChild(ring);
  });
}

// --- Tooltip ---
const tooltip = document.getElementById('tooltip');
var _tooltipActive = false;

function showTooltip(html) {
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  _tooltipActive = true;
}
function hideTooltip() {
  tooltip.style.display = 'none';
  _tooltipActive = false;
}
function posTooltip(x, y) {
  const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
  tooltip.style.left = Math.min(x + 14, window.innerWidth  - tw - 8) + 'px';
  tooltip.style.top  = Math.max(8, Math.min(y - 10, window.innerHeight - th - 8)) + 'px';
}
document.addEventListener('mousemove', e => {
  if (_tooltipActive) posTooltip(e.clientX, e.clientY);
});

// --- Panel helpers ---
function showRefBrowser() {
  document.getElementById('ref-browser').style.display = '';
  document.getElementById('edit-node').style.display   = 'none';
  document.getElementById('edit-edge').style.display   = 'none';
}
function showNodePanel() {
  document.getElementById('ref-browser').style.display = 'none';
  document.getElementById('edit-node').style.display   = '';
  document.getElementById('edit-edge').style.display   = 'none';
}
function showEdgePanel() {
  document.getElementById('ref-browser').style.display = 'none';
  document.getElementById('edit-node').style.display   = 'none';
  document.getElementById('edit-edge').style.display   = '';
}

// --- Reference browser ---
function _flattenSchemes() {
  const rules = [];
  for (const fam of Object.values((SCHEMES_DATA || {}).inferential_rules || {}))
    for (const r of (fam.rules || [])) rules.push(r);
  const fallacies = [];
  for (const fam of Object.values((SCHEMES_DATA || {}).fallacies || {}))
    for (const f of (fam.fallacies || [])) fallacies.push(f);
  const biases = [];
  for (const fam of Object.values((SCHEMES_DATA || {}).biases || {}))
    for (const b of (fam.biases || [])) biases.push(b);
  return {
    rules:     rules,
    fallacies: fallacies,
    biases:    biases,
  };
}
const SCHEMES_FLAT = _flattenSchemes();

function _buildFlatSection(id, label, items) {
  let html = '<div class="ref-section" id="refsec-' + id + '">';
  html += '<div class="ref-section-hd" data-sec="' + id + '" onclick="toggleRefSection(this.dataset.sec)">';
  html += '<span class="ref-chev" id="ref-chev-' + id + '">&#x25BE;</span> ';
  html += escHtml(label);
  html += ' <span class="ref-count">' + items.length + '</span></div>';
  html += '<div class="ref-body open" id="ref-body-' + id + '">';
  for (let i = 0; i < items.length; i++) {
    const item   = items[i];
    const itemId = 'ritem-' + id + '-' + i;
    html += '<div class="ref-item" id="' + itemId + '">';
    html += '<div class="ref-item-hd" data-id="' + itemId + '" onclick="toggleRefItem(this.dataset.id)">' + escHtml(item.name) + '</div>';
    html += '<div class="ref-item-detail" id="' + itemId + '-det">';
    html += '<div class="ref-item-desc">' + escHtml(item.description) + '</div>';
    if (item.example)
      html += '<div class="ref-item-ex">' + escHtml(item.example) + '</div>';
    if (item.source)
      html += '<div class="ref-item-src">' + renderMdLinks(item.source) + '</div>';
    html += '</div></div>';
  }
  html += '<div class="ref-no-results" id="ref-empty-' + id + '">No matches</div>';
  html += '</div></div>';
  return html;
}

function buildRefBrowser() {
  const container = document.getElementById('ref-browser');
  if (!container) return;
  let html = '<input type="text" id="ref-search" placeholder="&#x1F50D; Search&hellip;" oninput="filterRef(this.value)">';

  // Inferential rules: nested by family
  const ruleFamilies = Object.entries((SCHEMES_DATA || {}).inferential_rules || {});
  html += '<div class="ref-section" id="refsec-rules">';
  html += '<div class="ref-section-hd" data-sec="rules" onclick="toggleRefSection(this.dataset.sec)">';
  html += '<span class="ref-chev" id="ref-chev-rules">&#x25BE;</span> Inferential Rules';
  html += ' <span class="ref-count">' + SCHEMES_FLAT.rules.length + '</span></div>';
  html += '<div class="ref-body open" id="ref-body-rules">';
  let ruleIdx = 0;
  for (const [famKey, fam] of ruleFamilies) {
    const items = fam.rules || [];
    html += '<div id="refsubfam-rule-' + famKey + '">';
    html += '<div class="ref-subfam-hd" data-fam="rule-' + famKey + '" onclick="toggleRefSubfam(this.dataset.fam)">';
    html += '<span class="ref-chev" id="ref-subchev-rule-' + famKey + '">&#x25BE;</span> ';
    html += escHtml(fam.label || famKey);
    html += ' <span class="ref-count">' + items.length + '</span></div>';
    html += '<div class="ref-subfam-body open" id="ref-subfam-body-rule-' + famKey + '">';
    for (let i = 0; i < items.length; i++) {
      const item   = items[i];
      const itemId = 'ritem-rules-' + ruleIdx++;
      html += '<div class="ref-item" id="' + itemId + '">';
      html += '<div class="ref-item-hd" data-id="' + itemId + '" onclick="toggleRefItem(this.dataset.id)">' + escHtml(item.name) + '</div>';
      html += '<div class="ref-item-detail" id="' + itemId + '-det">';
      html += '<div class="ref-item-desc">' + escHtml(item.description) + '</div>';
      if (item.example)
        html += '<div class="ref-item-ex">' + escHtml(item.example) + '</div>';
      if (item.source)
        html += '<div class="ref-item-src">' + renderMdLinks(item.source) + '</div>';
      html += '</div></div>';
    }
    html += '</div></div>';
  }
  html += '<div class="ref-no-results" id="ref-empty-rules">No matches</div>';
  html += '</div></div>';

  // Fallacies: nested by family
  const fallacyFamilies = Object.entries((SCHEMES_DATA || {}).fallacies || {});
  html += '<div class="ref-section" id="refsec-fallacies">';
  html += '<div class="ref-section-hd" data-sec="fallacies" onclick="toggleRefSection(this.dataset.sec)">';
  html += '<span class="ref-chev" id="ref-chev-fallacies">&#x25BE;</span> Fallacies';
  html += ' <span class="ref-count">' + SCHEMES_FLAT.fallacies.length + '</span></div>';
  html += '<div class="ref-body open" id="ref-body-fallacies">';
  let fallacyIdx = 0;
  for (const [famKey, fam] of fallacyFamilies) {
    const items = fam.fallacies || [];
    html += '<div id="refsubfam-' + famKey + '">';
    html += '<div class="ref-subfam-hd" data-fam="' + famKey + '" onclick="toggleRefSubfam(this.dataset.fam)">';
    html += '<span class="ref-chev" id="ref-subchev-' + famKey + '">&#x25BE;</span> ';
    html += escHtml(fam.label || famKey);
    html += ' <span class="ref-count">' + items.length + '</span></div>';
    html += '<div class="ref-subfam-body open" id="ref-subfam-body-' + famKey + '">';
    for (let i = 0; i < items.length; i++) {
      const item   = items[i];
      const itemId = 'ritem-fallacies-' + fallacyIdx++;
      html += '<div class="ref-item" id="' + itemId + '">';
      html += '<div class="ref-item-hd" data-id="' + itemId + '" onclick="toggleRefItem(this.dataset.id)">' + escHtml(item.name) + '</div>';
      html += '<div class="ref-item-detail" id="' + itemId + '-det">';
      html += '<div class="ref-item-desc">' + escHtml(item.description) + '</div>';
      if (item.example)
        html += '<div class="ref-item-ex">' + escHtml(item.example) + '</div>';
      if (item.source)
        html += '<div class="ref-item-src">' + renderMdLinks(item.source) + '</div>';
      html += '</div></div>';
    }
    html += '</div></div>';
  }
  html += '<div class="ref-no-results" id="ref-empty-fallacies">No matches</div>';
  html += '</div></div>';

  // Biases: nested by family
  const biasFamilies = Object.entries((SCHEMES_DATA || {}).biases || {});
  html += '<div class="ref-section" id="refsec-biases">';
  html += '<div class="ref-section-hd" data-sec="biases" onclick="toggleRefSection(this.dataset.sec)">';
  html += '<span class="ref-chev" id="ref-chev-biases">&#x25BE;</span> Biases';
  html += ' <span class="ref-count">' + SCHEMES_FLAT.biases.length + '</span></div>';
  html += '<div class="ref-body open" id="ref-body-biases">';
  let biasIdx = 0;
  for (const [famKey, fam] of biasFamilies) {
    const items = fam.biases || [];
    html += '<div id="refsubfam-bias-' + famKey + '">';
    html += '<div class="ref-subfam-hd" data-fam="bias-' + famKey + '" onclick="toggleRefSubfam(this.dataset.fam)">';
    html += '<span class="ref-chev" id="ref-subchev-bias-' + famKey + '">&#x25BE;</span> ';
    html += escHtml(fam.label || famKey);
    html += ' <span class="ref-count">' + items.length + '</span></div>';
    html += '<div class="ref-subfam-body open" id="ref-subfam-body-bias-' + famKey + '">';
    for (let i = 0; i < items.length; i++) {
      const item   = items[i];
      const itemId = 'ritem-biases-' + biasIdx++;
      html += '<div class="ref-item" id="' + itemId + '">';
      html += '<div class="ref-item-hd" data-id="' + itemId + '" onclick="toggleRefItem(this.dataset.id)">' + escHtml(item.name) + '</div>';
      html += '<div class="ref-item-detail" id="' + itemId + '-det">';
      html += '<div class="ref-item-desc">' + escHtml(item.description) + '</div>';
      if (item.example)
        html += '<div class="ref-item-ex">' + escHtml(item.example) + '</div>';
      if (item.source)
        html += '<div class="ref-item-src">' + renderMdLinks(item.source) + '</div>';
      html += '</div></div>';
    }
    html += '</div></div>';
  }
  html += '<div class="ref-no-results" id="ref-empty-biases">No matches</div>';
  html += '</div></div>';

  container.innerHTML = html;
}

function toggleRefSubfam(famKey) {
  const body = document.getElementById('ref-subfam-body-' + famKey);
  const chev = document.getElementById('ref-subchev-' + famKey);
  if (!body) return;
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  if (chev) chev.classList.toggle('closed', isOpen);
}

function toggleRefSection(id) {
  const body = document.getElementById('ref-body-' + id);
  const chev = document.getElementById('ref-chev-' + id);
  if (!body) return;
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  if (chev) chev.classList.toggle('closed', isOpen);
}

function toggleRefItem(itemId) {
  const det = document.getElementById(itemId + '-det');
  if (det) det.classList.toggle('open');
}

function filterRef(query) {
  query = query.toLowerCase().trim();

  // Rules: nested by family
  let ruleGlobalIdx = 0;
  let anyRuleVisible = false;
  for (const [famKey, fam] of Object.entries((SCHEMES_DATA || {}).inferential_rules || {})) {
    const items = fam.rules || [];
    let anyFamVisible = false;
    for (let i = 0; i < items.length; i++) {
      const item   = items[i];
      const itemEl = document.getElementById('ritem-rules-' + ruleGlobalIdx++);
      if (!itemEl) continue;
      const matches = !query ||
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query);
      itemEl.style.display = matches ? '' : 'none';
      if (matches) { anyFamVisible = true; anyRuleVisible = true; }
    }
    if (query) {
      const subfamBody = document.getElementById('ref-subfam-body-rule-' + famKey);
      const subfamChev = document.getElementById('ref-subchev-rule-' + famKey);
      if (subfamBody) subfamBody.classList.toggle('open', anyFamVisible);
      if (subfamChev) subfamChev.classList.toggle('closed', !anyFamVisible);
    }
  }
  const ruleEmptyEl = document.getElementById('ref-empty-rules');
  if (ruleEmptyEl) ruleEmptyEl.style.display = (query && !anyRuleVisible) ? 'block' : 'none';
  if (query && anyRuleVisible) {
    const body = document.getElementById('ref-body-rules');
    const chev = document.getElementById('ref-chev-rules');
    if (body) body.classList.add('open');
    if (chev) chev.classList.remove('closed');
  }

  // Fallacies: nested by family
  let globalIdx = 0;
  let anyFallacyVisible = false;
  for (const [famKey, fam] of Object.entries((SCHEMES_DATA || {}).fallacies || {})) {
    const items = fam.fallacies || [];
    let anyFamVisible = false;
    for (let i = 0; i < items.length; i++) {
      const item   = items[i];
      const itemEl = document.getElementById('ritem-fallacies-' + globalIdx++);
      if (!itemEl) continue;
      const matches = !query ||
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query);
      itemEl.style.display = matches ? '' : 'none';
      if (matches) { anyFamVisible = true; anyFallacyVisible = true; }
    }
    if (query) {
      const subfamBody = document.getElementById('ref-subfam-body-' + famKey);
      const subfamChev = document.getElementById('ref-subchev-' + famKey);
      if (subfamBody) subfamBody.classList.toggle('open', anyFamVisible);
      if (subfamChev) subfamChev.classList.toggle('closed', !anyFamVisible);
    }
  }
  const emptyEl = document.getElementById('ref-empty-fallacies');
  if (emptyEl) emptyEl.style.display = (query && !anyFallacyVisible) ? 'block' : 'none';
  if (query && anyFallacyVisible) {
    const body = document.getElementById('ref-body-fallacies');
    const chev = document.getElementById('ref-chev-fallacies');
    if (body) body.classList.add('open');
    if (chev) chev.classList.remove('closed');
  }

  // Biases: nested by family
  let biasGlobalIdx = 0;
  let anyBiasVisible = false;
  for (const [famKey, fam] of Object.entries((SCHEMES_DATA || {}).biases || {})) {
    const items = fam.biases || [];
    let anyFamVisible = false;
    for (let i = 0; i < items.length; i++) {
      const item   = items[i];
      const itemEl = document.getElementById('ritem-biases-' + biasGlobalIdx++);
      if (!itemEl) continue;
      const matches = !query ||
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query);
      itemEl.style.display = matches ? '' : 'none';
      if (matches) { anyFamVisible = true; anyBiasVisible = true; }
    }
    if (query) {
      const subfamBody = document.getElementById('ref-subfam-body-bias-' + famKey);
      const subfamChev = document.getElementById('ref-subchev-bias-' + famKey);
      if (subfamBody) subfamBody.classList.toggle('open', anyFamVisible);
      if (subfamChev) subfamChev.classList.toggle('closed', !anyFamVisible);
    }
  }
  const biasEmptyEl = document.getElementById('ref-empty-biases');
  if (biasEmptyEl) biasEmptyEl.style.display = (query && !anyBiasVisible) ? 'block' : 'none';
  if (query && anyBiasVisible) {
    const body = document.getElementById('ref-body-biases');
    const chev = document.getElementById('ref-chev-biases');
    if (body) body.classList.add('open');
    if (chev) chev.classList.remove('closed');
  }
}

// --- Selection ---
function selectNode(node) {
  clearChainHighlight();
  clearHighlight(selectedCell);
  selectedCell = node;
  node.attr('body/stroke', '#f6ad55');
  node.attr('body/strokeWidth', 2.5);
  const d = node.getData() || {};
  document.getElementById('edit-type').value    = d.type    || 'normative_premise';
  document.getElementById('edit-content').value = d.content || '';
  document.getElementById('edit-notes').value   = d.notes   || '';
  showNodePanel();
  highlightChain(node);
}

function selectEdge(edge) {
  clearChainHighlight();
  clearHighlight(selectedCell);
  selectedCell = edge;
  edge.attr('line/strokeWidth', edge.attr('line/strokeWidth') * 1.6 || 3);
  const d = edge.getData() || {};
  const s = d.strength !== undefined ? d.strength : 0.5;
  document.getElementById('edit-relation').value  = d.relation || 'supports';
  document.getElementById('edit-strength').value  = s;
  document.getElementById('strength-val').textContent = parseFloat(s).toFixed(2);
  document.getElementById('edit-rule').value          = d.rule          || '';
  document.getElementById('edit-rule-reason').value   = d.rule_reason   || '';
  document.getElementById('edit-validity').value      = d.validity      || 'unknown';
  document.getElementById('edit-bias-label').value    = d.bias_label    || '';
  document.getElementById('edit-bias-reason').value   = d.bias_reason   || '';
  document.getElementById('edit-fallacy-label').value = d.fallacy_label || '';
  document.getElementById('edit-fallacy-reason').value= d.fallacy_reason|| '';
  showEdgePanel();
  highlightChainEdge(edge);
}

function clearHighlight(cell) {
  if (!cell) return;
  if (cell.isNode()) { cell.attr('body/stroke', 'none'); cell.attr('body/strokeWidth', 0); }
  if (cell.isEdge()) {
    const d = cell.getData() || {};
    cell.attr('line/strokeWidth', strengthToWidth(d.strength));
  }
}

function deselect() {
  clearChainHighlight();
  clearHighlight(selectedCell);
  selectedCell = null;
  showRefBrowser();
}

// --- Chain highlight ---
var _chainHighlighted = false;

function _getChainCells(node) {
  const nodeSet = new Set([node.id]);
  const edgeSet = new Set();

  // Upstream: all nodes/edges that feed into this node (recursively)
  const upQueue = [node];
  while (upQueue.length) {
    const cur = upQueue.shift();
    for (const edge of (graph.getIncomingEdges(cur) || [])) {
      edgeSet.add(edge.id);
      const src = graph.getCellById(edge.getSourceCellId());
      if (src && src.isNode() && !nodeSet.has(src.id)) {
        nodeSet.add(src.id);
        upQueue.push(src);
      }
    }
  }

  // Downstream: all nodes/edges this node feeds into (recursively, toward C1)
  const downQueue = [node];
  while (downQueue.length) {
    const cur = downQueue.shift();
    for (const edge of (graph.getOutgoingEdges(cur) || [])) {
      edgeSet.add(edge.id);
      const tgt = graph.getCellById(edge.getTargetCellId());
      if (tgt && tgt.isNode() && !nodeSet.has(tgt.id)) {
        nodeSet.add(tgt.id);
        downQueue.push(tgt);
      }
    }
  }

  return { nodeSet, edgeSet };
}

function _applyChainHighlight(nodeSet, edgeSet) {
  for (const n of graph.getNodes()) {
    const view = graph.findViewByCell(n);
    if (view) view.container.style.opacity = nodeSet.has(n.id) ? '' : '0.1';
  }
  for (const e of graph.getEdges()) {
    const view = graph.findViewByCell(e);
    if (view) view.container.style.opacity = edgeSet.has(e.id) ? '' : '0.07';
  }
  _chainHighlighted = true;
}

function highlightChain(node) {
  const { nodeSet, edgeSet } = _getChainCells(node);
  _applyChainHighlight(nodeSet, edgeSet);
}

function highlightChainEdge(edge) {
  // Chain = upstream from source + downstream from target.
  // _getChainCells on the source already covers both directions,
  // including the clicked edge and everything past the target.
  const srcNode = graph.getCellById(edge.getSourceCellId());
  const tgtNode = graph.getCellById(edge.getTargetCellId());
  const nodeSet = new Set();
  const edgeSet = new Set([edge.id]);
  for (const startNode of [srcNode, tgtNode]) {
    if (!startNode || !startNode.isNode()) continue;
    const { nodeSet: ns, edgeSet: es } = _getChainCells(startNode);
    for (const id of ns) nodeSet.add(id);
    for (const id of es) edgeSet.add(id);
  }
  _applyChainHighlight(nodeSet, edgeSet);
}

function clearChainHighlight() {
  if (!_chainHighlighted) return;
  for (const n of graph.getNodes()) {
    const view = graph.findViewByCell(n);
    if (view) view.container.style.opacity = '';
  }
  for (const e of graph.getEdges()) {
    const view = graph.findViewByCell(e);
    if (view) view.container.style.opacity = '';
  }
  _chainHighlighted = false;
}

// --- Update ---
function updateNode() {
  if (!selectedCell || !selectedCell.isNode()) return;
  _pushUndo();
  const type    = document.getElementById('edit-type').value;
  const content = document.getElementById('edit-content').value;
  const notes   = document.getElementById('edit-notes').value;
  const isJoiner = type === 'linked_joiner';
  selectedCell.setData({ type, content, notes });
  selectedCell.attr('body/fill',      NODE_COLORS[type] || '#aaa');
  selectedCell.attr('body/rx',        isJoiner ? selectedCell.getSize().width / 2 : 6);
  selectedCell.attr('body/ry',        isJoiner ? selectedCell.getSize().height / 2 : 6);
  const wrapped = isJoiner ? '∧' : wrapText(content);
  selectedCell.attr('label/text',     wrapped);
  selectedCell.attr('label/fontSize', isJoiner ? 16 : 11);
  if (!isJoiner) {
    const nLines = wrapped.split('\\n').length;
    selectedCell.resize(220, Math.max(55, nLines * 16 + 24));
  }
}

function onStrengthInput(val) {
  document.getElementById('strength-val').textContent = parseFloat(val).toFixed(2);
  if (selectedCell && selectedCell.isEdge()) {
    const d = selectedCell.getData() || {};
    const stroke = EDGE_COLORS[d.relation] || '#a0aec0';
    selectedCell.attr('line/strokeWidth',  strengthToWidth(val) * 1.6);
    selectedCell.attr('line/targetMarker', markerFor(stroke, val));
  }
}

function updateEdge() {
  if (!selectedCell || !selectedCell.isEdge()) return;
  _pushUndo();
  const relation = document.getElementById('edit-relation').value;
  const strength = parseFloat(document.getElementById('edit-strength').value);
  const rule           = document.getElementById('edit-rule').value;
  const rule_reason    = document.getElementById('edit-rule-reason').value;
  const validity       = document.getElementById('edit-validity').value;
  const bias_label     = document.getElementById('edit-bias-label').value;
  const bias_reason    = document.getElementById('edit-bias-reason').value;
  const fallacy_label  = document.getElementById('edit-fallacy-label').value;
  const fallacy_reason = document.getElementById('edit-fallacy-reason').value;
  selectedCell.setData({ relation, rule, rule_reason, validity,
                         bias_label, bias_reason, fallacy_label, fallacy_reason, strength });
  selectedCell.setAttrs(edgeAttrs(relation, validity, strength));
  selectedCell.attr('line/strokeWidth', strengthToWidth(strength) * 1.6);
  selectedCell.setLabels(makeEdgeLabels(rule, bias_label, fallacy_label));
}

function deleteSelected() {
  if (!selectedCell) return;
  _pushUndo();
  selectedCell.remove();
  selectedCell = null;
  showRefBrowser();
}

// --- Add node ---
const _NODE_ID_PREFIX = {
  claim:                   'C',
  normative_premise:       'N',
  empirical_premise:       'E',
  metaphysical_commitment: 'M',
  intermediate_conclusion: 'IC',
};

function _nextNodeId(type) {
  const prefix = _NODE_ID_PREFIX[type];
  if (!prefix) return 'new_' + (_nodeCounter++);
  const nums = graph.getNodes()
    .map(n => n.id)
    .filter(id => id.startsWith(prefix) && /^\d+$/.test(id.slice(prefix.length)))
    .map(id => parseInt(id.slice(prefix.length)));
  return prefix + ((nums.length ? Math.max(...nums) : 0) + 1);
}

function addNode(type) {
  _pushUndo();
  const isJoiner = type === 'linked_joiner';
  const id    = isJoiner ? 'joiner_' + (_nodeCounter++) : _nextNodeId(type);
  const label = isJoiner ? '∧' : (T.x6_new_node_prefix + ' ' + (TYPE_LABELS[type] || type));
  const w     = isJoiner ? _JOINER_SIZE : 220;
  const h     = isJoiner ? _JOINER_SIZE : 55;
  const node  = graph.addNode(makeNodeDef(
    { id, type, content: label, notes: '', width: w, height: h }, { x: 80, y: 80 }
  ));
  selectNode(node);
  if (type === 'claim') setTimeout(function() { addClaimRipple(node); }, 50);
}

// --- Connect mode ---
function setMode(m) {
  mode = m;
  document.getElementById('btn-select').classList.toggle('active',  m === 'select');
  document.getElementById('btn-connect').classList.toggle('active', m === 'connect');
  document.getElementById('mode-hint').style.display = m === 'connect' ? 'inline' : 'none';
  if (m === 'select' && connectSource) {
    connectSource.attr('body/stroke', 'none');
    connectSource.attr('body/strokeWidth', 0);
    connectSource = null;
  }
}

function setRouter(name) {
  EDGE_ROUTER = { name: name };
  graph.getEdges().forEach(function(e) { e.setRouter(EDGE_ROUTER); });
}

function handleConnectClick(node) {
  if (!connectSource) {
    connectSource = node;
    node.attr('body/stroke', '#f6ad55');
    node.attr('body/strokeWidth', 2.5);
  } else if (connectSource === node) {
    node.attr('body/stroke', 'none'); node.attr('body/strokeWidth', 0);
    connectSource = null;
  } else {
    _pushUndo();
    graph.addEdge({
      id: 'edge_' + Date.now(),
      source: { cell: connectSource.id }, target: { cell: node.id },
      router: EDGE_ROUTER, connector: EDGE_CONNECTOR,
      attrs:  edgeAttrs('supports', 'unknown', 0.5),
      data:   { relation: 'supports', rule: '', validity: 'unknown',
                bias: '', fallacy: '', strength: 0.5 },
      zIndex: 0,
    });
    connectSource.attr('body/stroke', 'none');
    connectSource.attr('body/strokeWidth', 0);
    connectSource = null;
    setMode('select');
  }
}

// ─── Guided construction ────────────────────────────────────────────────────
// A scaffolded, top-down wizard: start from a claim, repeatedly ask "what does
// this rest on?", add typed supports (live on the same graph), descend through
// intermediate conclusions, and soft-unlock free editing once the map holds at
// least one empirical and one normative premise. `direction` is reserved so a
// bottom-up variant can reuse this engine later.
var _guided = { active: false, direction: 'top_down', phase: 'idle',
                targetId: null, queue: [], round: [], selType: null };

// Order shown in the picker. Descriptions reuse the help-modal x6_nt_desc_* keys;
// examples are guided-specific. `leaf:false` means the type queues for justification.
var _GUIDED_TYPES = [
  { type: 'empirical_premise',       desc: 'x6_nt_desc_empirical',    ex: 'x6_guided_ex_empirical',    leaf: true  },
  { type: 'normative_premise',       desc: 'x6_nt_desc_normative',    ex: 'x6_guided_ex_normative',    leaf: true  },
  { type: 'intermediate_conclusion', desc: 'x6_nt_desc_intermediate', ex: 'x6_guided_ex_intermediate', leaf: false },
  { type: 'metaphysical_commitment', desc: 'x6_nt_desc_metaphysical', ex: 'x6_guided_ex_metaphysical', leaf: true  },
];

function escAttr(s) { return escHtml(s).replace(/"/g, '&quot;'); }

function startGuided() {
  _guided.active  = true;
  _guided.queue   = [];
  _guided.round   = [];
  _guided.selType = null;
  document.body.classList.add('guided');
  setMode('select');
  var claim = graph.getNodes().find(function(n) { return (n.getData() || {}).type === 'claim'; });
  if (claim) {
    _guided.targetId = claim.id;
    // A seeded template claim may carry a [PLACEHOLDER] for the student to fill.
    var ctext = (claim.getData() || {}).content || '';
    _guided.phase = /\[[^\]]+\]/.test(ctext) ? 'fill' : 'support';
    _guidedCenterTarget();
  } else {
    _guided.phase = 'claim'; _guided.targetId = null;
  }
  renderGuided();
}

// Replace a node's content + visible label (mirrors updateNode's content path).
function _guidedSetContent(node, content) {
  var d = node.getData() || {};
  node.setData({ type: d.type, content: content, notes: d.notes || '' });
  var wrapped = wrapText(content);
  node.attr('label/text', wrapped);
  node.resize(220, Math.max(55, wrapped.split('\\n').length * 16 + 24));
}

function guidedFillClaim() {
  var inp = document.getElementById('g-fill-input');
  var val = ((inp && inp.value) || '').trim();
  if (!val) { if (inp) inp.focus(); return; }
  _pushUndo();
  var node = graph.getCellById(_guided.targetId);
  if (node) {
    var cur = (node.getData() || {}).content || '';
    _guidedSetContent(node, cur.replace(/\[[^\]]+\]/, val));
  }
  _guided.phase = 'support';
  _guided.round = [];
  setTimeout(function() { addClaimRipple(node); _guidedCenterTarget(); }, 60);
  renderGuided();
}

function exitGuided() {
  _guided.active = false;
  _guided.phase  = 'idle';
  document.body.classList.remove('guided');
  setMode('select');
}

function _guidedHasType(type) {
  return graph.getNodes().some(function(n) { return (n.getData() || {}).type === type; });
}

function _guidedUnlockReady() {
  return _guidedHasType('empirical_premise') && _guidedHasType('normative_premise');
}

function _nodeContentById(id) {
  var n = graph.getCellById(id);
  return n ? ((n.getData() || {}).content || '') : '';
}

function _guidedCenterTarget() {
  var n = _guided.targetId ? graph.getCellById(_guided.targetId) : null;
  if (n) { try { graph.centerCell(n); } catch (e) {} }
}

// Create a node with explicit content, positioned below its current target.
function _guidedAddNode(type, content, notes, idx) {
  var id  = _nextNodeId(type);
  var tgt = _guided.targetId ? graph.getCellById(_guided.targetId) : null;
  var base = tgt ? tgt.position() : { x: 360, y: 80 };
  var pos  = tgt ? { x: base.x + (idx - 1) * 250, y: base.y + 150 } : { x: 360, y: 80 };
  return graph.addNode(makeNodeDef(
    { id: id, type: type, content: content, notes: notes || '', width: 220, height: 55 }, pos
  ));
}

function _guidedAddEdge(srcId, tgtId) {
  graph.addEdge({
    id: 'edge_' + Date.now() + '_' + Math.floor(Math.random() * 1000),
    source: { cell: srcId }, target: { cell: tgtId },
    router: EDGE_ROUTER, connector: EDGE_CONNECTOR,
    attrs:  edgeAttrs('supports', 'unknown', 0.5),
    data:   { relation: 'supports', rule: '', validity: 'unknown', bias: '', fallacy: '', strength: 0.5 },
    zIndex: 0,
  });
}

function guidedStartClaim() {
  var ta  = document.getElementById('g-claim-input');
  var txt = ((ta && ta.value) || '').trim();
  if (!txt) { if (ta) ta.focus(); return; }
  _pushUndo();
  _guided.targetId = null;
  var node = _guidedAddNode('claim', txt, '', 1);
  _guided.targetId = node.id;
  _guided.phase    = 'support';
  _guided.round    = [];
  setTimeout(function() { addClaimRipple(node); _guidedCenterTarget(); }, 60);
  renderGuided();
}

function guidedPickType(type) {
  _guided.selType = (_guided.selType === type) ? null : type;
  renderGuided();
  var c = document.getElementById('g-content-input');
  if (c) c.focus();
}

function guidedAddSupport() {
  if (!_guided.selType) return;
  var ci  = document.getElementById('g-content-input');
  var ni  = document.getElementById('g-notes-input');
  var txt = ((ci && ci.value) || '').trim();
  if (!txt) { if (ci) ci.focus(); return; }
  _pushUndo();
  var node = _guidedAddNode(_guided.selType, txt, ((ni && ni.value) || '').trim(), _guided.round.length + 1);
  _guidedAddEdge(node.id, _guided.targetId);
  _guided.round.push({ id: node.id, type: _guided.selType, content: txt });
  if (_guided.selType === 'intermediate_conclusion') _guided.queue.push(node.id);
  _guided.selType = null;
  renderGuided();
}

function guidedDoneNode() {
  if (_guided.round.length >= 2) { _guided.phase = 'link'; renderGuided(); return; }
  _guidedAdvance();
}

function guidedSetLinked(isLinked) {
  if (isLinked) _guidedMakeLinked(_guided.round.map(function(r) { return r.id; }), _guided.targetId);
  _guidedAdvance();
}

// Convert convergent edges (each source → target) into a co-dependent structure:
// route every source through a single ∧ joiner that then feeds the target.
function _guidedMakeLinked(srcIds, tgtId) {
  _pushUndo();
  graph.getEdges().forEach(function(e) {
    if (e.getTargetCellId() === tgtId && srcIds.indexOf(e.getSourceCellId()) !== -1) graph.removeEdge(e);
  });
  var jid  = 'joiner_' + (_nodeCounter++);
  var tgt  = graph.getCellById(tgtId);
  var base = tgt ? tgt.position() : { x: 360, y: 200 };
  graph.addNode(makeNodeDef(
    { id: jid, type: 'linked_joiner', content: '∧', notes: '', width: _JOINER_SIZE, height: _JOINER_SIZE },
    { x: base.x, y: base.y + 85 }
  ));
  srcIds.forEach(function(sid) { _guidedAddEdge(sid, jid); });
  _guidedAddEdge(jid, tgtId);
}

function _guidedAdvance() {
  _guided.round   = [];
  _guided.selType = null;
  if (_guided.queue.length) {
    _guided.targetId = _guided.queue.shift();
    _guided.phase    = 'support';
    _guidedCenterTarget();
  } else {
    _guided.phase = 'done';
  }
  renderGuided();
}

function _guidedChipsHtml() {
  var emp = _guidedHasType('empirical_premise'), norm = _guidedHasType('normative_premise');
  return '<div class="g-chips">' +
    '<div class="g-chip ' + (emp ? 'on' : '') + '">' + (emp ? '✓ ' : '') + escHtml(T.x6_guided_chip_emp) + '</div>' +
    '<div class="g-chip ' + (norm ? 'on' : '') + '">' + (norm ? '✓ ' : '') + escHtml(T.x6_guided_chip_norm) + '</div>' +
  '</div>';
}

function _guidedQueueHtml() {
  if (!_guided.queue.length) return '';
  var items = _guided.queue.map(function(id) { return '<li>' + escHtml(_nodeContentById(id)) + '</li>'; }).join('');
  return '<div class="g-queue"><strong>' + escHtml(T.x6_guided_queue_label) + '</strong>' +
         '<ul class="g-added">' + items + '</ul></div>';
}

function _guidedUnlockHtml() {
  var ready = _guidedUnlockReady();
  var note  = ready
    ? '<div class="g-help" style="color:#276749;margin-top:8px;text-align:center">' + escHtml(T.x6_guided_ready) + '</div>'
    : '<div class="g-help" style="margin-top:8px">' + escHtml(T.x6_guided_unlock_hint) + '</div>';
  return '<button class="g-btn g-btn-unlock' + (ready ? '' : ' muted') + '" style="margin-top:14px" ' +
         'onclick="exitGuided()">' + escHtml(T.x6_guided_unlock_btn) + '</button>' + note;
}

function renderGuided() {
  if (!_guided.active) return;
  var body = document.getElementById('guided-body');
  if (!body) return;
  var html = '';

  if (_guided.phase === 'fill') {
    var raw = _nodeContentById(_guided.targetId);
    var ph  = (raw.match(/\[[^\]]+\]/) || [''])[0];
    var preview = escHtml(raw).replace(escHtml(ph), '<span class="g-blank">' + escHtml(ph) + '</span>');
    html += _guidedChipsHtml();
    html += '<div class="g-card">';
    html += '<div class="g-q">' + escHtml(T.x6_guided_fill_prompt) + '</div>';
    html += '<div class="g-fill-preview">' + preview + '</div>';
    html += '<input type="text" id="g-fill-input" placeholder="' + escAttr(T.x6_guided_fill_ph) + '">';
    html += '<button class="g-btn g-btn-primary" onclick="guidedFillClaim()">' + escHtml(T.x6_guided_fill_btn) + '</button>';
    html += '</div>';
    body.innerHTML = html;
    var fi = document.getElementById('g-fill-input'); if (fi) fi.focus();
    return;
  }

  if (_guided.phase === 'claim') {
    html += _guidedChipsHtml();
    html += '<div class="g-card">';
    html += '<div class="g-q">' + escHtml(T.x6_guided_claim_prompt) + '</div>';
    html += '<div class="g-help">' + escHtml(T.x6_guided_claim_help) + '</div>';
    html += '<textarea id="g-claim-input" rows="3" placeholder="' + escAttr(T.x6_guided_claim_ph) + '"></textarea>';
    html += '<button class="g-btn g-btn-primary" onclick="guidedStartClaim()">' + escHtml(T.x6_guided_claim_btn) + '</button>';
    html += '</div>';
    body.innerHTML = html;
    var ci = document.getElementById('g-claim-input'); if (ci) ci.focus();
    return;
  }

  if (_guided.phase === 'support' || _guided.phase === 'link') {
    html += _guidedChipsHtml();
    html += '<div class="g-target"><div class="g-target-lbl">' + escHtml(T.x6_guided_justifying) + '</div>' +
            '<div class="g-target-txt">' + escHtml(_nodeContentById(_guided.targetId)) + '</div></div>';
  }

  if (_guided.phase === 'support') {
    html += '<div class="g-q">' + escHtml(T.x6_guided_support_q) + '</div>';
    html += '<div class="g-help">' + escHtml(T.x6_guided_pick_type) + '</div>';
    _GUIDED_TYPES.forEach(function(tp) {
      var sel = _guided.selType === tp.type;
      html += '<button class="g-type-btn' + (sel ? ' sel' : '') + '" data-type="' + tp.type +
              '" onclick="guidedPickType(this.dataset.type)">' + escHtml(TYPE_LABELS[tp.type] || tp.type) + '</button>';
      if (sel) {
        html += '<div class="g-type-desc">' + escHtml(T[tp.desc] || '') +
                '<span class="g-ex">' + escHtml(T[tp.ex] || '') + '</span></div>';
        html += '<textarea id="g-content-input" rows="2" placeholder="' + escAttr(T.x6_guided_content_ph) + '"></textarea>';
        html += '<textarea id="g-notes-input" rows="1" placeholder="' + escAttr(T.x6_guided_notes_ph) + '"></textarea>';
        html += '<button class="g-btn g-btn-primary" onclick="guidedAddSupport()">' + escHtml(T.x6_guided_add_btn) + '</button>';
      }
    });
    html += '<div class="g-card" style="margin-top:12px"><h3>' + escHtml(T.x6_guided_added) + '</h3>';
    if (_guided.round.length) {
      html += '<ul class="g-added">';
      _guided.round.forEach(function(r) {
        html += '<li><span class="g-dot" style="background:' + (NODE_COLORS[r.type] || '#aaa') + '"></span>' +
                escHtml(r.content) + '</li>';
      });
      html += '</ul>';
    } else {
      html += '<div class="g-help" style="margin:0">' + escHtml(T.x6_guided_none_yet) + '</div>';
    }
    html += '</div>';
    html += '<button class="g-btn g-btn-ghost" onclick="guidedDoneNode()"' +
            (_guided.round.length ? '' : ' disabled') + '>' + escHtml(T.x6_guided_done_node) + '</button>';
    html += _guidedQueueHtml();
    html += _guidedUnlockHtml();
  }

  if (_guided.phase === 'link') {
    html += '<div class="g-q">' + escHtml(T.x6_guided_link_q) + '</div>';
    html += '<div class="g-help">' + escHtml(T.x6_guided_link_explain) + '</div>';
    html += '<div class="g-link-row">';
    html += '<button class="g-btn g-btn-primary" onclick="guidedSetLinked(true)">' + escHtml(T.x6_guided_link_linked) + '</button>';
    html += '<button class="g-btn g-btn-ghost" onclick="guidedSetLinked(false)">' + escHtml(T.x6_guided_link_conv) + '</button>';
    html += '</div>';
  }

  if (_guided.phase === 'done') {
    html += _guidedChipsHtml();
    html += '<div class="g-card"><h3>' + escHtml(T.x6_guided_complete_t) + '</h3>' +
            '<div class="g-help" style="margin:0">' + escHtml(T.x6_guided_complete_b) + '</div></div>';
    html += _guidedQueueHtml();
    html += _guidedUnlockHtml();
  }

  body.innerHTML = html;
}

// --- Events ---
graph.on('node:click', ({ node }) => {
  hideTooltip();
  if (mode === 'connect') { handleConnectClick(node); return; }
  if (selectedCell === node) { deselect(); return; }
  selectNode(node);
});

graph.on('edge:click', ({ edge }) => {
  hideTooltip();
  if (mode === 'connect') return;
  if (selectedCell === edge) { deselect(); return; }
  selectEdge(edge);
});

graph.on('blank:click', () => {
  if (connectSource) {
    connectSource.attr('body/stroke', 'none');
    connectSource.attr('body/strokeWidth', 0);
    connectSource = null;
  }
  deselect();
});

// Node hover → show notes
graph.on('node:mouseenter', ({ node }) => {
  const d = node.getData() || {};
  if (!d.notes) return;
  showTooltip('<div class="tt-label">Notes</div>' + escHtml(d.notes));
});
graph.on('node:mouseleave', hideTooltip);

// Edge hover → show bias / fallacy
graph.on('edge:mouseenter', ({ edge }) => {
  const d = edge.getData() || {};
  const lines = [];
  if (d.bias_label) {
    let s = '<span class="tt-warn">⚠ ' + escHtml(d.bias_label) + '</span>';
    if (d.bias_reason) s += '<br><span style="color:#fbd38d;font-size:10px">' + escHtml(d.bias_reason) + '</span>';
    lines.push(s);
  }
  if (d.fallacy_label) {
    let s = '<span class="tt-err">⚠ ' + escHtml(d.fallacy_label) + '</span>';
    if (d.fallacy_reason) s += '<br><span style="color:#fc8181;font-size:10px">' + escHtml(d.fallacy_reason) + '</span>';
    lines.push(s);
  }
  if (!lines.length) return;
  showTooltip(lines.join('<br><br>'));
});
graph.on('edge:mouseleave', hideTooltip);

// --- Keyboard shortcuts ---
document.addEventListener('keydown', function(e) {
  const tag = (document.activeElement || {}).tagName || '';
  const inField = ['TEXTAREA', 'INPUT', 'SELECT'].includes(tag) ||
                  !!(document.activeElement || {}).isContentEditable;
  if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
    if (!inField) { e.preventDefault(); undo(); }
    return;
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
    if (!inField) { e.preventDefault(); redo(); }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey || inField) return;
  if (e.key === 'Delete' || e.key === 'Backspace') { deleteSelected(); return; }
  if (e.key === 'Escape') { if (mode === 'connect') setMode('select'); else deselect(); return; }
  if (e.key === 'c' || e.key === 'C') { e.preventDefault(); setMode(mode === 'connect' ? 'select' : 'connect'); return; }
  const NODE_KEYS = { t: 'claim', n: 'normative_premise', e: 'empirical_premise',
                      m: 'metaphysical_commitment', i: 'intermediate_conclusion', j: 'linked_joiner' };
  const nodeType = NODE_KEYS[e.key.toLowerCase()];
  if (nodeType) { e.preventDefault(); addNode(nodeType); }
});

// --- Export ---
function exportJSON() {
  const state = _captureState();
  state.id = 'exported';
  triggerDownload(
    URL.createObjectURL(new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' })),
    'argument_map.json'
  );
}

// --- Image / file export helpers ---
function triggerDownload(href, filename) {
  const a = Object.assign(document.createElement('a'), { href: href, download: filename });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function _getGraphSVG() {
  const svgEl = container.querySelector('svg');
  if (!svgEl) return null;
  const w = container.clientWidth;
  const h = container.clientHeight;
  const clone = svgEl.cloneNode(true);
  clone.setAttribute('width', w);
  clone.setAttribute('height', h);
  if (!clone.getAttribute('viewBox'))
    clone.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
  return { clone: clone, w: w, h: h };
}

function exportSVG() {
  const r = _getGraphSVG();
  if (!r) { alert('No SVG found.'); return; }
  const svgStr = '<?xml version="1.0" encoding="UTF-8"?>\\n' +
                 new XMLSerializer().serializeToString(r.clone);
  triggerDownload(
    URL.createObjectURL(new Blob([svgStr], { type: 'image/svg+xml' })),
    'argument_map.svg'
  );
}

function exportPNG() {
  const r = _getGraphSVG();
  if (!r) { alert('No SVG found.'); return; }
  const svgStr = new XMLSerializer().serializeToString(r.clone);
  const url = URL.createObjectURL(new Blob([svgStr], { type: 'image/svg+xml' }));
  const scale = 2;
  const canvas = document.createElement('canvas');
  canvas.width  = r.w * scale;
  canvas.height = r.h * scale;
  const ctx = canvas.getContext('2d');
  ctx.scale(scale, scale);
  ctx.fillStyle = '#f0f2f5';
  ctx.fillRect(0, 0, r.w, r.h);
  const img = new Image();
  img.onload = function() {
    ctx.drawImage(img, 0, 0, r.w, r.h);
    URL.revokeObjectURL(url);
    triggerDownload(canvas.toDataURL('image/png'), 'argument_map.png');
  };
  img.onerror = function() {
    URL.revokeObjectURL(url);
    alert('PNG export failed — try Export SVG instead.');
  };
  img.src = url;
}

// --- Import JSON ---
function importJSON() {
  const input = Object.assign(document.createElement('input'), {
    type: 'file', accept: '.json'
  });
  input.onchange = function(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function(ev) {
      try {
        _pushUndo();
        rebuildFromMap(JSON.parse(ev.target.result));
      } catch(err) {
        alert('Invalid JSON: ' + err.message);
      }
    };
    reader.readAsText(file);
  };
  input.click();
}

function rebuildFromMap(map) {
  graph.clearCells();
  selectedCell = null;
  connectSource = null;
  showRefBrowser();

  const nodesData = [];
  const edgesData = [];

  for (const node of (map.nodes || [])) {
    const label  = wrapText(node.content || '');
    const nLines = label.split('\\n').length;
    nodesData.push({
      id: node.id, type: node.type, content: node.content,
      label: label, notes: node.notes || '',
      width:  node.type === 'linked_joiner' ? _JOINER_SIZE : 220,
      height: node.type === 'linked_joiner' ? _JOINER_SIZE : Math.max(55, nLines * 16 + 24),
    });
  }

  for (const step of (map.steps || [])) {
    const ann = step.annotation || {};
    const validity = ann.valid === true ? 'valid' : ann.valid === false ? 'invalid' : 'unknown';
    const base = {
      step_id: step.id, relation: step.relation || 'supports',
      rule: step.rule || '', rule_reason: step.rule_reason || '',
      validity: validity,
      bias_label: ann.bias_label || '', bias_reason: ann.bias_reason || '',
      fallacy_label: ann.fallacy_label || '', fallacy_reason: ann.fallacy_reason || '',
      strength: step.strength || 0.5,
    };
    if (step.linked) {
      const joinerId = 'joiner_' + step.id;
      nodesData.push({ id: joinerId, type: 'linked_joiner',
                       content: 'Both premises required', notes: '',
                       width: _JOINER_SIZE, height: _JOINER_SIZE });
      (step.sources || []).forEach(function(src, i) {
        edgesData.push(Object.assign({}, base, { id: step.id + '_in_' + i,
                        source: src, target: joinerId,
                        rule: '', bias_label: '', fallacy_label: '',
                        bias_reason: '', fallacy_reason: '' }));
      });
      if (step.target) {
        edgesData.push(Object.assign({}, base, { id: step.id + '_out',
                        source: joinerId, target: step.target }));
      }
    } else {
      (step.sources || []).forEach(function(src, i) {
        edgesData.push(Object.assign({}, base, { id: step.id + '_' + i,
                        source: src, target: step.target }));
      });
    }
  }

  const positions = computeLayout(nodesData, edgesData);
  for (const n of nodesData) {
    const pos = (map._layout && map._layout[n.id]) || positions[n.id] || { x: 60, y: 60 };
    graph.addNode(makeNodeDef(n, pos));
  }
  for (const e of edgesData) {
    graph.addEdge({
      id: e.id, source: { cell: e.source }, target: { cell: e.target },
      router: EDGE_ROUTER, connector: EDGE_CONNECTOR,
      attrs:  edgeAttrs(e.relation, e.validity, e.strength),
      labels: makeEdgeLabels(e.rule, e.bias_label, e.fallacy_label),
      data:   { relation: e.relation, rule: e.rule, rule_reason: e.rule_reason,
                validity: e.validity,
                bias_label: e.bias_label, bias_reason: e.bias_reason,
                fallacy_label: e.fallacy_label, fallacy_reason: e.fallacy_reason,
                strength: e.strength || 0.5 },
      zIndex: 0,
    });
  }
  setTimeout(function() { graph.centerContent(); addClaimRipple(); }, 80);
}

// --- Clear all ---
function clearAll() {
  if (!confirm('Clear all nodes and edges? This cannot be undone.')) return;
  _pushUndo();
  graph.clearCells();
  selectedCell  = null;
  connectSource = null;
  showRefBrowser();
}

// --- Help modal ---
function openHelp()  { document.getElementById('help-overlay').classList.add('open'); }
function closeHelp() { document.getElementById('help-overlay').classList.remove('open'); }


// --- Z-order: label chips always on top ---
function _bringLabelsToFront() {
  // In SVG, z-order = DOM order. Reorder within each element's parent:
  // unlabeled edges first (go below), labeled edges last (go above).
  function _move(cell) {
    const view = graph.findViewByCell(cell);
    if (view && view.container && view.container.parentNode)
      view.container.parentNode.appendChild(view.container);
  }
  const edges = graph.getEdges();
  edges.forEach(function(e) {
    const d = e.getData() || {};
    if (!d.rule && !d.bias_label && !d.fallacy_label) _move(e);
  });
  edges.forEach(function(e) {
    const d = e.getData() || {};
    if (d.rule || d.bias_label || d.fallacy_label) _move(e);
  });
  graph.getNodes().forEach(_move);
}

// --- Panel toggle ---
function _syncGraphBounds() {
  const gc = document.getElementById('graph-container');
  gc.style.left  = _leftVisible  ? _LEFT_W  + 'px' : '0';
  gc.style.right = _rightVisible ? _RIGHT_W + 'px' : '0';
}

function toggleLeftPanel() {
  _leftVisible = !_leftVisible;
  document.getElementById('add-panel').style.display = _leftVisible ? '' : 'none';
  const tab = document.getElementById('left-panel-toggle');
  tab.innerHTML = _leftVisible ? '&#x25C4;' : '&#x25BA;';
  tab.style.left = _leftVisible ? _LEFT_W + 'px' : '0';
  _syncGraphBounds();
}

function toggleRightPanel() {
  _rightVisible = !_rightVisible;
  document.getElementById('edit-panel').style.display = _rightVisible ? '' : 'none';
  const tab = document.getElementById('right-panel-toggle');
  tab.innerHTML = _rightVisible ? '&#x25BA;' : '&#x25C4;';
  tab.style.right = _rightVisible ? _RIGHT_W + 'px' : '0';
  _syncGraphBounds();
}

// --- Panel resize ---
document.getElementById('panel-resize-handle').addEventListener('mousedown', function(e) {
  _resizing     = true;
  _resizeStartX = e.clientX;
  _resizeStartW = document.getElementById('edit-panel').offsetWidth;
  this.classList.add('dragging');
  e.preventDefault();
});

document.addEventListener('mousemove', function(e) {
  if (!_resizing) return;
  const delta    = _resizeStartX - e.clientX;
  _RIGHT_W       = Math.max(_MIN_RIGHT_W, Math.min(_MAX_RIGHT_W, _resizeStartW + delta));
  const panel    = document.getElementById('edit-panel');
  const gc       = document.getElementById('graph-container');
  panel.style.width = _RIGHT_W + 'px';
  if (_rightVisible) {
    gc.style.right = _RIGHT_W + 'px';
    document.getElementById('right-panel-toggle').style.right = _RIGHT_W + 'px';
  }
});

document.addEventListener('mouseup', function() {
  if (!_resizing) return;
  _resizing = false;
  document.getElementById('panel-resize-handle').classList.remove('dragging');
});

renderAll();

if (typeof GUIDED_START !== 'undefined' && GUIDED_START) setTimeout(startGuided, 120);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_html_x6(argmap: Union[ArgumentMapV2, dict], output_path: Optional[str] = None, return_html: bool = False, lang: str = 'en', guided: bool = False) -> str:
    """Generate a standalone interactive X6 HTML visualizer.

    If return_html=True, always returns the HTML string (ignores output_path).
    If output_path is set and return_html=False, writes to file and returns the string.
    lang: ISO language code ('en' or 'it'); controls UI string translations.
    guided: when True, the viewer starts in guided-construction mode.
    """
    if isinstance(argmap, ArgumentMapV2):
        argmap = argmap.model_dump()
    if not argmap:
        argmap = {"title": "Argument Map", "nodes": [], "steps": []}
    data  = to_x6_data(argmap)
    title = _html.escape(argmap.get("title", "Argument Map"))

    schemes = {}
    if _SCHEMES_PATH.exists():
        with open(_SCHEMES_PATH, encoding='utf-8') as f:
            schemes = json.load(f)

    # _layout stores per-node {x, y} positions from the last save, keyed by node ID.
    # Passed as JSON so the JS can restore exact positions instead of recomputing layout.
    layout = argmap.get("_layout") or {}
    t      = _get_x6_t(lang)

    # Sentinel substitution: each AUTOMAP_* token is replaced with JSON-encoded data.
    # These tokens are chosen to be collision-free with any realistic academic text.
    result = (_HTML
              .replace("AUTOMAP_NODES_JSON",   json.dumps(data["nodes"],   ensure_ascii=False))
              .replace("AUTOMAP_EDGES_JSON",   json.dumps(data["edges"],   ensure_ascii=False))
              .replace("AUTOMAP_SCHEMES_JSON", json.dumps(schemes,         ensure_ascii=False))
              .replace("AUTOMAP_LAYOUT_JSON",  json.dumps(layout,          ensure_ascii=False))
              .replace("AUTOMAP_T_JSON",        json.dumps(t,              ensure_ascii=False))
              .replace("AUTOMAP_GUIDED",        "true" if guided else "false")
              .replace("AUTOMAP_LANG",          lang)
              .replace("AUTOMAP_TITLE",         title))
    if output_path and not return_html:
        Path(output_path).write_text(result, encoding="utf-8")
    return result
