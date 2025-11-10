# Makeup & SFX Breakdown Builder (Streamlit)

A fast, opinionated tool that ingests a **Chronologie** PDF and a **Breakdown DOCX template**, then outputs a new DOCX **Makeup & SFX breakdown** table with correct scenes, timing, summary/location, cast, SFX and preserved notes.

The app is built with **Python + Streamlit + pdfplumber + python-docx** and includes PDF-specific heuristics for messy production documents (dangling headers, inline slashes, strike-through removals, etc.).

---

## What it does

- **Parses “ROLLEN”** from the Chronologie PDF to map `ID ➜ Character` (strips “ - Actor” suffixes and role notes).
- **Finds scene blocks** even when a header is split across lines (`day /` on one line and `12T1` on the next, or `day` + `I/T` + `12T1` across three).
- **Extracts columns**:
  - **Day** and **Scene** from the header
  - **Timing** (e.g., `I/T`, `A/N`, `I+T/…`; normalized to `I/T` when needed)
  - **Summary/Location** from the **left** column text after timing
  - **Cast & Doubles** from the **right** column using the Rollen ID map (plus “Komparsen” detection)
  - **SFX** and **Notes** are **preserved** from the uploaded DOCX template (matched by `Day + Scene`)
- **Removes strike-through lines** from the PDF (e.g., crossed-out schedule beats) by detecting thin horizontal rules and dropping intersecting words.
- **Normalizes text** (reduces duplicate commas and bad “ / ” separators).
- **Scene divider lines in DOCX**: thick **top** border when a row’s Summary looks like an ALL-CAPS location header (e.g., `BERLIN - TAG`). Light bottom borders elsewhere.

---

## Why these heuristics exist

Production PDFs are dirty:
- Scene headers often **wrap** across lines (e.g., day number, slash, scene id scattered), and sometimes **timing appears on its own line**.
- The **cast index** lives in a pseudo right column with numeric IDs that must be resolved against `ROLLEN`.
- PDFs include **editorial strike-outs** (thin lines) which must be ignored to match the actual schedule.
- PDFs use **spaced slashes** (`" / "`) as list separators; we convert to commas to avoid spurious splits.

---

## Inputs & Outputs

**Inputs**
1. `Chronologie PDF` — the original schedule/chronology. Must include a “ROLLEN” section with numeric IDs.
2. `Breakdown DOCX` (template) — any existing table that has the same first 7 columns (Day, Scene, Timing, Summary/Location, Cast & Doubles, SFX, Notes). Existing SFX/Notes are preserved when `Day + Scene` matches.

**Output**
- A new `Breakdown_filled_EP1.docx` saved client-side via Streamlit’s download button.
- A change log of added/removed `Day/Scene` keys vs the uploaded template.

---

## UI controls

- **Cast column split** — slider (default `0.61`) that defines the left/right column cutoff used to separate Summary (left) from Cast IDs (right) when PDFs aren’t perfectly aligned.
- **Debug** — shows counts and high-level info.
- **Super Debug** — dumps the first ~40 parsed lines per page and detected headers (useful when a scene is swallowed or over-split).

---

## How it works (core flow)

1. **Open PDF** with `pdfplumber`.
2. **Build Rollen map** by scanning the “ROLLEN” block; coalesce wrapped role lines; strip “ - Actor” suffixes and bracketed notes.
3. **Per page:**
   - Extract words → **drop words hit by strike-through lines** (thin/long horizontal rules).
   - Group into lines (Y-buckets), keep X order.
   - **Normalize headers**: merge patterns like `day "/"` + `scene`, `day` + `scene`, or `day` + `timing` + `scene`.
   - Detect header indices (`day / scene` or `day scene`).
   - For each header block, split words into left/right by the **cast_split_ratio**; pull **Timing** from the left text; summary starts after timing; **Cast** from the right (match IDs to Rollen).
4. **Create DOCX**:
   - Reuse table from uploaded template.
   - Clear body rows.
   - For each parsed row, insert values and **preserve SFX/Notes** if a `(Day, Scene)` match exists.
   - Add **top border** when the Summary looks like a location header (ALL-CAPS + dashes), add **light bottom** borders elsewhere.
   - Final cleanup pass to remove duplicate commas or stray role text.

---

## Project structure

