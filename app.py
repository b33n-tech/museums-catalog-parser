# app.py
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Catalogue Parser", layout="wide")

st.title("📚 Catalogue OCR → Tableau")

uploaded_file = st.file_uploader("Dépose ton fichier OCR (.txt)", type=["txt"])

if uploaded_file is not None:
    text = uploaded_file.read().decode("utf-8")

    # --- Nettoyage rapide du texte ---
    text = re.sub(r"\s+", " ", text)  # réduire espaces multiples
    text = re.sub(r"—", "-", text)    # normaliser tirets
    text = text.replace("??", "Inconnu")

    # --- Découpage des notices par numéro ---
    # Exemple : "589 Buste de Dionysos..."
    entries = re.split(r"\s(?=\d{3,4}\s)", text)

    data = []
    for entry in entries:
        entry = entry.strip()
        if not entry or not re.match(r"^\d{3,4}", entry):
            continue  # on saute les bouts sans numéro

        # --- Extraction des champs principaux ---
        num_match = re.match(r"^(\d{3,4})", entry)
        numero = num_match.group(1) if num_match else ""

        # Objet : jusqu'à la première phrase complète ou saut
        objet_match = re.search(r"^\d{3,4}\s+(.*?)(?=(?:IVe|Ve|IIIe|IIe|Ie)\s*s\.)", entry)
        objet = objet_match.group(1).strip() if objet_match else ""

        # Datation
        datation_match = re.search(r"((?:[IVX]{1,3}e|\d+)(?:\s*moitié)?\s*s\.?\s*av\.?\s*J\.-C\.)", entry)
        datation = datation_match.group(1) if datation_match else ""

        # Matière
        matiere_match = re.search(r"-\s*(Marbre|Bronze|Terre cuite)", entry, re.IGNORECASE)
        matiere = matiere_match.group(1) if matiere_match else ""

        # Provenance
        provenance_match = re.search(r"-\s*([^-.]+?)\s*-\s*[^-.]+", entry)
        provenance = provenance_match.group(1).strip() if provenance_match else ""

        # Lieu actuel (musée / ville)
        lieu_match = re.search(r"-\s*([A-Z][^.;]+)", entry)
        lieu = lieu_match.group(1).strip() if lieu_match else ""

        # Références = tout ce qui suit "Cf." ou après le dernier point
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
