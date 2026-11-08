"""Tests de la mise en forme et du découpage des messages (aucun envoi réel)."""

import unittest
from datetime import datetime, timedelta, timezone

from outils import Element
from telegram import LIMITE_TELEGRAM, construire_messages, formater_element

FIN = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
DEBUT = FIN - timedelta(days=7)


def faire_element(i, titre=None):
    return Element(
        cle=f"e{i}",
        type="rss",
        titre=titre or f"Article numéro {i}",
        url=f"https://exemple.test/article-{i}",
        source="Source test",
        date=FIN,
        resume="Un résumé assez long pour prendre de la place dans le message. " * 3,
    )


class TestDecoupage(unittest.TestCase):
    def test_un_seul_message_si_court(self):
        sections = [("Vite", [faire_element(1), faire_element(2)])]
        messages = construire_messages(sections, DEBUT, FIN)
        self.assertEqual(len(messages), 1)
        self.assertIn("Veille Astro", messages[0])
        self.assertIn("02/11/2026", messages[0])
        self.assertIn("<b>Vite</b>", messages[0])

    def test_decoupe_sans_depasser_la_limite_ni_couper_un_element(self):
        elements = [faire_element(i) for i in range(30)]
        sections = [("Thème A", elements[:15]), ("Thème B", elements[15:])]
        messages = construire_messages(sections, DEBUT, FIN, limite=900)
        self.assertGreater(len(messages), 1)
        for texte in messages:
            self.assertLessEqual(len(texte), 900)
        # chaque élément (son bloc complet) apparaît une seule fois, dans un seul message
        for e in elements:
            bloc = formater_element(e)
            self.assertEqual(sum(texte.count(bloc) for texte in messages), 1)

    def test_titre_de_section_repete_dans_le_message_suivant(self):
        elements = [faire_element(i) for i in range(12)]
        messages = construire_messages([("Thème unique", elements)], DEBUT, FIN, limite=800)
        self.assertGreater(len(messages), 1)
        for texte in messages:
            self.assertIn("<b>Thème unique</b>", texte)

    def test_limite_par_defaut_sous_celle_de_telegram(self):
        elements = [faire_element(i) for i in range(40)]
        messages = construire_messages([("A", elements)], DEBUT, FIN)
        self.assertTrue(all(len(m) <= LIMITE_TELEGRAM for m in messages))

    def test_aucune_nouveaute(self):
        messages = construire_messages([], DEBUT, FIN)
        self.assertEqual(len(messages), 1)
        self.assertIn("Aucune nouveauté", messages[0])

    def test_avertissement_sources_en_echec(self):
        messages = construire_messages([("A", [faire_element(1)])], DEBUT, FIN, ["BrightLocal"])
        self.assertIn("BrightLocal", messages[-1])


class TestHtml(unittest.TestCase):
    def test_echappement_du_titre_et_du_lien(self):
        e = faire_element(1, titre="Test <script> & co")
        e.url = 'https://exemple.test/?a=1&b="2"'
        texte = formater_element(e)
        self.assertIn("Test &lt;script&gt; &amp; co", texte)
        self.assertNotIn("<script>", texte)
        self.assertIn("a=1&amp;b=&quot;2&quot;", texte)


if __name__ == "__main__":
    unittest.main()
