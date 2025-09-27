# app.py
"""
Catalogue OCR -> Tableau
Streamlit app:
- Upload .txt OR paste URL OR paste raw text
- Parses entries identified by artwork numbers (e.g. 746, 749-750)
- Detects page markers like "—  138  —" and injects page into each entry
- Extracts: Numéros, Page, Description, Datation, Matière, Provenance, Lieu actuel, Références, Commentaire
"""
import re
from typing import List, Dict, Optional
import pandas as pd
import streamlit as st
import requests

st.set_page_config(page_title="Catalogue Parser - OCR → Tableau", layout="wide")
st.title("📚 Catalogue OCR → Tableau (Streamlit)")

st.markdown(
    "Options : upload `.txt`, coller une URL directe vers un `.txt`, ou coller le texte brut.\n\n"
    "L'outil repère les numéros d'œuvre (ex. `746`, `749-750`) et les pages (`—  138  —`) et tente d'extraire "
    "Description / Fiche technique / Références / Commentaire."
)

# -------------------------
# Utils / heuristics
# -------------------------

# Correction map pour coquilles courantes (à compléter)
CORRECTIONS = {
    "British Muséum": "British Museum",
    "Furtwsengler": "Furtwängler",
    "Furtwaengler": "Furtwängler",
    "Brunn-Bruckmann": "Brunn-Bruckmann",
    "Friederichs-Wolters": "Friedrichs-Wolters",
    "Mûller-Wieseler-Wernicke": "Müller-Wieseler-Wernicke",
    # ajoutes-en d'autres selon besoin
}


def apply_corrections(text: str) -> str:
    for k, v in CORRECTIONS.items():
        text = re.sub(re.escape(k), v, text, flags=re.IGNORECASE)
    return text


PAGE_MARKER_RE = re.compile(r"^[\-\—\–\s]{0,3}\s*(\d{1,4})\s*[\-\—\–\s]{0,3}$")
ENTRY_START_RE = re.compile(r"^\s*(\d{1,4}(?:-\d{1,4})?)(?:[.)\s])")  # ex: "746 " or "746." or "746-747 "
REFS_RE = re.compile(r"\bCf\.\s*([^—;\n]+(?:[—;][^—;\n]+)*)", re.IGNORECASE)  # capture after "Cf."
DATATION_RE = re.compile(
    r"(?:(?:Fin|Début|Milieu|1ère|1re|2e|2ème|2e moitié)?\s*(?:du\s*)?(?:[IVX]{1,3}(?:e|er|ème)?(?:\s*(?:ou|-)\s*[IVX]{1,3}(?:e|er|ème)?)?\s*(?:s\.|siècle))\s*(?:av\.?\s*J\.-C\.|av\.?\s*J.-C\.|av\.?\s*JC\.|ap\.?r?\.?J\.-C\.)|(?:I{1,3}e|IIe|IIIe|IVe|Ve)\s*s\.\s*av\.?\s*J\.-C\.)",
    re.IGNORECASE,
)
MATERIAU_RE = re.compile(r"\b(Marbre|Bronze|Terre cuite|Terre-cuite|Plâtre|Argile|Pierre|Or|Étain)\b", re.IGNORECASE)
MUSEE_RE = re.compile(r"\b(Musée|Louvre|British Museum|Glyptothèque|Naples|Vatican|Berlin|Munich|Paris|Rome|Athènes|Vienne)\b", re.IGNORECASE)
PROVENANCE_HINTS = ["Provenance", "Près de", "Provenance inconnue", "d' ", "de ", "Attique", "Corinthe", "Herculanum", "Athènes", "Le Pirée", "Près"]

def normalize_text(raw: str) -> str:
    # Normalize unicode dashes/spaces, keep line breaks but reduce excessive spaces
    txt = raw.replace("\r\n", "\n").replace("\r", "\n")
    txt = txt.replace("\u2013", "-").replace("\u2014", "-").replace("\u2012", "-")
    # Fix many consecutive spaces but keep single spaces and newlines
    txt = re.sub(r"[ ]{2,}", " ", txt)
    # some OCRs put spaces between letters, remove isolated repeated single-letter spaces like "A c t i o n"?
    # (risky) -> skip aggressive letter join; we rely on later heuristics.
    txt = apply_corrections(txt)
    return txt


