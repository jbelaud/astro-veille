"""Fonctions utilitaires : configuration, état, heure de Paris, secrets, journal.

Tout ce fichier utilise surtout la bibliothèque standard de Python.
Seul PyYAML (lecture de config.yaml) est une dépendance externe.
"""

import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import yaml

# User-Agent générique : pas d'adresse e-mail dedans.
USER_AGENT = "astro-veille/1.0"

FUSEAU_PARIS = ZoneInfo("Europe/Paris")

# Variables d'environnement qui contiennent des secrets (jamais affichées).
NOMS_SECRETS = (
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GITHUB_TOKEN",
)


@dataclass
class Element:
    """Une nouveauté trouvée (post Reddit, release GitHub, article RSS...)."""

    cle: str  # identifiant unique, ex. "reddit:abc123" ou "github:4356"
    type: str  # "reddit_post", "reddit_reponse", "github" ou "rss"
    titre: str
    url: str
    source: str  # nom affiché de la source
    date: datetime  # date de publication (avec fuseau, en UTC)
    resume: str = ""  # une ligne de contexte pour le message
    texte: str = ""  # texte plus long, utilisé pour détecter les thèmes
    score: int = 0  # note Reddit
    nb_commentaires: int = 0
    prioritaire: bool = False  # ex. release d'Astro lui-même
    themes: list = field(default_factory=list)
    points: float = 0.0  # note de pertinence, calculée dans tri.py


# --------------------------------------------------------------------------- #
# Journal et secrets
# --------------------------------------------------------------------------- #
def masquer_secrets(texte):
    """Remplace tout secret connu par *** (même s'il est dans un message d'erreur)."""
    texte = str(texte)
    for nom in NOMS_SECRETS:
        valeur = os.environ.get(nom, "")
        if len(valeur) >= 4:
            texte = texte.replace(valeur, "***")
    # Filet de sécurité : une URL Telegram contient le jeton après "bot".
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", texte)


def log(message):
    """Affiche un message de journal (sur stderr), toujours sans secret."""
    print(masquer_secrets(message), file=sys.stderr)


# --------------------------------------------------------------------------- #
# Nettoyage de texte
# --------------------------------------------------------------------------- #
def tronquer(texte, n):
    """Raccourcit un texte à n caractères environ, sans couper un mot."""
    texte = re.sub(r"\s+", " ", texte or "").strip()
    if len(texte) <= n:
        return texte
    return texte[:n].rsplit(" ", 1)[0] + "…"


def nettoyer_texte(texte):
    """Enlève le HTML et le Markdown le plus courant pour garder du texte brut."""
    texte = re.sub(r"<[^>]+>", " ", texte or "")
    texte = html.unescape(texte)
    texte = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", texte)  # [texte](lien) -> texte
    texte = texte.replace("`", "").replace("*", "")
    return re.sub(r"\s+", " ", texte).strip()


def resume_changelog(corps, n=160):
    """Extrait la première vraie ligne utile d'une note de version GitHub."""
    for ligne in (corps or "").splitlines():
        brute = ligne
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if brute.startswith((" ", "\t")):
            continue  # sous-liste (souvent la liste des dépendances mises à jour)
        if ligne.lstrip("-* ").startswith("Updated dependencies"):
            continue
        t = ligne.lstrip("-* ").strip()
        t = re.sub(r"\[`?[0-9a-f]{7,40}`?\]\([^)]*\)\s*", "", t)  # lien de commit
        t = re.sub(r"Thanks \[@[^\]]+\]\([^)]*\)!\s*-?\s*", "", t)  # remerciements
        t = nettoyer_texte(t)
        if t:
            return tronquer(t, n)
    return ""


# --------------------------------------------------------------------------- #
# Configuration et état
# --------------------------------------------------------------------------- #
def charger_config(chemin):
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def etat_vide():
    return {"derniere_execution_reussie": None, "ids_envoyes": {}}


def charger_etat(chemin):
    """Lit state.json. S'il n'existe pas, on repart d'un état vide."""
    if not os.path.exists(chemin):
        return etat_vide()
    with open(chemin, encoding="utf-8") as f:
        etat = json.load(f)
    base = etat_vide()
    base.update(etat)
    return base


def sauver_etat(chemin, etat):
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def lire_iso(texte):
    """Convertit un texte ISO 8601 en datetime avec fuseau (UTC par défaut)."""
    d = datetime.fromisoformat(texte.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def calculer_depuis(etat, maintenant, jours_premier_lancement=7, marge_minutes=60):
    """Date à partir de laquelle on garde les éléments.

    - Après une exécution réussie : la date de cette exécution, moins une petite marge
      (les doublons éventuels sont éliminés par les identifiants déjà envoyés).
    - Au tout premier lancement : une fenêtre de sécurité de 7 jours.
    """
    derniere = etat.get("derniere_execution_reussie")
    if derniere:
        return lire_iso(derniere) - timedelta(minutes=marge_minutes)
    return maintenant - timedelta(days=jours_premier_lancement)


def purger_ids(ids, maintenant, jours=180):
    """Oublie les identifiants envoyés il y a plus de `jours` jours (garde le fichier petit)."""
    limite = maintenant - timedelta(days=jours)
    return {cle: date for cle, date in ids.items() if lire_iso(date) >= limite}


# --------------------------------------------------------------------------- #
# Heure de Paris
# --------------------------------------------------------------------------- #
def est_9h_a_paris(maintenant=None):
    """Vrai s'il est entre 9h00 et 9h59 à Paris (heure d'été ou d'hiver)."""
    if maintenant is None:
        maintenant = datetime.now(timezone.utc)
    return maintenant.astimezone(FUSEAU_PARIS).hour == 9
