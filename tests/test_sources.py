"""Tests : Reddit est facultatif et désactivé par défaut (aucun appel réseau)."""

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

import sources

DEPUIS = datetime(2026, 11, 1, tzinfo=timezone.utc)
SOURCE_REDDIT = {"type": "reddit", "id": "astrojs", "nom": "r/astrojs"}
SOURCE_RSS = {"type": "rss", "id": "https://exemple.test/feed.xml", "nom": "Blog test"}


def sans_identifiants_reddit():
    env = {k: v for k, v in os.environ.items() if not k.startswith("REDDIT_")}
    return mock.patch.dict(os.environ, env, clear=True)


class TestRedditFacultatif(unittest.TestCase):
    def test_desactive_par_defaut_aucun_appel(self):
        config = {"sources": [SOURCE_REDDIT, SOURCE_RSS]}  # pas de section "reddit"
        with mock.patch.object(sources, "collecter_reddit") as reddit, \
             mock.patch.object(sources, "RedditClient") as client, \
             mock.patch.object(sources, "collecter_rss", return_value=[]) as rss:
            elements, echecs, essayees = sources.collecter_tout(config, DEPUIS, "inutile.sqlite")
        reddit.assert_not_called()
        client.assert_not_called()
        rss.assert_called_once()
        self.assertEqual((elements, echecs, essayees), ([], [], 1))  # Reddit ignoré, pas un échec

    def test_enabled_false_explicite(self):
        config = {"reddit": {"enabled": False}, "sources": [SOURCE_REDDIT]}
        with mock.patch.object(sources, "collecter_reddit") as reddit:
            _, echecs, essayees = sources.collecter_tout(config, DEPUIS, "inutile.sqlite")
        reddit.assert_not_called()
        self.assertEqual((echecs, essayees), ([], 0))

    def test_active_sans_identifiants_avertissement_et_aucun_appel(self):
        config = {"reddit": {"enabled": True}, "sources": [SOURCE_REDDIT]}
        with sans_identifiants_reddit(), \
             mock.patch.object(sources, "collecter_reddit") as reddit, \
             mock.patch.object(sources, "RedditClient") as client, \
             mock.patch.object(sources, "log") as journal:
            _, echecs, essayees = sources.collecter_tout(config, DEPUIS, "inutile.sqlite")
        reddit.assert_not_called()
        client.assert_not_called()
        self.assertEqual((echecs, essayees), ([], 0))
        messages = " ".join(str(c.args[0]) for c in journal.call_args_list)
        self.assertIn("AVERTISSEMENT", messages)

    def test_active_avec_identifiants_appelle_reddit(self):
        config = {"reddit": {"enabled": True}, "sources": [SOURCE_REDDIT]}
        with mock.patch.dict(os.environ, {"REDDIT_CLIENT_ID": "abcd1234", "REDDIT_CLIENT_SECRET": "efgh5678"}), \
             mock.patch.object(sources, "collecter_reddit", return_value=[]) as reddit:
            _, echecs, essayees = sources.collecter_tout(config, DEPUIS, "inutile.sqlite")
        reddit.assert_called_once()
        self.assertEqual((echecs, essayees), ([], 1))

    def test_le_client_reddit_refuse_de_demarrer_sans_identifiants(self):
        # Plus de repli vers les endpoints publics : sans identifiants, aucune requête n'est faite.
        with mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError):
                sources.RedditClient(None, None)
        urlopen.assert_not_called()

    def test_github_et_rss_fonctionnent_sans_reddit(self):
        config = {
            "sources": [
                SOURCE_REDDIT,
                {"type": "github", "id": "withastro/astro", "nom": "Astro"},
                SOURCE_RSS,
            ]
        }
        with mock.patch.object(sources, "collecter_reddit") as reddit, \
             mock.patch.object(sources, "collecter_github", return_value=[]) as gh, \
             mock.patch.object(sources, "collecter_rss", return_value=[]) as rss:
            _, echecs, essayees = sources.collecter_tout(config, DEPUIS, "inutile.sqlite")
        reddit.assert_not_called()
        gh.assert_called_once()
        rss.assert_called_once()
        self.assertEqual((echecs, essayees), ([], 2))


class TestConfigParDefaut(unittest.TestCase):
    def test_config_yaml_livree_a_reddit_desactive(self):
        from outils import charger_config

        dossier = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config = charger_config(os.path.join(dossier, "config.yaml"))
        self.assertIs(config["reddit"]["enabled"], False)

    def test_gitignore_exclut_la_base_sqlite(self):
        dossier = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(dossier, ".gitignore"), encoding="utf-8") as f:
            lignes = {l.strip() for l in f}
        self.assertIn("*.sqlite", lignes)


if __name__ == "__main__":
    unittest.main()
