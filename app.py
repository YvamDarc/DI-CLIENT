# app_client.py — Application client
# Lit un JSON de questions (généré par l'app admin),
# affiche une réponse texte + upload de justificatifs par question,
# renomme les fichiers: {client_id}_{numero:03d}_justif_{k}{ext},
# enregistre un CSV des réponses + sauvegarde de brouillon.

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

import streamlit as st
import pandas as pd

# ----------------- Répertoires (créés si besoin) -----------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "client_data"
RESP_DIR = DATA_DIR / "responses"
UPLOADS_DIR = DATA_DIR / "uploads"
DRAFTS_DIR = DATA_DIR / "drafts"

for p in (DATA_DIR, RESP_DIR, UPLOADS_DIR, DRAFTS_DIR):
    p.mkdir(parents=True, exist_ok=True)

# ----------------- Helpers -----------------
def slugify(s: str) -> str:
    """
    Simplifie une chaîne pour l'utiliser dans un nom de fichier.
    """
    import re
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s-]+", "_", s).strip("_")
    return s or "x"

def load_json_questions(file) -> Dict[str, Any]:
    """
    Charge le JSON de questions. Schéma attendu:
    {
      "client_id": "...",
      "questions": [
        {
          "numero": 1,
          "date": "2025-02-24",
          "libelle": "...",
          "montant": 123.45,
          "piece": "REF/PIECE",
          "question": "...",
          "sous_compte": "...",
          "groupe": "Fournisseurs (401)",
          "type": "mixte"
        },
        ...
      ]
    }
    """
    try:
        if hasattr(file, "read"):
            data = json.load(file)
        else:
            data = json.loads(Path(file).read_text(encoding="utf-8"))
        # Validation minimale
        if "questions" not in data or not isinstance(data["questions"], list):
            raise ValueError("JSON invalide : champ 'questions' manquant.")
        data.setdefault("client_id", "client_sans_id")
        return data
    except Exception as e:
        st.error(f"Erreur de lecture du JSON: {e}")
        raise

def draft_path(client_id: str) -> Path:
    return DRAFTS_DIR / f"{slugify(client_id)}.json"