# -------------------------
# Parsing pipeline
# -------------------------
def split_into_blocks(text: str) -> List[Dict]:
    """
    Walk line-by-line:
    - track current_page when encountering a page marker line like "—  138  —"
    - start a new block when a line begins with an entry number (e.g. "746 " or "749-750 ")
    - collect lines into current block (joined with spaces)
    Returns list of dicts: {'num_str': '746' or '749-750', 'page': 138, 'raw': '...'}
    """
    lines = text.splitlines()
    blocks = []
    current_page: Optional[int] = None
    current_block: Optional[Dict] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue  # skip blank lines (OCR often has many)
        # detect page marker (line that is just like "—  138  —" or "— 138 —")
        pm = PAGE_MARKER_RE.match(line)
        if pm:
            current_page = int(pm.group(1))
            # do not attach page as its own block; it's a marker
            continue

        # detect entry start
        m = ENTRY_START_RE.match(line)
        if m:
            # start new block
            num_str = m.group(1)
            # If there's an existing block, finalize it
            if current_block:
                blocks.append(current_block)
            current_block = {"num_str": num_str, "page": current_page, "raw_lines": [line[m.end():].strip()]}
        else:
            # continuation line => if there's no current block, this might be a global comment:
            if current_block:
                current_block["raw_lines"].append(line)
            else:
                # no current block: treat as orphan comment - attach to a special block or skip
                # We'll append as a special "comment_only" block with num_str = None
                # If last block exists and has no comment, attach; else create a floating block
                if blocks and "floating_comments" not in blocks[-1]:
                    blocks[-1].setdefault("floating_comments", []).append(line)
                else:
                    # create a floating block
                    blocks.append({"num_str": None, "page": current_page, "raw_lines": [line]})

    # append last block
    if current_block:
        blocks.append(current_block)

    # Merge raw_lines into raw text
    for b in blocks:
        b["raw"] = " ".join(b.get("raw_lines", [])).strip()
        b.pop("raw_lines", None)

    return blocks


def extract_fields(block: Dict) -> Dict:
    """
    Given a block with 'num_str', 'page', 'raw' -> extract structured fields.
    """
    raw = block.get("raw", "").strip()
    # Apply small cleanup
    raw = re.sub(r"\s*-\s*", " — ", raw)  # normalize hyphen blocks into em-dash spaces
    raw = re.sub(r"\s+", " ", raw).strip()
    result = {
        "Numéros": block.get("num_str"),
        "Page": block.get("page"),
        "Description": "",
        "Datation": "",
        "Matière": "",
        "Provenance": "",
        "Lieu actuel": "",
        "Références": "",
        "Commentaire": ""
    }

    if not raw:
        return result

    # 1) Références (Cf.) - take everything from last Cf. occurrence to end of raw (but only that clause)
    refs = REFS_RE.findall(raw)
    if refs:
        # join multiple Cf. matches
        refs_text = " ; ".join([r.strip() for r in refs])
        result["Références"] = "Cf. " + refs_text
        # remove refs from raw for subsequent parsing
        raw_no_refs = REFS_RE.sub("", raw)
    else:
        raw_no_refs = raw

    # 2) Datation
    dat_m = DATATION_RE.search(raw_no_refs)
    if dat_m:
        result["Datation"] = dat_m.group(0).strip()
        # remove datation from raw copy
        raw_no_dat = raw_no_refs.replace(result["Datation"], " ")
    else:
        raw_no_dat = raw_no_refs

    # 3) Matière
    mat_m = MATERIAU_RE.search(raw_no_dat)
    if mat_m:
        result["Matière"] = mat_m.group(1).strip()
        # do not aggressively remove; will be separated below

    # 4) Split by em-dash tokens (commonly used to separate fiche technique items)
    parts = [p.strip() for p in re.split(r"—", raw_no_dat) if p.strip()]
    # Common pattern in parts: [Description, Datation, Matière/Provenance, Lieu actuel, Refs]
    # Heuristics:
    if parts:
        # assume first part is description until it looks like a fiche technique (contains 'av. J.-C.' or a material or 'Provenance' or 'Musée')
        first = parts[0]
        if (DATATION_RE.search(first) or MATERIAU_RE.search(first) or MUSEE_RE.search(first) or any(pfx in first for pfx in PROVENANCE_HINTS)):
            # first part seems like fiche technique; keep description empty or short
            result["Description"] = ""
        else:
            # description is first part
            result["Description"] = first

    # scan remaining parts to fill provenance and lieu
    for p in parts[1:] if len(parts) > 1 else []:
        # datation
        if not result["Datation"]:
            d = DATATION_RE.search(p)
            if d:
                result["Datation"] = d.group(0).strip()
                continue
        # matière
        if not result["Matière"]:
            m = MATERIAU_RE.search(p)
            if m:
                result["Matière"] = m.group(1).strip()
                # continue scanning; material could be in same part with provenance
        # musée / lieu
        if MUSEE_RE.search(p) or re.search(r"\b[A-Z][a-z]{2,}\s*,\s*[A-Z][a-z]{2,}\b", p):
            # heuristique: if contains 'Musée' or 'Louvre' or pattern 'City, Museum' -> Lieu actuel
            result["Lieu actuel"] = p
            continue
        # provenance hints
        if any(hint.lower() in p.lower() for hint in PROVENANCE_HINTS):
            result["Provenance"] = p
            continue

    # If no em-dash parsing helped, fallback: try to parse raw_no_dat by commas / periods
    if not result["Lieu actuel"] and MUSEE_RE.search(raw_no_dat):
        result["Lieu actuel"] = raw_no_dat  # fallback to raw containing museum

    # If description empty, attempt to extract from the beginning of the raw text up to first fiche token
    if not result["Description"]:
        # take substring from start up to first occurrence of datation or material or '—' in original raw
        first_marker_pos = len(raw)
        for marker in [" av. J.-C.", "—", "Marbre", "Bronze", "Terre cuite", "Cf."]:
            pos = raw.find(marker)
            if pos != -1 and pos < first_marker_pos:
                first_marker_pos = pos
        desc = raw[:first_marker_pos].strip()
        # strip leading numbers/titling left
        if re.match(r"^\d", desc):
            # remove a leading stray number if present
            desc = re.sub(r"^\d{1,4}(?:-\d{1,4})?[\.\s]*", "", desc).strip()
        result["Description"] = desc

    # leftover / comment: take what's left after removing description, datation, refs, and common parts
    leftover = raw
    for to_remove in [result["Description"], result["Datation"], result["Références"]]:
        if to_remove:
            leftover = leftover.replace(to_remove, " ")
    # also remove material and lieu if they appear verbatim
    if result["Matière"]:
        leftover = leftover.replace(result["Matière"], " ")
    if result["Lieu actuel"]:
        leftover = leftover.replace(result["Lieu actuel"], " ")
    if result["Provenance"]:
        leftover = leftover.replace(result["Provenance"], " ")

    leftover = re.sub(r"\s+", " ", leftover).strip()
    # Clean obvious leading/trailing punctuation
    leftover = leftover.strip(" ,;.-")
    result["Commentaire"] = leftover

    return result


