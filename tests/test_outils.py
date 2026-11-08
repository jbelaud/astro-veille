"""Tests de l'heure de Paris, de l'état, des secrets et de la lecture des flux."""

import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from outils import (
    calculer_depuis,
    charger_etat,
    est_9h_a_paris,
    masquer_secrets,
    purger_ids,
    resume_changelog,
    sauver_etat,
)
from sources import garder_dernier_par_paquet, lire_flux


def utc(annee, mois, jour, heure, minute=0):
    return datetime(annee, mois, jour, heure, minute, tzinfo=timezone.utc)


class TestHeureParis(unittest.TestCase):
    def test_hiver_9h_paris_est_8h_utc(self):
        self.assertTrue(est_9h_a_paris(utc(2026, 1, 12, 8)))
        self.assertFalse(est_9h_a_paris(utc(2026, 1, 12, 7)))

    def test_ete_9h_paris_est_7h_utc(self):
        self.assertTrue(est_9h_a_paris(utc(2026, 7, 13, 7)))
        self.assertFalse(est_9h_a_paris(utc(2026, 7, 13, 8)))

    def test_changement_d_heure(self):
        # Lundi 30 mars 2026 : heure d'été depuis dimanche -> 9h Paris = 7h UTC
        self.assertTrue(est_9h_a_paris(utc(2026, 3, 30, 7)))
        # Lundi 26 octobre 2026 : heure d'hiver depuis dimanche -> 9h Paris = 8h UTC
        self.assertTrue(est_9h_a_paris(utc(2026, 10, 26, 8)))

    def test_chaque_lundi_un_seul_des_deux_declencheurs_passe(self):
        # Les déclencheurs du workflow sont 7h et 8h UTC : un seul doit être accepté.
        for jour in (utc(2026, 1, 12, 0), utc(2026, 7, 13, 0), utc(2026, 3, 30, 0), utc(2026, 10, 26, 0)):
            acceptes = [h for h in (7, 8) if est_9h_a_paris(jour.replace(hour=h))]
            self.assertEqual(len(acceptes), 1, jour)


class TestEtat(unittest.TestCase):
    def test_premier_lancement_fenetre_de_7_jours(self):
        maintenant = utc(2026, 11, 9, 8)
        self.assertEqual(calculer_depuis({}, maintenant), maintenant - timedelta(days=7))

    def test_apres_une_execution_reussie(self):
        etat = {"derniere_execution_reussie": "2026-11-02T08:00:00+00:00"}
        depuis = calculer_depuis(etat, utc(2026, 11, 9, 8), marge_minutes=60)
        self.assertEqual(depuis, utc(2026, 11, 2, 7))

    def test_sauvegarde_et_relecture(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "state.json")
            self.assertEqual(charger_etat(chemin)["ids_envoyes"], {})  # fichier absent
            sauver_etat(chemin, {"derniere_execution_reussie": "x", "ids_envoyes": {"a": "b"}})
            self.assertEqual(charger_etat(chemin)["ids_envoyes"], {"a": "b"})

    def test_purge_des_vieux_identifiants(self):
        maintenant = utc(2026, 11, 9, 8)
        ids = {"vieux": utc(2025, 1, 1, 0).isoformat(), "recent": utc(2026, 11, 2, 0).isoformat()}
        self.assertEqual(list(purger_ids(ids, maintenant)), ["recent"])


class TestSecrets(unittest.TestCase):
    def test_masque_les_secrets_et_les_urls_telegram(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123456:ABCdef-secret"}):
            texte = masquer_secrets("erreur sur https://api.telegram.org/bot123456:ABCdef-secret/sendMessage")
        self.assertNotIn("ABCdef", texte)
        self.assertNotIn("123456", texte)


class TestTextes(unittest.TestCase):
    def test_resume_changelog(self):
        corps = (
            "### Patch Changes\n\n"
            "- [`7da442b`](https://github.com/withastro/astro/commit/7da442b) Thanks [@dev](https://github.com/dev)! - "
            "Fixes the image endpoint on case-sensitive filesystems\n"
            "- Updated dependencies [[`7da442b`](https://x)]:\n  - @astrojs/internal-helpers@0.13.1\n"
        )
        self.assertEqual(
            resume_changelog(corps), "Fixes the image endpoint on case-sensitive filesystems"
        )

    def test_garde_la_derniere_release_de_chaque_paquet(self):
        releases = [
            {"tag_name": "astro@7.4.6", "published_at": "2026-11-05T16:00:00Z"},
            {"tag_name": "astro@7.4.7", "published_at": "2026-11-05T19:00:00Z"},
            {"tag_name": "@astrojs/react@7.1.4", "published_at": "2026-11-05T19:00:00Z"},
        ]
        tags = {r["tag_name"] for r in garder_dernier_par_paquet(releases)}
        self.assertEqual(tags, {"astro@7.4.7", "@astrojs/react@7.1.4"})


class TestFlux(unittest.TestCase):
    def test_lecture_rss(self):
        xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>Article A</title><link>https://x.test/a</link>
        <guid isPermaLink="false">guid-a</guid>
        <pubDate>Tue, 31 Mar 2026 00:00:00 +0000</pubDate>
        <description><![CDATA[<p>Bonjour</p>]]></description></item>
        </channel></rss>"""
        articles = lire_flux(xml)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["id"], "guid-a")
        self.assertEqual(articles[0]["date"], utc(2026, 3, 31, 0))

    def test_lecture_atom(self):
        xml = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>Entree B</title><id>tag:b</id>
        <link rel="alternate" href="https://x.test/b"/>
        <updated>2026-05-15T10:00:00Z</updated><summary>Resume</summary></entry></feed>"""
        articles = lire_flux(xml)
        self.assertEqual(articles[0]["lien"], "https://x.test/b")
        self.assertEqual(articles[0]["date"], utc(2026, 5, 15, 10))


class TestDryRunDemo(unittest.TestCase):
    def test_demo_dry_run_complet_sans_reseau(self):
        import veille

        with tempfile.TemporaryDirectory() as dossier:
            etat = os.path.join(dossier, "state.json")
            sortie = io.StringIO()
            with contextlib.redirect_stdout(sortie):
                code = veille.main(["--demo", "--dry-run", "--etat", etat])
            self.assertEqual(code, 0)
            texte = sortie.getvalue()
            self.assertIn("Veille Astro", texte)
            self.assertIn("astro@9.9.0", texte)
            self.assertIn("&lt;sans&gt;", texte)  # échappement HTML
            self.assertFalse(os.path.exists(etat))  # le dry-run n'écrit rien


if __name__ == "__main__":
    unittest.main()
