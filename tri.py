"""Tri et sélection : filtre par date, déduplication, thèmes, score de pertinence."""

import re

from outils import Element  # noqa: F401  (rappel : c'est le type manipulé ici)


# --------------------------------------------------------------------------- #
# Thèmes
# --------------------------------------------------------------------------- #
def compiler_themes(themes_config):
    """Transforme {"Nom du thème": ["mot-clé", ...]} en expressions régulières.

    Un mot-clé doit commencer un mot : "ssr" ne correspond pas à "classroom",
    mais "hydrat" correspond à "hydration".
    """
    resultat = {}
    for nom, mots in themes_config.items():
        motifs = ["(?<!\\w)" + re.escape(mot) for mot in mots]
        resultat[nom] = re.compile("|".join(motifs), re.IGNORECASE)
    return resultat


def detecter_themes(texte, themes_compiles):
    """Renvoie les thèmes trouvés dans le texte, le plus présent en premier."""
    texte = (texte or "")[:4000]
    trouves = []
    for ordre, (nom, motif) in enumerate(themes_compiles.items()):
        mots_distincts = {m.lower() for m in motif.findall(texte)}
        if mots_distincts:
            trouves.append((-len(mots_distincts), ordre, nom))
    trouves.sort()
    return [nom for _, _, nom in trouves]


# --------------------------------------------------------------------------- #
# Filtres
# --------------------------------------------------------------------------- #
def filtrer_par_date(elements, depuis):
    """Ne garde que les éléments publiés depuis la date donnée."""
    return [e for e in elements if e.date >= depuis]


def dedupliquer(elements, ids_deja_envoyes):
    """Enlève les doublons et les éléments déjà envoyés lors d'une précédente exécution."""
    vus = set()
    resultat = []
    for e in elements:
        if e.cle in ids_deja_envoyes or e.cle in vus:
            continue
        vus.add(e.cle)
        resultat.append(e)
    return resultat


# --------------------------------------------------------------------------- #
# Pertinence
# --------------------------------------------------------------------------- #
def calculer_points(e):
    """Note de pertinence : plus c'est haut, plus l'élément passe devant.

    Ordre voulu : releases Astro et réponses très notées d'abord, puis le reste.
    """
    if e.type == "github":
        points = 60
        if e.prioritaire:
            points += 40  # release d'Astro lui-même
    elif e.type == "reddit_reponse":
        points = 30 + min(e.score, 100)
    elif e.type == "reddit_post":
        points = 15 + min(e.score, 30) + min(e.nb_commentaires, 20)
    else:  # rss
        points = 20
    return points + 5 * len(e.themes)


def trier(elements):
    """Du plus pertinent au moins pertinent (à égalité : le plus récent d'abord)."""
    return sorted(elements, key=lambda e: (-e.points, -e.date.timestamp()))


def selectionner(elements, ids_deja_envoyes, depuis, themes_compiles, max_elements=15):
    """Applique toutes les étapes et renvoie les `max_elements` meilleurs éléments."""
    elements = filtrer_par_date(elements, depuis)
    elements = dedupliquer(elements, ids_deja_envoyes)
    for e in elements:
        e.themes = detecter_themes(f"{e.titre}\n{e.texte}", themes_compiles)
        e.points = calculer_points(e)
    return trier(elements)[:max_elements]


def grouper_par_theme(elements):
    """Range les éléments par thème principal.

    Renvoie une liste [(nom_du_thème, [éléments])] : les thèmes ayant le meilleur
    élément viennent en premier, "Autres" est toujours en dernier.
    """
    groupes = {}
    for e in elements:  # `elements` est déjà trié par pertinence
        theme = e.themes[0] if e.themes else "Autres"
        groupes.setdefault(theme, []).append(e)

    def cle(item):
        nom, liste = item
        return (nom == "Autres", -liste[0].points)

    return sorted(groupes.items(), key=cle)
