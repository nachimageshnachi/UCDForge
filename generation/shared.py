"""

Shared utilities for the UCD Generation wizard.



Extracted from the original monolithic ucd_generation.py so that every step

module can import exactly what it needs without circular dependencies.

"""



import re

import json

import streamlit as st

import streamlit.components.v1 as components

import pandas as pd

import nltk

from nltk import pos_tag, word_tokenize

from nltk.stem import WordNetLemmatizer



from helpers_old import get_db_values, reverse_lookup, TextValidationTools  # type: ignore

from embeddings import embed_paragraph, embed_short  # type: ignore





# ---------------------------------------------------------------------------

# Deduplication

# ---------------------------------------------------------------------------



def dedupe(seq):

    """Case-insensitive, order-preserving deduplication of strings."""

    seen = set()

    out = []

    for x in seq or []:

        s = (x or "").strip()

        if not s:

            continue

        k = s.lower()

        if k in seen:

            continue

        seen.add(k)

        out.append(s)

    return out





# ---------------------------------------------------------------------------

# Color management

# ---------------------------------------------------------------------------



PALETTE = [

    "#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e",

    "#e6ab02", "#a6761d", "#666666", "#1f78b4", "#b15928",

    "#6aa9ff", "#33a02c", "#6a3d9a", "#ff7f00", "#b2df8a",

]





def ensure_actor_colors(actors_list):

    if "ucd_actor_colors" not in st.session_state:

        st.session_state.ucd_actor_colors = {}

    color_map = dict(st.session_state.ucd_actor_colors)

    used = set(color_map.values())

    palette_idx = 0

    for name in actors_list:

        if name in color_map:

            continue

        while palette_idx < len(PALETTE) and PALETTE[palette_idx] in used:

            palette_idx += 1

        color = PALETTE[palette_idx % len(PALETTE)]

        palette_idx += 1

        color_map[name] = color

        used.add(color)

    st.session_state.ucd_actor_colors = color_map

    return color_map





def ensure_uc_colors(uc_list):

    if "ucd_uc_colors" not in st.session_state:

        st.session_state.ucd_uc_colors = {}

    color_map = dict(st.session_state.ucd_uc_colors)

    used = set(color_map.values())

    palette_idx = 0

    for name in uc_list:

        if name in color_map:

            continue

        while palette_idx < len(PALETTE) and PALETTE[palette_idx] in used:

            palette_idx += 1

        color = PALETTE[palette_idx % len(PALETTE)]

        palette_idx += 1

        color_map[name] = color

        used.add(color)

    st.session_state.ucd_uc_colors = color_map

    return color_map





# ---------------------------------------------------------------------------

# DB-backed suggestion lists (cached)

# ---------------------------------------------------------------------------



@st.cache_data(show_spinner=False)

def load_db_values():

    try:

        return get_db_values() or {}

    except Exception:

        return {}





@st.cache_data(show_spinner=False)

