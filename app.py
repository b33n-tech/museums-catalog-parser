# app.py
import re
import pandas as pd
import streamlit as st
import requests

st.set_page_config(page_title="Catalogue Parser", layout="wide")
st.title("📚 Catalogue OCR → Tableau")

st.write("Choisis une méthode pour fournir le texte OCR :")

option = st.radio(
    "Source du texte OCR",
    ["📂 Uploader un fichier .txt", "🌍 Coller un lien vers un .txt en ligne"]
)

text = None

# --- OPTION 1 : Upload fichier ---
if option == "📂 Uploader un fichier .txt":
    uploaded_file = st.file_uploader("Dépose ton fichier OCR (.txt)", type=["txt"])
    if uploaded_file is not None:
        text = uploaded_file.read().decode("utf-8")

# --- OPTION 2 : URL du fichier texte ---
elif option == "🌍 Coller un lien vers un .txt en ligne":
    url = st.text_input("Entre l'URL directe vers un fichier texte (.txt)")
    if url:
        try:
            response = requests.get(url)
            response.raise_for_status()
            text = response.text
            st.success("Fichier récupéré avec succès ✅")
        except Exception as e:
            st.error(f"Erreur lors du téléchargement : {e}")

# --- Parsing seulement si texte dispo ---
if text:
    # --- Nettoyage rapide du texte ---
    text = re.sub(r"\s+", " ", text)  # réduire espaces multiples
    text = re.sub(r"—", "-", text)    # normaliser tirets
    text = text.replace("??", "Inconnu")

    # --- Découpage des notices par numéro ---
    entries = re.split(r"\s(?=\d{3,4}\s)", text)

    data = []
    for entry in entries:
        entry = entry.strip()
        if not entry or not re.match(r"^\d{3,4}", entry):
            continue

        # --- Extraction des champs principaux ---
        numero = re.match(r"^(\d{3,4})", entry).group(1)

        objet_match = re.search(r"^\d{3,4}\s+(.*?)(?=(?:IVe|Ve|IIIe|IIe|Ie)\s*s\.)", entry)
        objet = objet_match.group(1).strip() if objet_match else ""

        datation_match = re.search(r"((?:[IVX]{1,3}e|\d+)(?:\s*moitié)?\s*s\.?\s*av\.?\s*J\.-C\.)", entry)
        datation = datation_match.group(1) if datation_match else ""

        matiere_match = re.search(r"-\s*(Marbre|Bronze|Terre cuite)", entry, re.IGNORECASE)
        matiere = matiere_match.group(1) if matiere_match else ""

        provenance_match = re.search(r"-\s*([^-.]+?)\s*-\s*[^-.]+", entry)
        provenance = provenance_match.group(1).strip() if provenance_match else ""

        lieu_match = re.search(r"-\s*([A-Z][^.;]+)", entry)
        lieu = lieu_match.group(1).strip() if lieu_match else ""

        refs_match = re.search(r"(Cf\..+)$", entry)
        refs = refs_match.group(1).strip() if refs_match else ""

        data.append({
            "Numéro": numero,
            "Objet": objet,
            "Datation": datation,
            "Matière": matiere,
            "Provenance": provenance,
            "Lieu actuel": lieu,
            "Références": refs
        })

    # --- DataFrame final ---
    df = pd.DataFrame(data)

    st.success(f"{len(df)} notices extraites ✅")
    st.dataframe(df, use_container_width=True)

    # --- Export CSV ---
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Télécharger en CSV",
        data=csv,
        file_name="catalogue.csv",
        mime="text/csv",
    )
