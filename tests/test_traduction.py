"""Tests : traduction (sans réseau), releases sans notes, flux désactivés."""

import io
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

import sources
import traduction
from outils import Element

DEPUIS = datetime(2026, 11, 1, tzinfo=timezone.utc)
CFG_ACTIVE = {"enabled": True, "langue_source": "en", "langue_cible": "fr"}


def element(type_="rss", titre="Hello", resume="World"):
    return Element(cle="x", type=type_, titre=titre, url="https://e.test", source="S",
                   date=DEPUIS, resume=resume)


class TestTraductionElements(unittest.TestCase):
    def test_desactivee_ne_fait_rien(self):
        el = element()
        faux = mock.Mock()
        traduction.traduire_elements([el], {"enabled": False}, traducteur=faux, pause=0)
        faux.assert_not_called()
        self.assertEqual(el.titre, "Hello")

    def test_traduit_titre_et_resume_des_flux(self):
        el = element()
        traduction.traduire_elements([el], CFG_ACTIVE, traducteur=lambda t, s, c: f"FR:{t}", pause=0)
        self.assertEqual((el.titre, el.resume), ("FR:Hello", "FR:World"))

    def test_github_garde_son_titre(self):
        el = element("github", titre="astro@7.4.7")
        traduction.traduire_elements([el], CFG_ACTIVE, traducteur=lambda t, s, c: f"FR:{t}", pause=0)
        self.assertEqual((el.titre, el.resume), ("astro@7.4.7", "FR:World"))

    def test_echec_conserve_le_texte_anglais(self):
        el = element()
        traduction.traduire_elements([el], CFG_ACTIVE, traducteur=lambda t, s, c: None, pause=0)
        self.assertEqual((el.titre, el.resume), ("Hello", "World"))

    def test_arret_apres_trois_echecs_de_suite(self):
        els = [element(titre=f"t{i}", resume=f"r{i}") for i in range(5)]
        faux = mock.Mock(return_value=None)
        traduction.traduire_elements(els, CFG_ACTIVE, traducteur=faux, pause=0)
        self.assertEqual(faux.call_count, traduction.ECHECS_AVANT_ARRET)


class TestTraduireTexte(unittest.TestCase):
    def reponse(self, donnees):
        r = io.BytesIO(json.dumps(donnees).encode())
        r.__enter__ = lambda s: s
        r.__exit__ = lambda s, *a: None
        return r

    def test_reponse_normale(self):
        donnees = {"responseStatus": 200, "responseData": {"translatedText": "Bonjour &amp; salut"}}
        with mock.patch("urllib.request.urlopen", return_value=self.reponse(donnees)):
            self.assertEqual(traduction.traduire_texte("Hello"), "Bonjour & salut")

    def test_avertissement_de_quota_renvoie_none(self):
        donnees = {"responseStatus": 200,
                   "responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"}}
        with mock.patch("urllib.request.urlopen", return_value=self.reponse(donnees)):
            self.assertIsNone(traduction.traduire_texte("Hello"))

    def test_erreur_reseau_renvoie_none(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
            self.assertIsNone(traduction.traduire_texte("Hello"))


class TestReleasesSansNotes(unittest.TestCase):
    def releases(self):
        base = {"published_at": "2026-11-05T10:00:00Z", "draft": False, "prerelease": False,
                "html_url": "https://g.test"}
        return json.dumps([
            dict(base, id=1, tag_name="astro@7.0.0", name="astro@7.0.0", body=""),
            dict(base, id=2, tag_name="@astrojs/react@4.0.0", name="react", body=""),
            dict(base, id=3, tag_name="@astrojs/mdx@4.0.0", name="mdx",
                 body="### Minor Changes\n\n- Ajoute une vraie fonctionnalité utile"),
        ])

    def collecter(self, cfg_extra=None):
        cfg = {"type": "github", "id": "withastro/astro", "nom": "Astro",
               "prefixes_prioritaires": ["astro@"]}
        cfg.update(cfg_extra or {})
        with mock.patch.object(sources, "telecharger", return_value=self.releases()):
            return sources.collecter_github(cfg, DEPUIS)

    def test_sans_notes_ignorees_sauf_prioritaires(self):
        titres = sorted(e.titre for e in self.collecter())
        self.assertEqual(titres, ["astro@7.0.0", "mdx"])

    def test_option_desactivee_garde_tout(self):
        self.assertEqual(len(self.collecter({"ignorer_sans_notes": False})), 3)


class TestSourceDesactivee(unittest.TestCase):
    def test_actif_false_aucun_appel(self):
        config = {"sources": [{"type": "rss", "id": "https://e.test/f", "nom": "X", "actif": False}]}
        with mock.patch.object(sources, "collecter_rss") as rss:
            _, echecs, essayees = sources.collecter_tout(config, DEPUIS, "inutile.sqlite")
        rss.assert_not_called()
        self.assertEqual((echecs, essayees), ([], 0))


if __name__ == "__main__":
    unittest.main()
