"""Tests du tri, de la déduplication et des thèmes (données fictives, aucun réseau)."""

import unittest
from datetime import datetime, timedelta, timezone

from outils import Element
from tri import (
    compiler_themes,
    dedupliquer,
    detecter_themes,
    filtrer_par_date,
    grouper_par_theme,
    selectionner,
)

MAINTENANT = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)
THEMES = compiler_themes(
    {
        "SSR": ["ssr", "adapter"],
        "i18n": ["i18n", "locale"],
        "Vite": ["vite"],
    }
)


def faire_element(cle, type="rss", jours=1, **kwargs):
    return Element(
        cle=cle,
        type=type,
        titre=kwargs.pop("titre", f"Titre {cle}"),
        url=f"https://exemple.test/{cle}",
        source="Test",
        date=MAINTENANT - timedelta(days=jours),
        **kwargs,
    )


class TestThemes(unittest.TestCase):
    def test_detecte_plusieurs_themes_le_plus_present_en_premier(self):
        themes = detecter_themes("Adapter SSR et vite, avec un adapter Node", THEMES)
        self.assertEqual(themes[0], "SSR")
        self.assertIn("Vite", themes)

    def test_un_mot_cle_commence_un_mot(self):
        # "ssr" ne doit pas être trouvé dans "classroom"
        self.assertEqual(detecter_themes("classroom", THEMES), [])

    def test_aucun_theme(self):
        self.assertEqual(detecter_themes("rien à voir", THEMES), [])


class TestFiltresEtDedoublonnage(unittest.TestCase):
    def test_filtre_par_date(self):
        vieux = faire_element("a", jours=10)
        recent = faire_element("b", jours=1)
        depuis = MAINTENANT - timedelta(days=7)
        self.assertEqual(filtrer_par_date([vieux, recent], depuis), [recent])

    def test_dedoublonnage_dans_la_meme_execution(self):
        resultat = dedupliquer([faire_element("a"), faire_element("a"), faire_element("b")], {})
        self.assertEqual([e.cle for e in resultat], ["a", "b"])

    def test_ignore_les_identifiants_deja_envoyes(self):
        resultat = dedupliquer([faire_element("a"), faire_element("b")], {"a": "2026-11-02T08:00:00+00:00"})
        self.assertEqual([e.cle for e in resultat], ["b"])


class TestSelection(unittest.TestCase):
    def setUp(self):
        self.depuis = MAINTENANT - timedelta(days=7)

    def test_ordre_de_pertinence(self):
        release_astro = faire_element("rel", type="github", prioritaire=True)
        reponse_top = faire_element("rep", type="reddit_reponse", score=40)
        post_faible = faire_element("post", type="reddit_post", score=1)
        rss = faire_element("rss", type="rss")
        resultat = selectionner([rss, post_faible, reponse_top, release_astro], {}, self.depuis, THEMES)
        cles = [e.cle for e in resultat]
        self.assertEqual(cles[:2], ["rel", "rep"])  # release Astro et réponse très notée d'abord
        self.assertEqual(set(cles[2:]), {"post", "rss"})

    def test_limite_du_nombre_d_elements(self):
        elements = [faire_element(f"e{i}") for i in range(30)]
        resultat = selectionner(elements, {}, self.depuis, THEMES, max_elements=15)
        self.assertEqual(len(resultat), 15)

    def test_exclut_trop_ancien_et_deja_envoye(self):
        elements = [
            faire_element("ancien", jours=20),
            faire_element("deja"),
            faire_element("ok"),
        ]
        resultat = selectionner(elements, {"deja": "x"}, self.depuis, THEMES)
        self.assertEqual([e.cle for e in resultat], ["ok"])

    def test_groupes_autres_en_dernier(self):
        elements = [
            faire_element("sans_theme", type="github", titre="neutre", texte="rien"),
            faire_element("avec_theme", type="rss", titre="Support de Vite", texte="vite"),
        ]
        selection = selectionner(elements, {}, self.depuis, THEMES)
        groupes = grouper_par_theme(selection)
        self.assertEqual(groupes[-1][0], "Autres")
        self.assertEqual(groupes[0][0], "Vite")


if __name__ == "__main__":
    unittest.main()