# -------------------------
# Streamlit UI
# -------------------------
st.sidebar.header("Options")
opt = st.sidebar.multiselect("Colonnes à inclure dans l'export", ["Numéros", "Page", "Description", "Datation", "Matière", "Provenance", "Lieu actuel", "Références", "Commentaire"], default=["Numéros", "Page", "Description", "Datation", "Matière", "Lieu actuel", "Références"])

input_mode = st.radio("Source du texte OCR :", ("📂 Upload .txt", "🌍 URL directe vers .txt", "📋 Coller le texte"))

raw_text: Optional[str] = None

if input_mode == "📂 Upload .txt":
    up = st.file_uploader("Dépose ton fichier .txt (OCR)", type=["txt"])
    if up:
        raw_text = up.read().decode("utf-8", errors="replace")
elif input_mode == "🌍 URL directe vers .txt":
    url_inp = st.text_input("Colle l'URL directe vers le .txt (ex: archive.org stream .txt)")
    if st.button("Récupérer le fichier"):
        if not url_inp:
            st.error("Donne d'abord une URL.")
        else:
            try:
                r = requests.get(url_inp, timeout=15)
                r.raise_for_status()
                raw_text = r.text
                st.success("Fichier récupéré ✅")
            except Exception as e:
                st.error(f"Erreur : {e}")
elif input_mode == "📋 Coller le texte":
    raw_text = st.text_area("Colle ici le texte OCR (long)", height=300)

if raw_text:
    # Normalize & parse
    norm = normalize_text(raw_text)
    blocks = split_into_blocks(norm)
    st.info(f"{len(blocks)} blocs détectés (certains pourront être des commentaires flottants).")

    # Convert blocks to records
    records = []
    for b in blocks:
        # skip blocks that are purely floating comments without num
        if b.get("num_str") is None and b.get("raw", "").strip():
            # attach as a general comment row if you want; for now, include but mark Numéros None
            rec = extract_fields(b)
            records.append(rec)
        elif b.get("num_str"):
            rec = extract_fields(b)
            records.append(rec)

    df = pd.DataFrame(records)

    # Ensure column order
    cols = ["Numéros", "Page", "Description", "Datation", "Matière", "Provenance", "Lieu actuel", "Références", "Commentaire"]
    df = df[[c for c in cols if c in df.columns]]

    st.success(f"{len(df)} notices structurées (hors blocs vides).")
    st.dataframe(df, use_container_width=True)

    # Export buttons
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Télécharger CSV", csv, file_name="catalogue_parsed.csv", mime="text/csv")

    # Excel export
    try:
        import io
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="catalogue")
        st.download_button("⬇️ Télécharger XLSX", buffer.getvalue(), file_name="catalogue_parsed.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception:
        # openpyxl may not be installed; skip silently
        pass

    # Quick stats / inspect
    st.markdown("### Quelques contrôles rapides")
    st.write("Exemples de notices sans datation détectée (à corriger manuellement):")
    missing_dates = df[df["Datation"].astype(bool) == False]
    st.write(missing_dates.head(10))

    st.markdown("### Échantillon brut (bloc -> raw)")
    # show raw blocks with page and num for debugging
    if st.checkbox("Afficher blocs détectés (raw)"):
        for i, b in enumerate(blocks[:200]):
            st.markdown(f"**Bloc #{i} — Numéros:** {b.get('num_str')} — Page: {b.get('page')}")
            st.text(b.get("raw"))

    st.info("Astuces :\n- Affine la map CORRECTIONS si certaines coquilles reviennent souvent.\n- Ajuste les regex DATATION_RE / MATERIAU_RE selon ton texte.\n- Si beaucoup d'entrées sont fusionnées ou cassées, essaie de prétraiter le .txt pour remettre des retours à la ligne aux bons endroits.")
else:
    st.info("Fournis un fichier .txt, une URL ou colle le texte pour démarrer.")