def build_suggestion_lists(db_values):

    def _ensure_nltk():

        try:

            pos_tag(["test"])

            word_tokenize("test")

        except LookupError:

            for res in ('punkt', 'averaged_perceptron_tagger', 'wordnet'):

                try:

                    nltk.download(res, quiet=True)

                except Exception:

                    pass



    _ensure_nltk()

    _lemmatizer = WordNetLemmatizer()



    ACRONYM = re.compile(r'^[A-Z]{2,}S?$')

    PRONOUN_TAGS = {"PRP", "PRP$", "WP", "WP$", "EX"}

    INDEFINITE = {"anyone", "anybody", "someone", "somebody",

                  "everyone", "everybody", "nobody", "none"}



    def _tokens_tags(s: str):

        try:

            toks = [t for t in word_tokenize(s) if re.search(r"\w", t)]

            lower = [t.lower() for t in toks]

            tags = pos_tag(lower) if lower else []

            return list(zip(toks, [t for _, t in tags]))

        except Exception:

            toks = [t for t in re.split(r"\s+", s.strip()) if t]

            return [(t, "NN") for t in toks]



    def _is_valid_actor_phrase(name: str) -> bool:

        if not name or not name.strip():

            return False

        pairs = _tokens_tags(name)

        if not pairs:

            return False

        if any(tag in PRONOUN_TAGS for _, tag in pairs):

            return False

        if any(tok.lower() in INDEFINITE for tok, _ in pairs):

            return False

        last_tok, last_tag = pairs[-1]

        if ACRONYM.fullmatch(last_tok or ""):

            return True

        if last_tag in {"NNS", "NNP", "NNPS"}:

            return False

        try:

            lemma = _lemmatizer.lemmatize((last_tok or '').lower(), 'n')

            if (last_tok or '').lower().endswith('s') and lemma != (last_tok or '').lower():

                return False

        except Exception:

            pass

        return last_tag == "NN"



    def _is_valid_uc_title(title: str) -> bool:

        if not title or not title.strip():

            return False

        pairs = _tokens_tags(title)

        if not pairs:

            return False

        first_tok, first_tag = pairs[0]

        if first_tag not in {"VB", "VBP"}:

            return False

        last_tok, last_tag = pairs[-1]

        if last_tag not in {"NN", "NNS", "NNP", "NNPS"}:

            return False

        if all(not tag.startswith("VB") for _, tag in pairs[:-1]):

            tags_only = [tag for _, tag in pairs]

            if set(tags_only) == {"NN"} and len(pairs) >= 2:

                return True

            return False

        return True



    def build(expanded_dict, kind: str):

        items_all = set()

        canon_names = []

        for readable, data in (expanded_dict or {}).items():

            nm = TextValidationTools.normalize(readable)

            if nm:

                items_all.add(nm)

                canon_names.append(nm)

            for s in data.get("synonyms", []) or []:

                sn = TextValidationTools.normalize(s)

                if sn:

                    items_all.add(sn)

        if kind == 'actor':

            filtered = [x for x in items_all if _is_valid_actor_phrase(x)]

        else:

            filtered = [x for x in items_all if _is_valid_uc_title(x)]

            if not filtered and canon_names:

                filtered = canon_names

        return sorted(dict.fromkeys(filtered))



    actors_expanded = (db_values or {}).get("actors", {})

    ucs_expanded = (db_values or {}).get("use_cases", {})

    return build(actors_expanded, 'actor'), build(ucs_expanded, 'uc')





# ---------------------------------------------------------------------------

# SVG Renderers

# ---------------------------------------------------------------------------



def render_match_svg(actors_list, use_cases_list, pairs_list, visible, colors):

    """Render actor --- use-case matching SVG with colored connection lines."""

    left_items = actors_list

    right_items = use_cases_list

    n = max(len(left_items), len(right_items), 1)

    row_h = 38

    pad = 8

    legend_h = 32 if left_items else 0

    label_h = 26

    height = legend_h + label_h + n * row_h



    def _y(idx):

        return legend_h + label_h + row_h * idx + row_h // 2



    left_rows = []

    for i in range(n):

        if i < len(left_items):

            name = left_items[i]

            color = colors.get(name, "#666666")

            dim = "0.35" if (visible and name not in visible) else "1.0"

            left_rows.append(

                f'<div class="item" title="{name}" style="opacity:{dim}"><span class="chip" style="background:{color}"></span>{i+1}. {name}</div>'

            )

        else:

            left_rows.append('<div class="item" title=""></div>')

    left_html = "".join(left_rows)



    right_rows = []

    for i in range(n):

        if i < len(right_items):

            name = right_items[i]

            right_rows.append(f'<div class="item" title="{name}">{i+1}. {name}</div>')

        else:

            right_rows.append('<div class="item" title=""></div>')

    right_html = "".join(right_rows)



    lines_svg = []

    for ai, ui in pairs_list:

        if ai < len(left_items) and ui < len(right_items):

            x1 = "45%"

            y1 = _y(ai)

            x2 = "55%"

            y2 = _y(ui)

            stroke = colors.get(left_items[ai], "#666666")

            opacity = "1.0" if (not visible or left_items[ai] in visible) else "0.15"

            lines_svg.append(
                f'<g><circle cx="{x1}" cy="{y1}" r="3" fill="{stroke}" fill-opacity="{opacity}" />'
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-opacity="{opacity}" stroke-width="2" stroke-linecap="round" />'
                f'<circle cx="{x2}" cy="{y2}" r="3" fill="{stroke}" fill-opacity="{opacity}" /></g>'
            )

    legend_items = "".join(
        f'<div class="legend-item"><span class="chip" style="background:{colors.get(actor_name, "#666666")}"></span>{actor_name}</div>'
        for actor_name in left_items
    )

    html = f"""
    <style>
      .match-wrap {{ position: relative; width: 100%; }}
      .cols {{ display: flex; justify-content: space-between; }}
      .col {{ width: 45%; }}
      .item {{ height: {row_h}px; display: flex; align-items: center; border-bottom: 1px solid #eee; font-family: sans-serif; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .label {{ font-weight: 600; height: {label_h}px; margin: 0; display: flex; align-items: center; font-family: sans-serif; }}
      .chip {{ width: 10px; height: 10px; display: inline-block; margin-right: 8px; border-radius: 2px; }}
      .legend {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; height: {legend_h}px; margin-bottom: 0; font-family: sans-serif; font-size: 12px; }}
      .legend-item {{ display: flex; align-items: center; gap: 6px; }}
    </style>
    <div class="match-wrap" style="padding: 0 {pad}px;">
      <div class="legend">{legend_items}</div>
      <div class="cols">
        <div class="col">
          <div class="label">Actors</div>
          {left_html}
        </div>
        <div class="col">
          <div class="label">Use Cases</div>
          {right_html}
        </div>
      </div>
      <svg width="100%" height="{height}" style="position:absolute; top:0; left:0; pointer-events:none;">
        {''.join(lines_svg)}
      </svg>
    </div>
    """
    components.html(html, height=height + 20)





