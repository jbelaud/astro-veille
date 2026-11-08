"""Message Telegram : mise en forme HTML, découpage et envoi."""

import html
import json
import time
import urllib.error
import urllib.request

from outils import tronquer

LIMITE_TELEGRAM = 4096
# On garde une petite marge sous la limite officielle.
LIMITE_UTILISEE = 4000


def echapper(texte):
    """Échappe <, > et & pour que Telegram n'interprète pas du faux HTML."""
    return html.escape(texte or "", quote=False)


def formater_element(e):
    """Un élément = titre, source, une ligne de contexte et le lien."""
    lignes = [f"• <b>{echapper(tronquer(e.titre, 140))}</b> ({echapper(e.source)})"]
    if e.resume:
        lignes.append(echapper(tronquer(e.resume, 180)))
    if len(e.themes) > 1:
        lignes.append("<i>aussi : " + echapper(", ".join(e.themes[1:3])) + "</i>")
    lignes.append(f'<a href="{html.escape(e.url, quote=True)}">Voir le lien</a>')
    return "\n".join(lignes)


def construire_messages(sections, debut, fin, avertissements=None, limite=LIMITE_UTILISEE):
    """Construit la liste des messages à envoyer.

    - `sections` : [(nom_du_thème, [éléments])]
    - un élément n'est jamais coupé en deux : si le message est plein, on passe au suivant
    - le titre de section est répété en tête du message suivant si besoin
    """
    titre = f"<b>Veille Astro</b> — du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"

    blocs = []  # (thème ou None, texte)
    for nom, elements in sections:
        for e in elements:
            blocs.append((nom, formater_element(e)))
    if not blocs:
        blocs.append((None, "Aucune nouveauté cette semaine."))
    if avertissements:
        blocs.append((None, "⚠️ Sources en échec : " + echapper(", ".join(avertissements))))

    messages = []
    courant = titre
    theme_courant = None
    contient_un_bloc = False  # un message ne reste jamais "titre seul"
    for theme, bloc in blocs:
        ajout = _ajout(theme, theme_courant, bloc)
        if len(courant) + len(ajout) > limite and contient_un_bloc:
            # Message plein : on le range et on repart sur un nouveau message.
            messages.append(courant)
            courant = "<b>Veille Astro</b> — suite"
            theme_courant = None
            ajout = _ajout(theme, theme_courant, bloc)
        courant += ajout
        theme_courant = theme
        contient_un_bloc = True
    messages.append(courant)
    return messages


def _ajout(theme, theme_courant, bloc):
    """Texte à ajouter au message : avec le titre de section si on change de thème."""
    if theme and theme != theme_courant:
        return f"\n\n<b>{echapper(theme)}</b>\n{bloc}"
    return f"\n\n{bloc}"


# --------------------------------------------------------------------------- #
# Envoi
# --------------------------------------------------------------------------- #
def _appeler_api(token, donnees):
    """Appelle sendMessage. Les erreurs ne contiennent jamais l'URL (donc jamais le jeton)."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requete = urllib.request.Request(
        url,
        data=json.dumps(donnees).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "astro-veille/1.0"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            reponse.read()
    except urllib.error.HTTPError as err:
        try:
            description = json.load(err).get("description", "")
        except Exception:
            description = ""
        raise RuntimeError(f"Telegram a refusé le message (HTTP {err.code}) : {description}") from None
    except urllib.error.URLError:
        raise RuntimeError("Telegram est injoignable (erreur réseau)") from None


def envoyer_messages(token, chat_id, messages):
    """Envoie les messages en HTML, avec une courte pause entre chaque."""
    for i, texte in enumerate(messages):
        if i > 0:
            time.sleep(1)
        _appeler_api(
            token,
            {
                "chat_id": chat_id,
                "text": texte,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )


def envoyer_alerte(token, chat_id, texte):
    """Petit message d'alerte en texte simple. Ne plante jamais (on est déjà en erreur)."""
    try:
        _appeler_api(token, {"chat_id": chat_id, "text": texte[:500]})
        return True
    except Exception:
        return False
