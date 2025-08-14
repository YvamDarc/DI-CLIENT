# app_client.py — Client (compact + tabulaire)
# - Lit un JSON de questions
# - Réponses texte éditables dans un tableau
# - Upload de justificatifs par n° de question (renommage)
# - Brouillon + export CSV récapitulatif

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

import streamlit as st
import pandas as pd

# ---------- Répertoires ----------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "client_data"
UPLOADS_DIR = DATA_DIR / "uploads"
RESP_DIR = DATA_DIR / "responses"
DRAFTS_DIR = DATA_DIR / "drafts"
for p in (DATA_DIR, UPLOADS_DIR, RESP_DIR, DRAFTS_DIR):
    p.mkdir(parents=True, exist_ok=True)

# ---------- Helpers ----------
def slugify(s: str) -> str:
    import re
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s).strip("_")
    return s or "x"

def load_json_questions(file_or_path) -> Dict[str, Any]:
    if hasattr(file_or_path, "read"):
        data = json.load(file_or_path)
    else:
        data = json.loads(Path(file_or_path).read_text(encoding="utf-8"))
    if "questions" not in data or not isinstance(data["questions"], list):
        raise ValueError("JSON invalide : champ 'questions' manquant.")
    data.setdefault("client_id", "client_sans_id")
    # normalise en DataFrame pour l’édition
    df = pd.DataFrame(data["questions"])
    # colonnes attendues (créées si manquantes)
    needed = ["numero","date","libelle","question","montant","piece","sous_compte","groupe"]
    for c in needed:
        if c not in df.columns: df[c] = ""
    # colonne Réponse vide au départ
    if "reponse" not in df.columns:
        df["reponse"] = ""
    return data["client_id"], df

def draft_path(client_id: str) -> Path:
    return DRAFTS_DIR / f"{slugify(client_id)}.json"

def load_draft_answers(client_id: str) -> Dict[str, str]:
    p = draft_path(client_id)
    if p.exists():
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            return j.get("answers", {})
        except Exception:
            return {}
    return {}

def save_draft_answers(client_id: str, answers: Dict[str, str]):
    p = draft_path(client_id)
    p.write_text(json.dumps({"answers": answers}, ensure_ascii=False, indent=2), encoding="utf-8")

def response_csv_path(client_id: str) -> Path:
    return RESP_DIR / f"{slugify(client_id)}.csv"

def append_responses_csv(client_id: str, df: pd.DataFrame):
    out = response_csv_path(client_id)
    # colonnes proprement ordonnées
    cols = ["numero","date","libelle","montant","piece","groupe","sous_compte","question","reponse","justificatifs"]
    for c in cols:
        if c not in df.columns: df[c] = ""
    df = df[cols].copy()
    df.insert(0, "client_id", client_id)
    df.insert(1, "timestamp_utc", pd.Timestamp.utcnow().isoformat())

    if out.exists():
        old = pd.read_csv(out)
        all_df = pd.concat([old, df], ignore_index=True)
    else:
        all_df = df
    all_df.to_csv(out, index=False)

def save_uploaded_file(client_id: str, numero: Optional[int], uploaded, seq: int) -> str:
    client_dir = UPLOADS_DIR / slugify(client_id)
    client_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(uploaded.name).suffix.lower()
    num = f"{int(numero):03d}" if pd.notna(numero) and str(numero).strip() != "" else "000"
    fname = f"{slugify(client_id)}_{num}_justif_{seq}{ext}"
    dest = client_dir / fname
    with open(dest, "wb") as f:
        f.write(uploaded.getbuffer())
    return str(dest.relative_to(BASE_DIR))

# ---------- UI ----------
st.set_page_config(page_title="Formulaire client", page_icon="🧾", layout="wide")
st.title("🧾 Formulaire client (vue compacte)")
st.caption("Répondez dans le tableau. Chargez vos justificatifs par numéro de question.")

# 1) Charger le JSON
qp = st.query_params
json_hint = qp.get("json", "")
st.subheader("1) Charger le fichier de questions")
c1, c2 = st.columns([2,1])
with c1:
    up = st.file_uploader("Fichier JSON de questions", type=["json"])
