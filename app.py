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
body, .stApp { background-color: #0e0e0e !important; color: #f5f5f5 !important; font-family: 'Montserrat', sans-serif; font-weight: 300 !important; }
h1, h2, h3, h4, h5, h6, label, p, div, span, input, textarea, select, button { font-family: 'Montserrat', sans-serif !important; font-weight: 300 !important; }
h1 { text-align: center; color: #f8f8f8; font-weight: 500; letter-spacing: 0.02em; margin-top: 1.5rem; margin-bottom: 1rem; }
[data-testid="stFileUploaderDropzone"] { border: 2px dashed #ffb6c1 !important; border-radius: 12px !important; background-color: #1c1c1c !important; transition: all 0.3s ease; }
[data-testid="stFileUploaderDropzone"]:hover { background-color: #222222 !important; border-color: #ffc9d9 !important; }
div.stButton > button { background-color: #ffb6c1 !important; color: #0e0e0e !important; border: none !important; border-radius: 12px !important; font-weight: 500 !important; font-size: 1rem !important; padding: 0.5rem 1.5rem !important; transition: all 0.25s ease; }
div.stButton > button:hover { background-color: #ffc9d9 !important; color: #000 !important; transform: translateY(-1px); }
.block-container { padding-top: 2rem !important; padding-bottom: 6rem !important; max-width: 900px !important; margin: 0 auto !important; }
.custom-footer { text-align: center; font-size: 0.9rem; color: #aaaaaa; font-family: 'Montserrat', sans-serif; margin-top: 3rem; margin-bottom: 1rem; opacity: 0.8; }
a.custom-link { color: #ffb6c1; text-decoration: none; font-weight: 500; }
a.custom-link:hover { text-decoration: underline; color: #ffc9d9; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 Makeup & SFX Breakdown Builder")
st.caption(f"Build loaded at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

st.markdown("""
<div style='color:#ffb6c1;font-weight:500;margin:.5rem 0 1.2rem;font-size:1.05rem'>
📂 Please upload both files below, then click <b>Generate Breakdown</b> to begin.
</div>
""", unsafe_allow_html=True)

chron_file = st.file_uploader("Upload Chronologie PDF", type=["pdf"])
break_file = st.file_uploader("Upload Previous Breakdown DOCX (template)", type=["docx"])

c1, c2, c3 = st.columns([1,1,2])
with c1:
    debug = st.checkbox("Debug Info")
with c2:
    super_debug = st.checkbox("Super Debug (lines & headers)")
with c3:
    cast_split_ratio = st.slider("Cast column split (% of page width)", 0.55, 0.85, 0.61, 0.01)

# ──────────────────────────────────────────────────────────────
# Regex
# ──────────────────────────────────────────────────────────────
SCENE_TOKEN   = r"[0-9]+[A-Z]?(?:T[0-9]+)?(?:\.[A-Z0-9]+)?"
HEADER_SLASH  = re.compile(rf"^\s*(\d+)\s*/\s*({SCENE_TOKEN})\b")
HEADER_SPACE  = re.compile(rf"^\s*(\d+)\s+({SCENE_TOKEN})\b")
TIMING_RX     = re.compile(r"\b([IA](?:\+[IA])?/[A-ZÄÖÜNTM]+|[IA][NTM])\b")
EXTRAS_RX     = re.compile(r"(\d+)\s*Komparsen", re.IGNORECASE)
ID_RX         = re.compile(r"\b\d{1,4}\b")

# Dangling variants and helpers
HEADER_DANGLING = re.compile(r"^\s*(\d+)\s*/\s*$")
SCENE_ONLY      = re.compile(rf"^\s*{SCENE_TOKEN}\s*$")
LINE_DAY         = re.compile(r"^\s*(\d+)\s*$")
LINE_SCENE_ONLY  = re.compile(rf"^\s*({SCENE_TOKEN})\s*[,;]*\s*$")
LINE_TIMING_ONLY = TIMING_RX

# Mid-block scene token detection (safe)
MID_SCENE_RX    = re.compile(rf"\b({SCENE_TOKEN})\b(?=\s+\d+(?:\s*/\s*\d+)?)")
UPPER_LOC_HINT  = re.compile(r"[A-ZÄÖÜ][A-ZÄÖÜ\- ]{6,}")

# Location extractor (captures ALL-CAPS chunk right after I/T, A/N, etc.)
LOC_RX = re.compile(
    r"(?:\b[IA](?:\+[IA])?/[A-ZÄÖÜNTM]+|[IA][NTM])\s+([A-ZÄÖÜ][A-ZÄÖÜ\-/ ]{5,})"
)

# ──────────────────────────────────────────────────────────────
# Cleanup helpers
# ──────────────────────────────────────────────────────────────
def clean_commas(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"(,\s*){2,}", ", ", s).strip(" ,;/")

def cleanup_docx(doc: Document) -> Document:
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
# Rollen parsing
# ──────────────────────────────────────────────────────────────
ROLE_LINE = re.compile(r"^\s*(\d{1,4})\s+(.+?)\s*$")

def clean_role_label(label: str) -> str:
    label = re.split(r"\s[-–—]\s", label, 1)[0]
    label = re.sub(r"\((?:[^)]*?Krankenpfleger\*?in[^)]*|\d{1,3})\)", "", label, flags=re.I)
    return re.sub(r"\s{2,}", " ", label).strip(" -–—\u2013 ")

def build_rollen_map(pdf) -> dict:
    mapping = {}
    for page in pdf.pages:
        txt = page.extract_text() or ""
        if "ROLLEN" not in txt:
            continue
        lines = [l.rstrip() for l in txt.splitlines()]
        i = 0
        while i < len(lines):
            m = ROLE_LINE.match(lines[i])
            if not m:
                i += 1; continue
            num, raw = m.groups()
            j = i + 1
            chunk = [raw]
            while j < len(lines) and not ROLE_LINE.match(lines[j]) and lines[j].strip():
                chunk.append(lines[j].strip()); j += 1
            label = clean_role_label(" ".join(chunk))
            if label:
                mapping[str(int(num))] = label
            i = j
        if mapping: break
    return mapping

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

def normalize_line_objs(line_objs):
    """Merge multi-line headers such as '1 /' + '12T1' or '1' + 'I/T' + '12T1'."""
    out = []
    i = 0; n = len(line_objs)

    def combine(base_idx, take_next_k, text_builder):
        combined = dict(line_objs[base_idx])
        combined["text"] = text_builder()
        merged_words = []
        for k in range(take_next_k + 1):
            merged_words.extend(line_objs[base_idx + k]["words"])
        combined["words"] = merged_words
        return combined

    while i < n:
        cur_text = line_objs[i]["text"]

        mA = HEADER_DANGLING.match(cur_text)
        if mA:
            # allow one blank/garbage spacer before SCENE_ONLY
            j = i + 1
            while j < n and not SCENE_ONLY.match(line_objs[j]["text"]) and not line_objs[j]["text"].strip():
                j += 1
            if j < n and SCENE_ONLY.match(line_objs[j]["text"]):
                day = mA.group(1)
                scene = line_objs[j]["text"].strip().strip(",;")
                merged = combine(i, j - i, lambda: f"{day} / {scene}")
                out.append(merged); i = j + 1; continue

        mB = LINE_DAY.match(cur_text)
        if mB and i + 1 < n and LINE_SCENE_ONLY.match(line_objs[i + 1]["text"]):
            day = mB.group(1)
            scene = line_objs[i + 1]["text"].strip().strip(",;")
            if i + 2 < n and LINE_TIMING_ONLY.search(line_objs[i + 2]["text"]):
                timing_txt = line_objs[i + 2]["text"].strip()
                merged = combine(i, 2, lambda: f"{day} / {scene} {timing_txt}")
                out.append(merged); i += 3; continue
            merged = combine(i, 1, lambda: f"{day} / {scene}")
            out.append(merged); i += 2; continue

        if mB and i + 2 < n and LINE_TIMING_ONLY.search(line_objs[i + 1]["text"]) and LINE_SCENE_ONLY.match(line_objs[i + 2]["text"]):
            day = mB.group(1)
            timing_txt = line_objs[i + 1]["text"].strip()
            scene = line_objs[i + 2]["text"].strip().strip(",;")
            merged = combine(i, 2, lambda: f"{day} / {scene} {timing_txt}")
            out.append(merged); i += 3; continue

        out.append(line_objs[i]); i += 1
    return out

def find_headers(lines):
    headers = []
    for i, L in enumerate(lines):
        t = L["text"]
        m = HEADER_SLASH.search(t) or HEADER_SPACE.search(t)
        if m:
            headers.append((i, m.group(1), m.group(2)))
    return headers

# ──────────────────────────────────────────────────────────────
# Scene parsing
# ──────────────────────────────────────────────────────────────
def fix_fake_slashes(s: str) -> str:
    if not s: return ""
    s = s.replace(" / ", ", ")
    s = re.sub(r"\s+/\s+", ", ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,;/")

def parse_scene_block(page, lines, start_idx, end_idx, rollen_map, cast_split_ratio):
    header_text = lines[start_idx]["text"]
    m = HEADER_SLASH.search(header_text) or HEADER_SPACE.search(header_text)
    day, scene = (m.group(1), m.group(2)) if m else ("", "")

    words_in_block = []
    for L in lines[start_idx:end_idx]:
        words_in_block.extend(L["words"])

    cast_cutoff = page.width * cast_split_ratio
    left_words  = [w for w in words_in_block if w["x0"] <  cast_cutoff]
    right_words = [w for w in words_in_block if w["x0"] >= cast_cutoff]

    left_text  = " ".join(w["text"] for w in sorted(left_words,  key=lambda w: (w["top"], w["x0"])))
    right_text = " ".join(w["text"] for w in sorted(right_words, key=lambda w: (w["top"], w["x0"])))

    tm = TIMING_RX.search(left_text)
    timing = (tm.group(1) if tm else "")
    if len(timing) == 2 and timing[0] in "IA" and timing[1] in "NTM":
        timing = f"{timing[0]}/{timing[1]}"

    summary = left_text
    if tm:
        pos = left_text.find(tm.group(0)) + len(tm.group(0))
        summary = left_text[pos:].strip()
    summary = re.sub(r"^\s*,\s*", "", summary)
    summary = EXTRAS_RX.sub("", summary)
    summary = fix_fake_slashes(summary)
    summary = clean_commas(summary)

    # Extract first ALL-CAPS location for block grouping/borders
    loc = ""
    mloc = LOC_RX.search(left_text)
    if mloc:
        loc = mloc.group(1).strip()
        # normalize multiple spaces and trailing numbers
        loc = re.sub(r"\s{2,}", " ", loc)
        loc = re.sub(r"\s+\d.*$", "", loc).strip(" -/")

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

    return day, scene, timing, summary, cast_text, loc

def split_internal_scenes(line_objs, start_idx, end_idx, cast_cutoff):
    cuts = [start_idx]; overrides = [None]
    for k in range(start_idx + 1, end_idx):
        L = line_objs[k]
        if not any(w["x0"] < cast_cutoff for w in L["words"]):
            continue
        txt = L["text"]
        m = MID_SCENE_RX.search(txt)
        if not m: continue
        if not UPPER_LOC_HINT.search(txt):  # must look like a location line
            continue
        frac = re.search(r"\b\d+\s*/\s*\d+\b", txt)
        if frac and txt.find(m.group(1)) > frac.start():
            continue
        cuts.append(k); overrides.append(m.group(1))
    cuts.append(end_idx)
    ranges = []
    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i+1]
        ranges.append((s, e, overrides[i]))
    return ranges

def extract_scene_rows(pdf, rollen_map, cast_split_ratio=0.61, super_debug=False):
    rows = []
    dbg_pages = []
    for p_idx, page in enumerate(pdf.pages):
        words = page.extract_words() or []
        line_objs = group_words_into_lines(words, y_round=1)
        line_objs = normalize_line_objs(line_objs)
        headers = find_headers(line_objs)

        if super_debug:
            dbg_pages.append({
                "page": p_idx+1,
                "lines_first40": [L["text"] for L in line_objs[:40]],
                "headers": headers
            })

        for i, (h_idx, day, scene) in enumerate(headers):
            next_idx = headers[i+1][0] if i+1 < len(headers) else len(line_objs)
            cast_cutoff = page.width * cast_split_ratio
            subranges = split_internal_scenes(line_objs, h_idx, next_idx, cast_cutoff)

            for s_idx, e_idx, override_scene in subranges:
                d, s, t, summary, cast_text, loc = parse_scene_block(
                    page, line_objs, s_idx, e_idx, rollen_map, cast_split_ratio
                )
                if override_scene:
                    s = override_scene
                rows.append([d, s, t, summary, cast_text, loc])

    return rows, dbg_pages

# ──────────────────────────────────────────────────────────────
# DOCX helpers (top/bottom borders on demand)
# ──────────────────────────────────────────────────────────────
def clear_row_shading(row):
    for cell in row.cells:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = tcPr.find(qn('w:shd'))
        if shd is not None:
            tcPr.remove(shd)

def set_row_border(row, edge="bottom", size=24, color="000000", val="single"):
    for cell in row.cells:
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = tcPr.find(qn('w:tcBorders'))
        if tcBorders is None:
            tcBorders = OxmlElement('w:tcBorders')
            tcPr.append(tcBorders)
        node = tcBorders.find(qn(f'w:{edge}'))
        if node is None:
            node = OxmlElement(f'w:{edge}')
            tcBorders.append(node)
        node.set(qn('w:val'), val)
        node.set(qn('w:sz'), str(size))
        node.set(qn('w:color'), color)

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

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
if chron_file and break_file and st.button("Generate Breakdown"):
    with pdfplumber.open(chron_file) as pdf:
        rollen_map = build_rollen_map(pdf)
        rows, dbg_pages = extract_scene_rows(
            pdf, rollen_map, cast_split_ratio=cast_split_ratio, super_debug=super_debug
        )

    st.subheader("🔍 Parsed Row Debug Preview (first 15)")
    st.dataframe(pd.DataFrame([{
        "Day": d, "Scene": s, "Timing": t, "Summary": summary, "Cast": cast, "Location": loc
    } for d, s, t, summary, cast, loc in rows[:15]]))

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

    prev_loc = None
    for idx, (d, s, t, summary, cast, loc) in enumerate(rows):
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

        # ── New border logic:
        # Draw a thick TOP line when the location changes (start of a new block).
        if loc and loc != prev_loc:
            set_row_border(r, edge="top", size=24, color="000000", val="single")
        prev_loc = loc

        # No bottom border here; we’ll only close the table with a bottom border on the last row.

    # Close the table visually with a bottom line on the last row
    if len(table.rows) > 1:
        set_row_border(table.rows[-1], edge="bottom", size=24, color="000000", val="single")

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

    st.success("✅ Breakdown built successfully!")
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

st.markdown("""
<div class="custom-footer">
Built with ❤️ by <a href="https://ashwinanandani.com" class="custom-link" target="_blank" style="font-weight:400">a fan of the show</a> — 
contact via WhatsApp for big issues, treat with love, and stay kind.
</div>
""", unsafe_allow_html=True)