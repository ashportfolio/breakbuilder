import re
from io import BytesIO
import pdfplumber
from docx import Document
import streamlit as st
import pandas as pd
import datetime

# ─────────────────────────────────────────────
# UI SETUP
# ─────────────────────────────────────────────
st.set_page_config(page_title="Makeup & SFX Breakdown", page_icon="💋", layout="wide")
st.title("🎬 Makeup & SFX Breakdown — Final Formatter")
st.caption(f"Loaded: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")

chron_file = st.file_uploader("Upload Chronologie PDF", type=["pdf"])
break_file = st.file_uploader("Upload Breakdown DOCX Template", type=["docx"])
debug = st.checkbox("Debug Info")

# ─────────────────────────────────────────────
# REGEX DEFINITIONS
# ─────────────────────────────────────────────
HEADER_LINE = re.compile(r"^(\d+)\s*/\s*([0-9A-Z.]+)\s+([IA](?:\+[IA])?/[A-ZÄÖÜNTM]+)\s+(.+)$")
FOLLOW_LINE = re.compile(r"^\d+\s+[\d/]+\s+.*")
OMITTED_RX = re.compile(r"\bOMITTED\b", re.I)
ID_RX = re.compile(r"\b\d{1,4}\b")
CUTOFF_RX = re.compile(r"\b(Komparsen|Dauer)\b", re.I)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def clean_commas(s):
    if not s:
        return ""
    s = re.sub(r"(,\s*){2,}", ", ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" ,;/")

def _clean_role_label_basic(label):
    label = re.split(r"\s[-–—]\s", label, 1)[0]
    label = label.split(",", 1)[0]
    label = re.sub(r"\([^)]*\)", "", label)
    return re.sub(r"\s{2,}", " ", label).strip(" -–—\u2013 ")

# ─────────────────────────────────────────────
# BUILD ROLLEN MAP
# ─────────────────────────────────────────────
def build_rollen_map(pdf):
    rollen = {}
    collecting = False
    for p in pdf.pages:
        text = p.extract_text() or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for line in lines:
            if not collecting and re.match(r"^ROLLEN\b", line, re.I):
                collecting = True
                continue
            if not collecting:
                continue
            if re.search(r"\b(MÜNCHEN|KRANK|HAUS|ESTABLISHER|SZENE|INT|EXT)\b", line):
                return rollen
            m = re.match(r"^(\d{1,4})\s+(.+?)\s*(?:[-–—].*)?$", line)
            if not m:
                continue
            num, name = m.groups()
            name = _clean_role_label_basic(name)
            if any(bad in name.upper() for bad in ["OMITTED", "KOMPARS", "FAHRZEUG", "PATIENT"]):
                continue
            if len(name) < 2:
                continue
            rollen[num] = name
    return rollen

# ─────────────────────────────────────────────
# EXTRACT SCENES
# ─────────────────────────────────────────────
def extract_scenes(pdf, rollen_map):
    lines = []
    for p in pdf.pages:
        text = p.extract_text() or ""
        lines += [ln.strip() for ln in text.splitlines() if ln.strip()]

    scenes = []
    current = None

    for line in lines:
        if OMITTED_RX.search(line):
            continue

        header_match = HEADER_LINE.match(line)
        if header_match:
            if current:
                scenes.append(current)

            day, scene, timing, rest = header_match.groups()

            # handle cast IDs possibly glued to text (e.g., 107Leo)
            rest_spaced = re.sub(r"(\d)([A-ZÄÖÜ])", r"\1, \2", rest)
            header_ids = re.findall(r"\b\d{1,4}\b", rest_spaced)
            valid_header = [i for i in header_ids if i in rollen_map]
            header_cast = ", ".join(f"{i} {rollen_map[i]}" for i in valid_header)

            clean_loc = re.sub(r"\b\d{1,4}\b", "", rest_spaced)
            clean_loc = re.sub(r"\s{2,}", " ", clean_loc).strip(" ,;/")

            current = {
                "Day": day,
                "Scene": scene,
                "Timing": timing,
                "Location": clean_loc,
                "Summary": "",
                "Cast": header_cast
            }
            continue

        if current and FOLLOW_LINE.match(line):
            line = re.sub(r"^\d+\s+[\d/]+\s*", "", line).strip()

            cutoff_match = CUTOFF_RX.search(line)
            if cutoff_match:
                line = line[:cutoff_match.start()].strip()

            # detect IDs even if glued to words
            spaced_line = re.sub(r"(\d)([A-ZÄÖÜ])", r"\1, \2", line)
            ids = re.findall(r"\b\d{1,4}\b", spaced_line)
            valid_ids = [i for i in ids if i in rollen_map]
            for i in valid_ids:
                entry = f"{i} {rollen_map[i]}"
                if entry not in current["Cast"]:
                    current["Cast"] += (", " if current["Cast"] else "") + entry

            summary_text = re.sub(r"\b\d{1,4}\b", "", spaced_line).strip()
            current["Summary"] += (" " if current["Summary"] else "") + summary_text
            continue

        if current and not HEADER_LINE.match(line):
            cutoff_match = CUTOFF_RX.search(line)
            if cutoff_match:
                line = line[:cutoff_match.start()].strip()
            current["Summary"] += (" " if current["Summary"] else "") + line

    if current:
        scenes.append(current)

    # cleanup
    for sc in scenes:
        sc["Summary"] = clean_commas(sc["Summary"])
        sc["Location"] = clean_commas(sc["Location"])
        sc["Cast"] = clean_commas(sc["Cast"])
    return scenes

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if chron_file and break_file and st.button("Generate Breakdown"):
    with pdfplumber.open(chron_file) as pdf:
        rollen_map = build_rollen_map(pdf)
        scenes = extract_scenes(pdf, rollen_map)

    st.subheader("🔍 Parsed Scene Preview")
    st.dataframe(pd.DataFrame(scenes).head(30))

    doc = Document(break_file)
    t = doc.tables[0]
    while len(t.rows) > 1:
        t._tbl.remove(t.rows[1]._tr)

    first = True
    for sc in scenes:
        if not first:
            spacer = t.add_row()
            for c in spacer.cells:
                c.text = ""
        first = False

        r = t.add_row()
        summary_loc = f"{sc['Location']}\n{sc['Summary']}".strip()
        vals = [
            sc["Day"],
            sc["Scene"],
            sc["Timing"],
            summary_loc,
            clean_commas(sc["Cast"]),
            "",  # SFX left blank
            ""   # Notes left blank
        ]
        for i, v in enumerate(vals[:len(r.cells)]):
            r.cells[i].text = v

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    st.download_button(
        "📥 Download Clean Breakdown",
        buf,
        "Breakdown_filled_EP7_final.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True
    )

    if debug:
        st.json({
            "rollen_count": len(rollen_map),
            "scene_count": len(scenes),
            "sample_rollen": dict(list(rollen_map.items())[:10])
        })

# ─────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────
st.markdown("""
<div class='custom-footer'>
Built with ❤️ by <a href="https://ashwinanandani.com" target="_blank" style="font-weight:400">a fan of the show</a> —
contact via WhatsApp for big issues, treat with love, and stay kind.
</div>
""", unsafe_allow_html=True)