with c2:
    path_str = st.text_input("Chemin JSON (optionnel)", value=str(json_hint))

client_id = None
df = None
if up is not None:
    client_id, df = load_json_questions(up)
elif path_str:
    try:
        client_id, df = load_json_questions(path_str)
    except Exception as e:
        st.error(f"Impossible de lire le JSON : {e}")

if df is None:
    st.info("Importez le JSON pour commencer.")
    st.stop()

st.markdown(f"**Client :** `{client_id}` — **Questions :** {len(df)}")

# Charger brouillon (colonne 'reponse')
draft_map = load_draft_answers(client_id)
if draft_map:
    # applique sur df (par numéro)
    df = df.copy()
    for i, row in df.iterrows():
        key = str(row.get("numero",""))
        if key in draft_map:
            df.at[i, "reponse"] = draft_map[key]

# 2) Tableau éditable (réponse texte)
st.subheader("2) Répondre dans le tableau")
view_cols = {
    "numero": "N°",
    "date": "Date",
    "libelle": "Libellé",
    "question": "Question",
    "montant": "Montant",
    "piece": "Pièce",
    "groupe": "Groupe",
    "sous_compte": "Sous-compte",
    "reponse": "Réponse"
}
df_view = df[list(view_cols.keys())].copy()

edited = st.data_editor(
    df_view,
    num_rows="fixed",
    use_container_width=True,
    hide_index=True,
    column_config={
        "numero": st.column_config.NumberColumn(view_cols["numero"], width="small"),
        "date": st.column_config.TextColumn(view_cols["date"], help="AAAA-MM-JJ"),
        "libelle": st.column_config.TextColumn(view_cols["libelle"]),
        "question": st.column_config.TextColumn(view_cols["question"]),
        "montant": st.column_config.NumberColumn(view_cols["montant"], step=0.01),
        "piece": st.column_config.TextColumn(view_cols["piece"]),
        "groupe": st.column_config.TextColumn(view_cols["groupe"], width="small"),
        "sous_compte": st.column_config.TextColumn(view_cols["sous_compte"], width="small"),
        "reponse": st.column_config.TextColumn(view_cols["reponse"]),
    },
    key="editor_main"
)

# sauvegarde brouillon (par numéro)
answers_map = {}
for _, r in edited.iterrows():
    key = str(r.get("numero",""))
    answers_map[key] = r.get("reponse","") or ""
save_draft_answers(client_id, answers_map)

# 3) Justificatifs : choisir un N° puis uploader (renommage)
st.subheader("3) Joindre des justificatifs")
nums = [n for n in edited["numero"].tolist() if pd.notna(n)]
sel_num = st.selectbox("Choisissez le N° de question", options=sorted(nums) if nums else [])
ups = st.file_uploader(
    "Déposer vos fichiers pour cette question",
    type=["pdf","png","jpg","jpeg","webp","tif","tiff","doc","docx","xls","xlsx","csv","txt"],
    accept_multiple_files=True,
    key="uploads_for_question"
)
if sel_num and ups:
    start_seq = 1
    saved = []
    for i, f in enumerate(ups, start=start_seq):
        rel = save_uploaded_file(client_id, sel_num, f, i)
        saved.append(rel)
    if saved:
        st.success(f"{len(saved)} fichier(s) enregistré(s) pour la question {int(sel_num)}.")
        st.write("Fichiers :", *[f"`{p}`" for p in saved], sep="\n")

st.divider()

# 4) Finaliser
st.subheader("4) Finaliser / Export CSV")
if st.button("📨 Envoyer / Exporter CSV"):
    # merge des réponses dans df
    df_out = df.copy()
    df_out = df_out.merge(edited[["numero","reponse"]], on="numero", how="left")
    # pas de suivi centralisé des fichiers déjà envoyés (stockés au disque), mais on met un placeholder
    df_out["justificatifs"] = ""  # chemins des fichiers non centralisés ici
    append_responses_csv(client_id, df_out)
    st.success("Vos réponses ont été enregistrées.")
    out = response_csv_path(client_id)
    if out.exists():
        with open(out, "rb") as fh:
            st.download_button("Télécharger le récapitulatif (CSV)", fh, file_name=out.name)
