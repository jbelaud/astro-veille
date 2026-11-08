"""Traduction automatique (anglais -> français) des titres et résumés du message.

Service utilisé : l'API publique et gratuite de MyMemory (aucune clé, aucun secret,
aucune adresse e-mail envoyée). Ses limites : la qualité est correcte sans plus, et le
quota gratuit quotidien est limité (partagé entre les utilisateurs d'une même adresse IP).

La traduction est "au mieux" : si elle échoue (quota, réseau...), le texte d'origine en
anglais est conservé et le message part quand même.
"""

import html
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from outils import USER_AGENT, log, tronquer

URL_API = "https://api.mymemory.translated.net/get"
MAX_CARACTERES = 400  # l'API refuse les textes trop longs (500 octets)
ECHECS_AVANT_ARRET = 3  # après 3 échecs d'affilée (quota atteint ?), on arrête de traduire


def traduire_texte(texte, source="en", cible="fr"):
    """Renvoie le texte traduit, ou None si la traduction a échoué."""
    texte = tronquer(texte, MAX_CARACTERES)
    if not texte:
        return texte
    parametres = urllib.parse.urlencode({"q": texte, "langpair": f"{source}|{cible}"})
    requete = urllib.request.Request(f"{URL_API}?{parametres}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(requete, timeout=15) as reponse:
            donnees = json.load(reponse)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    try:
        if int(donnees.get("responseStatus", 0)) != 200:
            return None
        traduit = donnees["responseData"]["translatedText"]
    except (KeyError, TypeError, ValueError):
        return None
    # Quand le quota est atteint, le service répond "MYMEMORY WARNING..." à la place du texte.
    if not traduit or "MYMEMORY WARNING" in traduit.upper():
        return None
    return html.unescape(traduit).strip()


def champs_a_traduire(element):
    """Les identifiants (ex. astro@7.4.7) et les titres de réponses Reddit ne sont pas traduits."""
    if element.type in ("github", "reddit_reponse"):
        return ["resume"]
    return ["titre", "resume"]


def traduire_elements(elements, cfg, traducteur=traduire_texte, pause=0.5):
    """Traduit en place les titres et résumés (si `traduction.enabled` vaut true)."""
    if not cfg.get("enabled", False):
        return
    source = cfg.get("langue_source", "en")
    cible = cfg.get("langue_cible", "fr")
    echecs_de_suite = 0
    traduits = 0
    for element in elements:
        for champ in champs_a_traduire(element):
            texte = getattr(element, champ)
            if not texte or texte == "Voir les notes de version.":
                continue
            if echecs_de_suite >= ECHECS_AVANT_ARRET:
                log("[traduction] trop d'échecs d'affilée : textes laissés en anglais")
                return
            resultat = traducteur(texte, source, cible)
            time.sleep(pause)
            if resultat is None:
                echecs_de_suite += 1
                continue
            echecs_de_suite = 0
            setattr(element, champ, resultat)
            traduits += 1
    log(f"[traduction] {traduits} texte(s) traduit(s)")