def render_uc_uc_svg(ucs_left, ucs_right, pairs_list,

                     stroke_color="#6aa9ff", dash="", labels=None,

                     key="sec", color_map=None):

    """Render use-case --- use-case (or actor --- actor) matching SVG with

    trunk-and-branch layout powered by inline JS."""

    left_items = ucs_left

    right_items = ucs_right

    n = max(len(left_items), len(right_items), 1)

    row_h = 30

    pad = 8

    label_h = 24

    legend_h = 32

    extra_pad = 60

    y_base = legend_h + label_h - row_h

    height = legend_h + label_h + n * row_h + extra_pad

    iframe_h = height



    import json as _json

    uc_colors = color_map or ensure_uc_colors(left_items)

    color_for_pair = []

    for (si, ti) in pairs_list:

        if 0 <= si < len(left_items):

            color_for_pair.append(uc_colors.get(left_items[si], stroke_color))

        else:

            color_for_pair.append(stroke_color)



    left_html_parts = []

    for i, name in enumerate(left_items):

        col = uc_colors.get(name, "#666666")

        left_html_parts.append(

            f'<div id="ucl_{key}_{i}" class="uc-item" title="{name}"><span class="chip" style="background:{col}"></span>{i+1}. {name}</div>'

        )

    left_html = "".join(left_html_parts)

    right_html = "".join(

        f'<div id="ucr_{key}_{i}" class="uc-item" title="{name}">{i+1}. {name}</div>' for i, name in enumerate(right_items)

    )

    pairs_json = _json.dumps(pairs_list)

    colors_json = _json.dumps(color_for_pair)

    labels_json = _json.dumps(labels or {})



    legend_items = "".join(

        f'<div class="legend-item"><span class="chip" style="background:{uc_colors.get(n, "#666666")}"></span>{n}</div>'

        for n in left_items

    )



    # Column labels

    left_label = "Use Cases (Left)"

    right_label = "Use Cases (Right)"

    if key == "inc":

        left_label = "Base Use Case"

        right_label = "Included Use Case"

    elif key == "ext":

        left_label = "Extension Use Case"

        right_label = "Base Use Case"

    elif key == "ucg":

        left_label = "Child Use Cases"

        right_label = "Parent Use Cases"

    elif key == "actg":

        left_label = "Child Actors"

        right_label = "Parent Actors"



    # Fallback straight lines SVG

    fallback_lines = []

    for (si, ti) in pairs_list:

        if 0 <= si < len(left_items) and 0 <= ti < len(right_items):

            _col = (color_map or uc_colors).get(left_items[si], stroke_color)

            _y1 = y_base + row_h * si + row_h // 2

            _y2 = y_base + row_h * ti + row_h // 2

            _lbl = (labels or {}).get(f"{si}|{ti}", "")

            fallback_lines.append(

                f'<g>'

                f'<circle cx="45%" cy="{_y1}" r="3" fill="{_col}" />'

                f'<line x1="45%" y1="{_y1}" x2="55%" y2="{_y2}" stroke="{_col}" stroke-width="2" stroke-linecap="round" />'

                f'<circle cx="55%" cy="{_y2}" r="3" fill="{_col}" />'

                + (f'<text x="50%" y="{(_y1+_y2)/2 - 6}" text-anchor="middle" style="font-family:sans-serif;font-size:11px;fill:{_col if key=="ext" else "#555"};">{_lbl}</text>' if _lbl else '')

                + '</g>'

            )



    html = f"""

    <style>

      .uc-wrap {{ max-width: 1140px; margin: 0 auto; padding: 12px 0 24px; position: relative; }}

      .uc-cols {{ position: relative; display: flex; justify-content: space-between; align-items: flex-start; column-gap: 64px; }}

      .uc-col {{ width: 46%; }}

      .uc-item {{ height: {row_h}px; line-height: {row_h}px; display: flex; align-items: center; border-bottom: 1px solid #eee; font-family: sans-serif; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

      .uc-cols .uc-col:first-child .uc-item {{ padding-right: 26px; }}

      .uc-cols .uc-col:last-child  .uc-item {{ padding-left: 26px; }}

      .label {{ font-weight: 600; height: {label_h}px; margin: 0; display: flex; align-items: center; font-family: sans-serif; }}

      .legend {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; min-height: {legend_h}px; margin-bottom: 8px; font-family: sans-serif; font-size: 12px; }}

      .legend-item {{ display: flex; align-items: center; gap: 6px; }}

      .chip {{ width: 10px; height: 10px; display: inline-block; margin-right: 8px; border-radius: 2px; }}

    </style>

    <div class="uc-wrap" id="uc_wrap_{key}" style="padding: 0 {pad}px;">

      <div class="legend">{legend_items}</div>

      <div class="uc-cols" id="uc_cols_{key}">

        <div class="uc-col">

          <div class="label">{left_label}</div>

          {left_html}

        </div>

        <div class="uc-col">

          <div class="label">{right_label}</div>

          {right_html}

        </div>

        <svg id="uc_overlay_{key}" width="100%" height="{height}" style="position:absolute; top:0; left:0; pointer-events:none; z-index:2;">

          <defs id="uc_defs_{key}"></defs>

          {''.join(fallback_lines)}

        </svg>

      </div>

    </div>

    <script>

    (function() {{

      try {{

        const pairs = {pairs_json};

        const pairColors = {colors_json};

        const labels = {labels_json};

        const dash = "{dash}";

        const sectionKey = '{key}';

        const svg = document.getElementById('uc_overlay_{key}');

        const defs = document.getElementById('uc_defs_{key}');

        const wrap = document.getElementById('uc_wrap_{key}');

        if (!svg || !wrap) return;

        const cols = document.getElementById('uc_cols_{key}') || wrap.querySelector('.uc-cols');

        const colsRect = cols.getBoundingClientRect();

        try {{

          const needH = Math.ceil(cols.getBoundingClientRect().height);

          if (needH && !isNaN(needH)) svg.setAttribute('height', needH);

        }} catch(e) {{}}

        const leftCol = cols.querySelector('.uc-col:first-child');

        const rightCol = cols.querySelector('.uc-col:last-child');

        const leftRect = leftCol.getBoundingClientRect();

        const rightRect = rightCol.getBoundingClientRect();

        const x1 = (leftRect.right - colsRect.left) - 10;

        const x2 = (rightRect.left - colsRect.left) + 10;

        const midx = (x1 + x2) / 2;



        const markerFor = {{}};

        function markerIdFor(color){{

          if (markerFor[color]) return markerFor[color];

          const id = 'm_' + color.replace(/[^a-zA-Z0-9]/g,'');

          const mk = document.createElementNS('http://www.w3.org/2000/svg','marker');

          mk.setAttribute('id', id); mk.setAttribute('viewBox','0 0 10 10');

          mk.setAttribute('refX','9'); mk.setAttribute('refY','5');

          mk.setAttribute('markerWidth','7'); mk.setAttribute('markerHeight','7');

          mk.setAttribute('orient','auto');

          const p = document.createElementNS('http://www.w3.org/2000/svg','path');

          p.setAttribute('d','M 0 0 L 10 5 L 0 10 z'); p.setAttribute('fill', color);

          mk.appendChild(p); defs.appendChild(mk); markerFor[color]=id; return id;

        }}

        function addLine(xa, ya, xb, yb, arrow, color) {{

          const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');

          ln.setAttribute('x1', xa); ln.setAttribute('y1', ya);

          ln.setAttribute('x2', xb); ln.setAttribute('y2', yb);

          ln.setAttribute('stroke', color || '{stroke_color}'); ln.setAttribute('stroke-width', 2);

          ln.setAttribute('stroke-linecap', 'round');

          if (dash) ln.setAttribute('stroke-dasharray', dash);

          if (arrow) ln.setAttribute('marker-end', 'url(#' + markerIdFor(color || '{stroke_color}') + ')');

          svg.appendChild(ln);

        }}

        function addDot(x, y, color) {{

          const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');

          c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 3);

          c.setAttribute('fill', color || '{stroke_color}'); svg.appendChild(c);

        }}

        function addText(x, y, txt, color) {{

          if (!txt) return;

          const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');

          t.setAttribute('x', x); t.setAttribute('y', y-6); t.setAttribute('text-anchor','middle');

          const fill = (sectionKey === 'ext') ? (color || '{stroke_color}') : '#555';

          t.setAttribute('style','font-family:sans-serif;font-size:11px;fill:' + fill + ';');

          t.textContent = txt; svg.appendChild(t);

        }}



        const groups = {{}};

        pairs.forEach(function(p, idx) {{

          const si = p[0], ti = p[1];

          if (!groups[si]) groups[si] = [];

          groups[si].push({{ ti: ti, idx: idx }});

        }});

        const leftKeys = Object.keys(groups).map(n=>parseInt(n,10)).sort((a,b)=>a-b);

        const laneGap = 12;

        const laneIndexByLeft = {{}};

        leftKeys.forEach((a,i)=> laneIndexByLeft[a] = i);

        const inbound = new Map();

        pairs.forEach((p, idx) => {{

          const si = p[0], ti = p[1];

          if (!inbound.has(ti)) inbound.set(ti, []);

          inbound.get(ti).push({{ idx, si }});

        }});

        const rankOf = new Map();

        inbound.forEach((arr) => {{

          arr.sort((a,b)=> (laneIndexByLeft[a.si]||0) - (laneIndexByLeft[b.si]||0));

          const total = arr.length;

          arr.forEach((entry, r)=> rankOf.set(entry.idx, {{ r: r, total: total }}));

        }});



        leftKeys.forEach(function(si, laneIndex) {{

          const l = document.getElementById('ucl_{key}_' + si);

          if (!l) return;

          const lr = l.getBoundingClientRect();

          const yLeft = (lr.top + lr.bottom)/2 - colsRect.top;

          const firstIdx = groups[si][0].idx;

          const col = pairColors[firstIdx] || '{stroke_color}';

          const trunkX = midx + (laneIndex - (leftKeys.length - 1)/2) * laneGap;



          addDot(x1, yLeft, col);

          addLine(x1, yLeft, trunkX, yLeft, false, col);



          const yTargets = groups[si].map(function(g) {{

            const r = document.getElementById('ucr_{key}_' + g.ti);

            if (!r) return yLeft;

            const rr = r.getBoundingClientRect();

            return (rr.top + rr.bottom)/2 - colsRect.top;

          }});

          const yMin = Math.min.apply(null, yTargets.concat([yLeft]));

          const yMax = Math.max.apply(null, yTargets.concat([yLeft]));

          addLine(trunkX, yMin, trunkX, yMax, false, col);



          groups[si].forEach(function(g) {{

            const r = document.getElementById('ucr_{key}_' + g.ti);

            if (!r) return;

            const rr = r.getBoundingClientRect();

            const base = (rr.top + rr.bottom)/2 - colsRect.top;

            const info = rankOf.get(g.idx) || {{ r: 0, total: 1 }};

            const y2 = base + (info.r - (info.total - 1)/2) * 6;

            addLine(trunkX, y2, x2, y2, true, col);

            const key = si + '|' + g.ti;

            if (labels[key]) addText(midx, (yLeft + y2)/2, labels[key], col);

          }});

        }});

      }} catch(e) {{ console.warn('uc overlay draw failed', e); }}

    }})();

    </script>

    """

    components.html(html, height=iframe_h)





