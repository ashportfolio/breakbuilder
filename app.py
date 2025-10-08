import re
from io import BytesIO
import pdfplumber
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import streamlit as st
import pandas as pd
import datetime

# ──────────────────────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Makeup & SFX Breakdown", page_icon="💋", layout="wide")

# STYLING
st.markdown("""
<style>
/* Overall page styling */
body, .stApp {
    background-color: #0e0e0e !important;
    color: #f5f5f5 !important;
    font-family: 'Montserrat', sans-serif;
    font-weight: 300 !important;
}

/* Typography fixes */
h1, h2, h3, h4, h5, h6, label, p, div, span, input, textarea, select, button {
    font-family: 'Montserrat', sans-serif !important;
    font-weight: 300 !important;
}

/* Title */
h1 {
    text-align: center;
    color: #f8f8f8;
    font-weight: 500;
    letter-spacing: 0.02em;
    margin-top: 1.5rem;
    margin-bottom: 1rem;
}

/* Upload boxes */
[data-testid="stFileUploaderDropzone"] {
    border: 2px dashed #ffb6c1 !important; /* pastel pink border */
    border-radius: 12px !important;
    background-color: #1c1c1c !important;
    transition: all 0.3s ease;
}

[data-testid="stFileUploaderDropzone"]:hover {
    background-color: #222222 !important;
    border-color: #ffc9d9 !important;
}

/* Buttons */
div.stButton > button {
    background-color: #ffb6c1 !important;
    color: #0e0e0e !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    padding: 0.5rem 1.5rem !important;
    transition: all 0.25s ease;
}

div.stButton > button:hover {
    background-color: #ffc9d9 !important;
    color: #000 !important;
    transform: translateY(-1px);
}

/* Sliders */
div[data-testid="stSlider"] > div > div > div {
    color: #ffb6c1 !important;
}

.css-1dp5vir .stSlider [role='slider'] {
    background-color: #ffb6c1 !important;
}

.stSlider > div > div > div > div[role='slider'] {
    background-color: #ffb6c1 !important;
}

/* Center main block */
.block-container {
    padding-top: 2rem !important;
    padding-bottom: 6rem !important; /* for footer space */
    max-width: 900px !important;
    margin: 0 auto !important;
}

.custom-footer {
    text-align: center;
    font-size: 0.9rem;
    color: #aaaaaa;
    font-family: 'Montserrat', sans-serif;
    margin-top: 3rem;
    margin-bottom: 1rem;
    opacity: 0.8;
}

a.custom-link {
    color: #ffb6c1;
    text-decoration: none;
    font-weight: 300 !important;
}

a.custom-link:hover {
    text-decoration: underline;
    color: #ffc9d9;
}
</style>
""", unsafe_allow_html=True)