def load_draft(client_id: str) -> Dict[str, Any]:
    p = draft_path(client_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_draft(client_id: str, answers: Dict[str, Any]):
    p = draft_path(client_id)
    p.write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")

def response_csv_path(client_id: str) -> Path:
    return RESP_DIR / f"{slugify(client_id)}.csv"

def append_responses_csv(client_id: str, rows: List[Dict[str, Any]]):
    out = response_csv_path(client_id)
    df_new = pd.DataFrame(rows)
    if out.exists():
        df_old = pd.read_csv(out)
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(out, index=False)

def save_uploaded_file(client_id: str, numero: Optional[int], uploaded, seq: int) -> str:
    """
    Sauvegarde un fichier uploadé avec un nom standardisé:
    {clientid}_{numero:03d}_justif_{seq}{ext}
    Retourne le chemin relatif.
    """
    client_dir = UPLOADS_DIR / slugify(client_id)
    client_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(uploaded.name).suffix.lower()
    num_str = f"{int(numero):03d}" if (numero is not None) else "000"
    filename = f"{slugify(client_id)}_{num_str}_justif_{seq}{ext}"
    save_path = client_dir / filename
    with open(save_path, "wb") as f:
        f.write(uploaded.getbuffer())
    return str(save_path.relative_to(BASE_DIR))

# ----------------- UI -----------------
st.set_page_config(page_title="Formulaire client", page_icon="🧾", layout="wide")

st.title("🧾 Formulaire client")
st.caption("Répondez aux questions et joignez les justificatifs. Votre brouillon est enregistré automatiquement.")

# Lecture du JSON: via query param ?json=... ou upload manuel
qp = st.query_params
json_hint = qp.get("json", "")

st.subheader("1) Charger le fichier de questions (JSON)")
colj1, colj2 = st.columns([2,1])
with colj1:
    json_file = st.file_uploader("Fichier JSON généré par votre comptable", type=["json"])
with colj2:
    st.write("Ou indiquez le nom de fichier (si présent côté serveur) :")
    json_path_str = st.text_input("Chemin JSON (optionnel)", value=str(json_hint))

data = None
if json_file is not None:
    data = load_json_questions(json_file)
elif json_path_str:
    try:
        data = load_json_questions(json_path_str)
    except Exception:
        data = None

if not data:
    st.info("Importez le JSON pour commencer.")
    st.stop()

client_id = data.get("client_id", "client_sans_id")
questions = data.get("questions", [])

st.markdown(f"**Client :** `{client_id}` — **Nombre de questions :** {len(questions)}")

# Charger / initialiser brouillon
draft = load_draft(client_id)
answers: Dict[str, Any] = draft.get("answers", {})

# Filtres côté client (confort)
with st.expander("🔎 Filtres d'affichage (optionnel)"):
    groups = sorted({q.get("groupe","") for q in questions if q.get("groupe")})
    sous_comptes = sorted({q.get("sous_compte","") for q in questions if q.get("sous_compte")})
    selected_groups = st.multiselect("Filtrer par groupe", options=groups, default=groups)
    selected_sc = st.multiselect("Filtrer par sous-compte", options=sous_comptes, default=sous_comptes)
    search = st.text_input("Recherche texte (dans libellé / question)")

def match_filters(q: Dict[str, Any]) -> bool:
    if 'selected_groups' in locals():
        if q.get("groupe","") not in selected_groups: return False
    if 'selected_sc' in locals():
        if q.get("sous_compte","") not in selected_sc: return False
    if 'search' in locals() and search:
        s = (q.get("libelle","") + " " + q.get("question","")).lower()
        if search.lower() not in s: return False
    return True

# Tri par groupe/sous-compte/numero
def sort_key(q: Dict[str, Any]):
    return (q.get("groupe",""), q.get("sous_compte",""), q.get("numero") or 0, q.get("date",""), q.get("libelle",""))

questions_sorted = sorted([q for q in questions if match_filters(q)], key=sort_key)

st.subheader("2) Répondre aux questions et joindre des justificatifs")

# Boucle d'affichage par groupe / sous-compte
current_group = None
current_sc = None
uploaded_map: Dict[str, List[str]] = {}  # qkey -> list of saved paths

for q in questions_sorted:
    grp = q.get("groupe","")
    sc = q.get("sous_compte","")
    if grp != current_group or sc != current_sc:
        st.markdown(f"### {grp or 'Groupe'} — Sous-compte {sc or '-'}")
        current_group, current_sc = grp, sc

    numero = q.get("numero")
    qkey = f"q_{numero if numero is not None else id(q)}"  # clé stable
    date = q.get("date") or ""
    libelle = q.get("libelle") or ""
    montant = q.get("montant", "")
    montant_str = ""
    if montant not in ("", None):
        try:
            montant_str = f"{float(montant):,.2f} €".replace(",", " ").replace(".", ",")
        except Exception:
            montant_str = str(montant)
    piece = q.get("piece") or ""

    # Header compact
    header = f"**Q{numero if numero is not None else '-'}** — {date} — {libelle}"
    if montant_str: header += f" — {montant_str}"
    if piece: header += f" — pièce: {piece}"
    st.markdown(header)

    # Texte de la question
    st.caption(q.get("question",""))

    # Réponse texte (brouillon conservé)
    default_text = answers.get(qkey, {}).get("texte", "")
    texte = st.text_area("Votre réponse (texte)", value=default_text, key=f"txt_{qkey}")
    # Mise à jour brouillon mémoire (immédiate)
    answers[qkey] = answers.get(qkey, {})
    answers[qkey]["texte"] = texte

    # Upload (multi-fichiers)
    ups = st.file_uploader(
        "Joindre une ou plusieurs pièces justificatives",
        type=["pdf","png","jpg","jpeg","webp","tif","tiff","doc","docx","xls","xlsx","csv","txt"],
        accept_multiple_files=True,
        key=f"up_{qkey}"
    )

    # Sauvegarde immédiate des fichiers uploadés (si nouveaux)
    saved_paths = answers[qkey].get("files", [])
    if ups:
        seq_start = len(saved_paths) + 1
        new_paths = []
        for i, up in enumerate(ups, start=seq_start):
            rel = save_uploaded_file(client_id, numero, up, i)
            new_paths.append(rel)
        saved_paths.extend(new_paths)
        answers[qkey]["files"] = saved_paths
        st.success(f"{len(new_paths)} fichier(s) enregistré(s).")

    # Afficher la liste des fichiers déjà enregistrés
    if saved_paths:
        st.write("Fichiers enregistrés :")
        for p in saved_paths:
            st.write(f"- `{p}`")

    st.divider()

# Autosave du brouillon à chaque interaction
save_draft(client_id, {"answers": answers})

st.subheader("3) Envoyer vos réponses")

# Quand l'utilisateur clique "Envoyer", on pousse un CSV "plat"
if st.button("📨 Envoyer / Finaliser"):
    timestamp = pd.Timestamp.utcnow().isoformat()

    # On reconstruit une table "à plat" par question
    rows = []
    for q in questions_sorted:
        numero = q.get("numero")
        qkey = f"q_{numero if numero is not None else id(q)}"
        info = answers.get(qkey, {})
        txt = info.get("texte", "")
        files = info.get("files", [])
        rows.append({
            "timestamp_utc": timestamp,
            "client": client_id,
            "numero": numero,
            "date": q.get("date",""),
            "libelle": q.get("libelle",""),
            "montant": q.get("montant",""),
            "piece": q.get("piece",""),
            "groupe": q.get("groupe",""),
            "sous_compte": q.get("sous_compte",""),
            "question": q.get("question",""),
            "reponse_texte": txt,
            "justificatifs": "; ".join(files) if files else ""
        })

    append_responses_csv(client_id, rows)

    # Purge (optionnel) du brouillon une fois envoyé
    save_draft(client_id, {"answers": {}})

    st.success("Merci, vos réponses ont été envoyées.")
    out = response_csv_path(client_id)
    if out.exists():
        with open(out, "rb") as fh:
            st.download_button("Télécharger le récapitulatif (CSV)", fh, file_name=out.name)
