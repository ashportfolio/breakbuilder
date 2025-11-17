import re
from io import BytesIO
import pdfplumber
from docx import Document
from docx.oxml.ns import qn
import streamlit as st
import pandas as pd
import datetime

# ─────────────────────────────────────────────
# UI & Styling
# ─────────────────────────────────────────────
st.set_page_config(page_title="Makeup & SFX Breakdown", page_icon="💋", layout="wide")

st.markdown("""
<style>
body, .stApp {
    background-color: #0e0e0e !important;
    color: #f5f5f5 !important;
    font-family: 'Montserrat', sans-serif;
}
@media (prefers-color-scheme: light) {
  body, .stApp { background-color: #ffffff !important; color: #111111 !important; }
}
[data-testid="stFileUploaderDropzone"] {
    border: 2px dashed #ffb6c1 !important;
    border-radius: 12px !important;
    background-color: #1c1c1c !important;
}
[data-testid="stFileUploaderDropzone"]:hover {
    background-color: #222 !important; border-color: #ffc9d9 !important;
}
div.stButton > button {
    background-color: #ffb6c1 !important; color: #0e0e0e !important;
    border-radius: 12px !important; font-weight: 500 !important;
}
div.stButton > button:hover { background-color: #ffc9d9 !important; color: #000 !important; }
.block-container { max-width: 900px !important; margin: 0 auto !important; }
.custom-footer { text-align: center; color: #aaaaaa; font-size: 0.9rem; margin-top: 3rem; }
a.custom-link { color: #ffb6c1; text-decoration: none; }
a.custom-link:hover { text-decoration: underline; color: #ffc9d9; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 Makeup & SFX Breakdown Builder")
st.caption(f"Build loaded at {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")

chron_file = st.file_uploader("Upload Chronologie PDF", type=["pdf"])
break_file = st.file_uploader("Upload Previous Breakdown DOCX", type=["docx"])
ep7_mode = st.checkbox("EP7 layout (3-column)", value=True)

if ep7_mode:
    col1, col2 = st.columns(2)
    with col1: col1_col2_split = st.slider("Split Col1→Col2 (%)", 0.1, 0.35, 0.22, 0.01)
    with col2: col2_col3_split = st.slider("Split Col2→Col3 (%)", 0.45, 0.8, 0.66, 0.01)
else:
    cast_split_ratio = st.slider("Cast column split", 0.55, 0.85, 0.61, 0.01)

debug = st.checkbox("Debug Info")

# ─────────────────────────────────────────────
# Regex
# ─────────────────────────────────────────────
HEADER_SLASH = re.compile(r"^\s*(\d+)\s*/\s*([0-9A-Z.]+)\b")
HEADER_SPACE = re.compile(r"^\s*(\d+)\s+([0-9A-Z.]+)\b")
TIMING_RX = re.compile(r"\b([IA](?:\+[IA])?/[A-ZÄÖÜNTM]+|[IA][NTM])\b")
SEITEN_RX = re.compile(r"Seiten\s*[:\-]?\s*\d+\/?\d*", re.I)
ID_RX = re.compile(r"\b\d{1,4}\b")
OMITTED_RX = re.compile(r"\bOMITTED\b", re.I)
UPPERCASE_WORD_RX = re.compile(r"\b[A-ZÄÖÜ]{3,}\b")

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def clean_commas(s):
    return re.sub(r"(,\s*){2,}", ", ", s).strip(" ,;/") if s else s

def cleanup_docx(doc):
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells:
                c.text = re.sub(r"Krankenpfleger\*in|Krankenpfeger\*in", "", c.text)
                c.text = re.sub(r"(,\s*){2,}", ", ", c.text)
    return doc

# ─────────────────────────────────────────────
# Rollen Parsing
# ─────────────────────────────────────────────
def build_rollen_map_ep7(pdf):
    mapping = {}
    rx = re.compile(r"^\s*(\d{1,4})\s+(.+?)\s*$")
    for page in pdf.pages:
        for line in (page.extract_text() or "").splitlines():
            m = rx.match(line.strip())
            if m:
                mapping[m.group(1)] = m.group(2).strip()
        if len(mapping) >= 5:
            break
    return mapping

# ─────────────────────────────────────────────
# Line Grouping
# ─────────────────────────────────────────────
def group_words_into_lines(words, y_tol=1.2):
    by_y = {}
    for w in words:
        y = round(w["top"] / y_tol) * y_tol
        by_y.setdefault(y, []).append(w)
    lines = []
    for y in sorted(by_y):
        wlist = sorted(by_y[y], key=lambda x: x["x0"])
        text = " ".join(w["text"] for w in wlist)
        if text.strip():
            lines.append({"y": y, "text": text, "words": wlist})
    return lines

def find_headers(lines, min_gap=10):
    headers = []
    prev_y = None
    prev_scene = None
    for i, L in enumerate(lines):
        txt = L["text"].strip()
        # Check header pattern
        m = HEADER_SLASH.search(txt) or HEADER_SPACE.search(txt)
        if not m:
            continue
        # Sanity: must have at least one uppercase word (likely location)
        if not UPPERCASE_WORD_RX.search(txt):
            continue
        scene = m.group(2)
        # Skip duplicates or too-close verticals
        if prev_scene == scene:
            continue
        if prev_y is not None and abs(L["y"] - prev_y) < min_gap:
            continue
        headers.append((i, m.group(1), scene))
        prev_y = L["y"]
        prev_scene = scene
    return headers

# ─────────────────────────────────────────────
# Column Parsing (EP7)
# ─────────────────────────────────────────────
def slice_columns(words, width, s12, s23):
    c1, c2, c3 = [], [], []
    for w in words:
        if w["x0"] < width * s12:
            c1.append(w)
        elif w["x0"] < width * s23:
            c2.append(w)
        else:
            c3.append(w)
    f = lambda ws: " ".join(t["text"] for t in sorted(ws, key=lambda x: (x["top"], x["x0"])))
    return f(c1), f(c2), f(c3)

def extract_caps_location(text):
    if not text:
        return ""
    text = re.sub(SEITEN_RX, "", text)
    text = re.sub(r"\b\d{1,4}\b", "", text)
    # capture first uppercase phrase before lowercase
    m = re.search(r"\b([A-ZÄÖÜ0-9][A-ZÄÖÜ0-9 \-/]+)(?=\s+[a-zäöü])", text)
    if m:
        return m.group(1).strip(" -_/")
    # fallback to first uppercase sequence
    parts = re.findall(r"[A-ZÄÖÜ0-9][A-ZÄÖÜ0-9 \-_/]{2,}", text)
    if parts:
        return parts[0].strip(" -_/")
    return text.strip()

# ─────────────────────────────────────────────
# Scene Parser
# ─────────────────────────────────────────────
def parse_scene_block_ep7(page, lines, start, end, rollen_map, s12, s23):
    header = lines[start]["text"]
    m = HEADER_SLASH.search(header) or HEADER_SPACE.search(header)
    day, scene = (m.group(1), m.group(2)) if m else ("", "")
    words = [w for L in lines[start:end] for w in L["words"]]
    col1, col2, col3 = slice_columns(words, page.width, s12, s23)
    raw_block = f"{col1} {col2} {col3}"

    # Skip OMITTED
    if OMITTED_RX.search(raw_block):
        return None

    # Timing
    tmatch = TIMING_RX.search(col1)
    timing = tmatch.group(1) if tmatch else ""

    # Clean & combine
    col2 = re.sub(SEITEN_RX, "", col2)
    col3 = re.sub(SEITEN_RX, "", col3)
    col2 = re.sub(r"\b\d{1,4}\b", "", col2)
    col3 = re.sub(r"\b\d{1,4}\b", "", col3)

    location = extract_caps_location(col2)
    description = col3.strip()
    summary = clean_commas(f"{location}\n{description}" if location else description)

    # Cast
    ids = set(ID_RX.findall(raw_block))
    cast = ", ".join(f"{i} {rollen_map[i]}" for i in sorted(ids, key=lambda x: int(x)) if i in rollen_map)
    return day, scene, timing, summary, cast

# ─────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────
def extract_scene_rows(pdf, rollen_map, s12, s23):
    rows = []
    for page in pdf.pages:
        words = page.extract_words() or []
        lines = group_words_into_lines(words)
        headers = find_headers(lines)
        for i, (idx, day, scene) in enumerate(headers):
            end = headers[i + 1][0] if i + 1 < len(headers) else len(lines)
            parsed = parse_scene_block_ep7(page, lines, idx, end, rollen_map, s12, s23)
            if parsed:
                rows.append(list(parsed))
    return rows

# ─────────────────────────────────────────────
# DOCX utilities
# ─────────────────────────────────────────────
def extract_existing_notes(doc):
    data = {}
    if not doc.tables:
        return data
    t = doc.tables[0]
    for r in t.rows[1:]:
        c = [x.text.strip() for x in r.cells]
        if len(c) >= 7:
            data[(c[0], c[1])] = {"SFX": c[5], "Notes": c[6]}
    return data

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if chron_file and break_file and st.button("Generate Breakdown"):
    with pdfplumber.open(chron_file) as pdf:
        rollen = build_rollen_map_ep7(pdf)
        rows = extract_scene_rows(pdf, rollen, col1_col2_split, col2_col3_split)

    st.dataframe(pd.DataFrame(rows, columns=["Day", "Scene", "Timing", "Summary", "Cast"]).head(15))

    doc = Document(break_file)
    existing = extract_existing_notes(doc)
    t = doc.tables[0]
    while len(t.rows) > 1:
        t._tbl.remove(t.rows[1]._tr)

    first = True
    for d, s, timing, summary, cast in rows:
        key = (d, s)
        sfx = existing.get(key, {}).get("SFX", "")
        notes = existing.get(key, {}).get("Notes", "")
        if not first:
            r = t.add_row()
            for c in r.cells: c.text = ""
        first = False
        r = t.add_row()
        vals = [d, s, timing, summary, cast, sfx, notes]
        for i, v in enumerate(vals):
            r.cells[i].text = str(v)

    cleanup_docx(doc)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    st.download_button("📥 Download New Breakdown", buf, "Breakdown_filled_EP7.docx",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       use_container_width=True)
    if debug:
        st.json({"rows": len(rows), "rollen": len(rollen)})

st.markdown("""
<div class='custom-footer'>
Built with ❤️ — contact if something explodes.
</div>
""", unsafe_allow_html=True)