st.title("🎬 Makeup & SFX Breakdown Builder")
st.caption(f"Build loaded at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

st.markdown("""
<div style='
    background-color: transparent;
    color: #ffb6c1;
    font-family: "Montserrat", sans-serif;
    font-weight: 600;
    text-align: left;
    margin-top: 0.5rem;
    margin-bottom: 1.2rem;
    font-size: 1.05rem;'>
📂 Please upload both files below, then click <b>Generate Breakdown</b> to begin.
</div>
""", unsafe_allow_html=True)

chron_file = st.file_uploader("Upload Chronologie PDF", type=["pdf"])
break_file = st.file_uploader("Upload Previous Breakdown DOCX (template)", type=["docx"])

dev_mode = st.secrets.get("dev_mode", True)

if dev_mode:
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        debug = st.checkbox("Debug Info")
    with c2:
        super_debug = st.checkbox("Super Debug (lines & headers)")
    with c3:
        cast_split_ratio = st.slider("Cast column split (% of page width)", 0.55, 0.85, 0.61, 0.01)
else:
    debug = False
    super_debug = False
    cast_split_ratio = 0.61  # default

# ──────────────────────────────────────────────────────────────
# Regex
# ──────────────────────────────────────────────────────────────
SCENE_TOKEN   = r"\d+(?:[A-Z]+(?:\d+)?)?"
HEADER_SLASH  = re.compile(rf"^\s*(\d+)\s*/\s*({SCENE_TOKEN})\b")
HEADER_SPACE  = re.compile(rf"^\s*(\d+)\s+({SCENE_TOKEN})\b")
TIMING_RX     = re.compile(r"\b([IA](?:\+[IA])?/[A-ZÄÖÜNTM]+|[IA][NTM])\b")
EXTRAS_RX     = re.compile(r"(\d+)\s*Komparsen", re.IGNORECASE)
ID_RX         = re.compile(r"\b\d{1,4}\b")

# ──────────────────────────────────────────────────────────────
# Cleanup helpers
# ──────────────────────────────────────────────────────────────
def clean_commas(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"(,\s*){2,}", ", ", s).strip(" ,;/")

def cleanup_docx(doc: Document) -> Document:
    """Post-process the final doc to remove stray text and double commas"""
    for p in doc.paragraphs:
        if "Krankenpfeger*in" in p.text or "Krankenpfleger*in" in p.text:
            p.text = p.text.replace("Krankenpfeger*in", "").replace("Krankenpfleger*in", "")
        if ", ," in p.text:
            p.text = re.sub(r"(,\s*){2,}", ", ", p.text)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if "Krankenpfeger*in" in cell.text or "Krankenpfleger*in" in cell.text:
                    cell.text = cell.text.replace("Krankenpfeger*in", "").replace("Krankenpfleger*in", "")
                if ", ," in cell.text:
                    cell.text = re.sub(r"(,\s*){2,}", ", ", cell.text)
    return doc

# ──────────────────────────────────────────────────────────────
# Rollen parsing (page 1, two columns)
# ──────────────────────────────────────────────────────────────
def build_rollen_map(pdf) -> dict:
    rollen = {}
    try:
        page = pdf.pages[0]
        words = page.extract_words() or []
    except Exception:
        return rollen
    if not words:
        return rollen

    midpoint = page.width / 2
    cols = {"left": {}, "right": {}}
    for w in words:
        y = round(w["top"], 0)
        x = w["x0"]
        side = "left" if x < midpoint else "right"
        cols[side].setdefault(y, []).append((x, w["text"]))

    def parse_col(lines_dict):
        out = {}
        for y in sorted(lines_dict):
            parts = " ".join(t for _, t in sorted(lines_dict[y], key=lambda x: x[0]))
            m = re.match(r"^(\d+)\s+(.+)$", parts.strip())
            if m:
                out[m.group(1)] = m.group(2).strip()
        return out

    rollen.update(parse_col(cols["left"]))
    rollen.update(parse_col(cols["right"]))
    return rollen

# ──────────────────────────────────────────────────────────────
# Lines & headers
# ──────────────────────────────────────────────────────────────
def group_words_into_lines(words, y_round=1):
    by_y = {}
    for w in words:
        y = round(w.get("top", 0.0), y_round)
        by_y.setdefault(y, []).append(w)
    lines = []
    for y in sorted(by_y):
        wlist = sorted(by_y[y], key=lambda w: w.get("x0", 0.0))
        text = " ".join(w["text"] for w in wlist if "text" in w)
        if text.strip():
            lines.append({"y": y, "words": wlist, "text": text.strip()})
    return lines

def find_headers(lines):
    headers = []
    for i, L in enumerate(lines):
        t = L["text"]
        if not TIMING_RX.search(t):
            continue
        m = HEADER_SLASH.search(t) or HEADER_SPACE.search(t)
        if m:
            headers.append((i, m.group(1), m.group(2)))
    return headers

# ──────────────────────────────────────────────────────────────
# Scene block → row
# ──────────────────────────────────────────────────────────────
def parse_scene_block(page, lines, start_idx, end_idx, rollen_map, cast_split_ratio):
    header_text = lines[start_idx]["text"]
    m = HEADER_SLASH.search(header_text) or HEADER_SPACE.search(header_text)
    day, scene = (m.group(1), m.group(2)) if m else ("", "")

    block_text = " ".join(L["text"] for L in lines[start_idx:end_idx])

    # Timing
    tm = TIMING_RX.search(block_text)
    timing = (tm.group(1) if tm else "")
    if len(timing) == 2 and timing[0] in "IA" and timing[1] in "NTM":
        timing = f"{timing[0]}/{timing[1]}"

    # Summary
    summary = block_text
    if tm:
        pos = block_text.find(tm.group(0)) + len(tm.group(0))
        summary = block_text[pos:].strip()
    summary = EXTRAS_RX.sub("", summary)
    summary = re.sub(r"\b\d{1,4}\b", "", summary)
    summary = fix_fake_slashes(summary)
    summary = clean_commas(summary)

    # Cast extraction
    words_in_block = []
    for L in lines[start_idx:end_idx]:
        words_in_block.extend(L["words"])

    cast_cutoff = page.width * cast_split_ratio
    right_words = [w for w in words_in_block if w["x0"] >= cast_cutoff]
    right_text = " ".join(w["text"] for w in sorted(right_words, key=lambda w: (w["top"], w["x0"])))

    extras_str = ""
    m_extra = EXTRAS_RX.search(right_text)
    if m_extra:
        extras_str = f"{m_extra.group(1)} Komparsen"
        right_text = EXTRAS_RX.sub("", right_text)

    ids = set(ID_RX.findall(right_text))
    valid_ids = [i for i in ids if i in rollen_map]
    cast_names = [f"{i} {rollen_map[i]}" for i in sorted(valid_ids, key=lambda x: int(x))]
    cast_line = clean_commas(", ".join(cast_names))

    cast_text = cast_line if cast_line else ""
    if extras_str:
        cast_text = f"{cast_text}\n{extras_str}" if cast_text else extras_str

    return day, scene, timing, summary, cast_text

def extract_scene_rows(pdf, rollen_map, cast_split_ratio=0.61, super_debug=False):
    rows = []
    dbg_pages = []
    for p_idx, page in enumerate(pdf.pages):
        words = page.extract_words() or []
        line_objs = group_words_into_lines(words, y_round=1)
        headers = find_headers(line_objs)

        if super_debug:
            dbg_pages.append({
                "page": p_idx+1,
                "lines_first40": [L["text"] for L in line_objs[:40]],
                "headers": headers
            })

        for i, (h_idx, day, scene) in enumerate(headers):
            next_idx = headers[i+1][0] if i+1 < len(headers) else len(line_objs)
            d, s, t, summary, cast_text = parse_scene_block(
                page, line_objs, h_idx, next_idx, rollen_map, cast_split_ratio
            )
            rows.append([d, s, t, summary, cast_text])

    return rows, dbg_pages

# ──────────────────────────────────────────────────────────────
# DOCX helpers
# ──────────────────────────────────────────────────────────────
def clear_row_shading(row):
    for cell in row.cells:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = tcPr.find(qn('w:shd'))
        if shd is not None:
            tcPr.remove(shd)

def set_row_bottom_border(row, size=24, color="000000", val="single"):
    for cell in row.cells:
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = tcPr.find(qn('w:tcBorders'))
        if tcBorders is None:
            tcBorders = OxmlElement('w:tcBorders')
            tcPr.append(tcBorders)
        bottom = tcBorders.find(qn('w:bottom'))
        if bottom is None:
            bottom = OxmlElement('w:bottom')
            tcBorders.append(bottom)
        bottom.set(qn('w:val'), val)
        bottom.set(qn('w:sz'), str(size))
        bottom.set(qn('w:color'), color)

def extract_existing_notes(docx_doc: Document) -> dict:
    out = {}
    if not docx_doc.tables:
        return out
    table = docx_doc.tables[0]
    for row in table.rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) < 7:
            continue
        key = (cells[0], cells[1])
        out[key] = {"SFX": cells[5], "Notes": cells[6]}
    return out