# ---------------------------------------------------------------------------

# Global page styling

# ---------------------------------------------------------------------------



def inject_global_styles():

    """Inject shared CSS used across all wizard steps."""

    st.markdown(

        """

        <style>

          .block-container {padding-left: 0.75rem; padding-right: 0.75rem; max-width: 1700px;}

          .stButton > button {

            white-space: nowrap;

            padding: 0.45rem 0.9rem;

            border-radius: 8px;

            display: block;

            margin: 0 auto;

          }

          .stMultiSelect [data-baseweb="tag"] {

            background-color: #e7f1ff !important;

            color: #0b5cab !important;

            border: 1px solid #b3d1ff !important;

          }

          .stMultiSelect [data-baseweb="tag"] span {

            white-space: normal !important;

            overflow: visible !important;

            text-overflow: clip !important;

            max-width: none !important;

          }

          .stMultiSelect > div > div { flex-wrap: wrap !important; }



          /* ---- Next / Extract / Confirm buttons --- green (primary type) ---- */

          button[kind="primary"] {

            background-color: #2d8a4e !important;

            border-color: #2d8a4e !important;

            color: white !important;

          }

          button[kind="primary"]:hover {

            background-color: #236b3d !important;

            border-color: #236b3d !important;

          }



          /* ---- Save Work download button --- green border/text ---- */

          [data-testid="stDownloadButton"] button:not([kind="primary"]) {
            color: #2d8a4e !important;

            border-color: #2d8a4e !important;

          }

          [data-testid="stDownloadButton"] button:not([kind="primary"]):hover {
            background-color: rgba(45,138,78,0.08) !important;

            border-color: #2d8a4e !important;

            color: #2d8a4e !important;

            box-shadow: 0 0 0 2px rgba(45,138,78,0.28) !important;

          }



          /* ---- Previous nav button --- blue

                 Target: 1st column of the navigation row (last stHorizontalBlock on page) ---- */

          div[data-testid="stHorizontalBlock"]:last-of-type

            > div[data-testid="stColumn"]:first-child button {

            background-color: #1a6fa8 !important;

            border-color: #1a6fa8 !important;

            color: white !important;

          }

          div[data-testid="stHorizontalBlock"]:last-of-type

            > div[data-testid="stColumn"]:first-child button:hover {

            background-color: #155a8a !important;

            border-color: #155a8a !important;

          }



          /* ---- Reset Session button --- yellow/amber ---- */

          /* :has() finds the stMarkdown containing #sr-row, then targets

             its sibling stHorizontalBlock's last column button */

          [data-testid="stMarkdown"]:has(#sr-row)

            ~ [data-testid="stHorizontalBlock"]

            > [data-testid="stColumn"]:last-child button {

            color: #a07800 !important;

            border-color: #d4a017 !important;

          }

          [data-testid="stMarkdown"]:has(#sr-row)

            ~ [data-testid="stHorizontalBlock"]

            > [data-testid="stColumn"]:last-child button:hover {

            background-color: rgba(212,160,23,0.10) !important;

            border-color: #d4a017 !important;

            color: #a07800 !important;

            box-shadow: 0 0 0 2px rgba(212,160,23,0.35) !important;

          }



          /* ---- Centre text in all buttons ---- */

          button { text-align: center !important; }

          button p { text-align: center !important; margin: 0 !important; }



          /* ---- Spinner: centred on page, 3 lines honour \n ---- */

          [data-testid="stSpinner"] {

            text-align: center !important;

          }

          [data-testid="stSpinner"] > div {

            display: inline-flex !important;

            flex-direction: column !important;

            align-items: center !important;

            justify-content: center !important;

            width: 100% !important;

          }

          [data-testid="stSpinner"] p,

          [data-testid="stSpinner"] span {

            white-space: pre-line !important;

            line-height: 1.7 !important;

            text-align: center !important;

          }

        </style>

        """,

        unsafe_allow_html=True,

    )





# ---------------------------------------------------------------------------

# Reusable summary table for relationship steps

# ---------------------------------------------------------------------------



def render_summary_table(rows, left_label, arrow_label, right_label,

                         title, icon="----", accent="#0b5cab",

                         extra_col_label=None):

    """Render a summary table using native Streamlit components.

    Used by steps 5 (includes), 6 (extends), 7 (UC gen), 8 (actor gen).

    """

    import pandas as pd



    n = len(rows)

    st.markdown(

        f"**{icon} {title}** &nbsp;&nbsp; *{n} item{'s' if n != 1 else ''}*"

    )



    if not rows:

        st.info("No relationships yet --- add one below.")

        return



    has_extra = bool(extra_col_label and any(r.get("extra") for r in rows))



    table_rows = []

    for r in rows:

        row = {

            left_label:  r.get("left", ""),

            "":          arrow_label,

            right_label: r.get("right", ""),

        }

        if has_extra:

            row[extra_col_label] = r.get("extra") or "-"

        table_rows.append(row)



    st.dataframe(

        pd.DataFrame(table_rows),

        use_container_width=True,

        hide_index=True,

    )

