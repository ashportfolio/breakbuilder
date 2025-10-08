import re
import datetime
from io import BytesIO
import pdfplumber
from docx import Document
from docx.shared import Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import streamlit as st
import pandas as pd

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
    font-weight: 500 !important;
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
    font-weight: 500;
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
    font-weight: 500;
    text-align: center;
    margin-top: 0.5rem;
    margin-bottom: 1.2rem;
    font-size: 1.05rem;'>
📂 Please upload both files below, then click <b>Generate Breakdown</b> to begin.
</div>
""", unsafe_allow_html=True)

chron_file = st.file_uploader("Upload Chronologie PDF", type=["pdf"])
break_file = st.file_uploader("Upload Previous Breakdown DOCX (template)", type=["docx"])

try:
    dev_mode = st.secrets["dev_mode"].lower() == "true"
except:
    dev_mode = True

if dev_mode:
    c1, c2, c3 = st.columns([1,1,2])
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

# Footer
st.markdown("""
<div class="custom-footer">
Built with ❤️ by <a href="https://ashwinanandani.com" class="custom-link" target="_blank">a fan of the show</a> — 
contact via WhatsApp for big issues, treat with love, and stay kind.
</div>
""", unsafe_allow_html=True)