# Replace pdf-extraction slashes with commas/spaces (safe)
def fix_fake_slashes(s: str) -> str:
    if not s:
        return ""
    # most of the bad ones are " / " that should just be separators
    s = s.replace(" / ", ", ")
    # extra safety: any stray spaced slashes -> comma
    s = re.sub(r"\s+/\s+", ", ", s)
    # normalize spaces
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,;/")

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
if chron_file and break_file and st.button("Generate Breakdown"):
    with pdfplumber.open(chron_file) as pdf:
        rollen_map = build_rollen_map(pdf)
        rows, dbg_pages = extract_scene_rows(pdf, rollen_map, cast_split_ratio=cast_split_ratio, super_debug=super_debug)

    st.subheader("🔍 Parsed Row Debug Preview (first 15)")
    st.dataframe(pd.DataFrame([{
        "Day": d, "Scene": s, "Timing": t, "Summary": summary, "Cast": cast
    } for d, s, t, summary, cast in rows[:15]]))

    try:
        old_doc = Document(break_file)
    except Exception as e:
        st.error(f"Could not read DOCX: {e}")
        st.stop()
    if not old_doc.tables:
        st.error("The uploaded Breakdown DOCX has no tables.")
        st.stop()

    existing = extract_existing_notes(old_doc)
    new_doc = Document(break_file)
    table = new_doc.tables[0]

    # clear body rows
    while len(table.rows) > 1:
        table._tbl.remove(table.rows[1]._tr)

    old_keys = set(existing.keys())
    new_keys = set()

    for d, s, t, summary, cast in rows:
        key = (d, s)
        new_keys.add(key)
        sfx = existing.get(key, {}).get("SFX", "")
        notes = existing.get(key, {}).get("Notes", "")

        r = table.add_row(); cells = r.cells
        vals = [d, s, t, clean_commas(summary), clean_commas(cast), sfx, notes]
        for i in range(min(len(vals), len(cells))):
            cells[i].text = str(vals[i])
        for j in range(len(vals), len(cells)):
            cells[j].text = ""

        clear_row_shading(r)
        set_row_bottom_border(r, size=24, color="000000")

    # 🔑 Post-process cleanup
    new_doc = cleanup_docx(new_doc)

    # Change log
    changelog = []
    for k in sorted(new_keys - old_keys):
        changelog.append(f"ADDED {k}")
    for k in sorted(old_keys - new_keys):
        changelog.append(f"REMOVED {k}")

    out_buffer = BytesIO()
    new_doc.save(out_buffer)
    out_buffer.seek(0)

    st.success("✅ Breakdown is ready! Click below to download:")
    st.download_button(
        "📥 Download New Breakdown",
        data=out_buffer,
        file_name="Breakdown_filled_EP1.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True
    )

    if changelog:
        st.subheader("📝 Change Log (Preview)")
        st.text("\n".join(changelog))

    if debug:
        st.subheader("🐛 Debug Info")
        st.json({
            "rollen_map_size": len(rollen_map),
            "parsed_rows": len(rows),
            "changes_detected": len(changelog),
            "cast_split_ratio_used": cast_split_ratio
        })

    if super_debug:
        st.subheader("🔬 Super Debug")
        for p in dbg_pages[:3]:
            st.markdown(f"**Page {p['page']}**")
            with st.expander("Lines (first ~40)", expanded=False):
                for i, t in enumerate(p["lines_first40"]):
                    st.write(f"{i:02d}: {t}")
            with st.expander("Detected headers", expanded=True):
                st.write(p["headers"])
#else:
#    st.info("Upload both files, then press **Generate Breakdown**.")

# Footer (placed at bottom)
st.markdown("""
<div class="custom-footer">
Built with ❤️ by <a href="https://ashwinanandani.com" class="custom-link" target="_blank">a fan of the show</a> — 
contact via WhatsApp for big issues, treat with love, and stay kind.
</div>
""", unsafe_allow_html=True)