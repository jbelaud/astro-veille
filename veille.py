#!/usr/bin/env python3
"""Veille Astro : collecte, trie et envoie un résumé hebdomadaire sur Telegram.

Usage :
  python veille.py --dry-run          # affiche le message au lieu de l'envoyer
  python veille.py --demo --dry-run   # idem, avec des données fictives (aucun réseau)
  python veille.py                    # envoi réel (variables d'environnement requises)
  python veille.py --verifier-heure   # utilisé par GitHub Actions (voir le workflow)

Variables d'environnement (jamais écrites dans le code) :
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
  et GITHUB_TOKEN (optionnelle).
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from demo import elements_fictifs
from outils import (
    FUSEAU_PARIS,
    calculer_depuis,
    charger_config,
    charger_etat,
    est_9h_a_paris,
    log,
    masquer_secrets,
    purger_ids,
    sauver_etat,
)
from sources import collecter_tout
from telegram import construire_messages, envoyer_alerte, envoyer_messages
from tri import compiler_themes, grouper_par_theme, selectionner

DOSSIER = os.path.dirname(os.path.abspath(__file__))


def lire_arguments(argv=None):
    p = argparse.ArgumentParser(description="Veille Astro vers Telegram")
    p.add_argument("--dry-run", action="store_true",
                   help="affiche le message au lieu de l'envoyer (et ne modifie pas state.json)")
    p.add_argument("--demo", action="store_true",
                   help="utilise des données fictives, sans appel réseau pour la collecte")
    p.add_argument("--verifier-heure", action="store_true",
                   help="indique s'il est 9h à Paris (pour GitHub Actions) puis s'arrête")
    p.add_argument("--config", default=os.path.join(DOSSIER, "config.yaml"))
    p.add_argument("--etat", default=os.path.join(DOSSIER, "state.json"))
    p.add_argument("--db", default=os.path.join(DOSSIER, "veille.sqlite"))
    return p.parse_args(argv)


def verifier_heure():
    """Écrit lancer=true/false pour GitHub Actions : vrai seulement s'il est 9h à Paris."""
    ok = est_9h_a_paris()
    heure = datetime.now(timezone.utc).astimezone(FUSEAU_PARIS).strftime("%H:%M")
    log(f"Heure à Paris : {heure} -> {'on lance' if ok else 'pas 9h, on arrête'}")
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"lancer={'true' if ok else 'false'}\n")
    return 0


def lancer(args):
    config = charger_config(args.config)
    reglages = config.get("reglages", {})
    etat = charger_etat(args.etat)
    maintenant = datetime.now(timezone.utc)
    depuis = calculer_depuis(
        etat,
        maintenant,
        reglages.get("fenetre_premier_lancement_jours", 7),
        reglages.get("marge_minutes", 60),
    )
    log(f"Période : depuis {depuis.astimezone(FUSEAU_PARIS):%d/%m/%Y %H:%M} (Paris)")

    # 1. Collecte
    if args.demo:
        elements, echecs, essayees = elements_fictifs(maintenant), [], 1
        depuis = min(depuis, min(e.date for e in elements))  # pour garder les données fictives
    else:
        elements, echecs, essayees = collecter_tout(config, depuis, args.db)
        if essayees and len(echecs) == essayees:
            raise RuntimeError("Toutes les sources ont échoué")

    # 2. Tri et sélection
    themes = compiler_themes(config.get("themes", {}))
    selection = selectionner(
        elements,
        etat["ids_envoyes"],
        depuis,
        themes,
        reglages.get("max_elements", 15),
    )
    log(f"{len(elements)} élément(s) collecté(s), {len(selection)} retenu(s)")

    # 3. Message(s)
    messages = construire_messages(
        grouper_par_theme(selection),
        depuis.astimezone(FUSEAU_PARIS),
        maintenant.astimezone(FUSEAU_PARIS),
        echecs,
    )

    if args.dry_run:
        for i, texte in enumerate(messages, 1):
            print(f"----- Message {i}/{len(messages)} ({len(texte)} caractères) -----")
            print(texte)
        print("----- Dry-run : rien envoyé, state.json inchangé -----")
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID doivent être définis")
    envoyer_messages(token, chat_id, messages)
    log(f"{len(messages)} message(s) envoyé(s) sur Telegram")

    # 4. État : seulement après un envoi réussi (et pas avec les données fictives)
    if args.demo:
        log("Mode démo : state.json non modifié")
    else:
        for e in selection:
            etat["ids_envoyes"][e.cle] = maintenant.isoformat()
        etat["ids_envoyes"] = purger_ids(etat["ids_envoyes"], maintenant)
        etat["derniere_execution_reussie"] = maintenant.isoformat()
        sauver_etat(args.etat, etat)
        log("state.json mis à jour")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # pour les accents sous Windows
    args = lire_arguments(argv)
    if args.verifier_heure:
        return verifier_heure()
    try:
        return lancer(args)
    except Exception as exc:
        message = masquer_secrets(f"{type(exc).__name__}: {exc}")
        log(f"ERREUR GRAVE : {message}")
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat_id and not args.dry_run:
            envoyer_alerte(token, chat_id, f"⚠️ Veille Astro : échec du programme.\n{message[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
