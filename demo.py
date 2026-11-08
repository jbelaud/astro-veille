"""Données fictives pour tester l'outil sans réseau (option --demo)."""

from datetime import timedelta

from outils import Element


def elements_fictifs(maintenant):
    """Quelques éléments inventés, de types différents."""
    def il_y_a(jours):
        return maintenant - timedelta(days=jours)

    return [
        Element(
            cle="github:1001", type="github", titre="astro@9.9.0",
            url="https://github.com/withastro/astro/releases/tag/astro%409.9.0",
            source="Astro (releases)", date=il_y_a(1),
            resume="Ajoute une option pour configurer les middleware par route.",
            texte="astro@9.9.0\nAjoute le support de middleware et de view transitions améliorées.",
            prioritaire=True,
        ),
        Element(
            cle="github:1002", type="github", titre="@astrojs/cloudflare@99.0.1",
            url="https://github.com/withastro/astro/releases/tag/%40astrojs%2Fcloudflare%4099.0.1",
            source="Astro (releases)", date=il_y_a(2),
            resume="Corrige le déploiement sur Cloudflare avec l'adapter SSR.",
            texte="@astrojs/cloudflare@99.0.1\nFix adapter SSR deploy sur Cloudflare Workers.",
        ),
        Element(
            cle="reddit:c1", type="reddit_reponse",
            titre="Réponse sur : Content collections et glob() ne trouvent plus mes fichiers",
            url="https://www.reddit.com/r/astrojs/comments/abc/x/c1/", source="r/astrojs",
            date=il_y_a(2), score=42,
            resume="Utilise content.config.ts avec le loader glob et vérifie le chemin de base.",
            texte="content collection defineCollection glob content.config",
        ),
        Element(
            cle="reddit:p1", type="reddit_post",
            titre="Astro + i18n : comment gérer les routes multilingues ?",
            url="https://www.reddit.com/r/astrojs/comments/def/x/", source="r/astrojs",
            date=il_y_a(3), score=12, nb_commentaires=9,
            resume="Je cherche une bonne pratique pour le routage par locale.",
            texte="i18n locale routing multilingual",
        ),
        Element(
            cle="rss:1", type="rss", titre="Local pack : ce qui change pour le SEO local",
            url="https://example.com/local-pack", source="BrightLocal", date=il_y_a(2),
            resume="Les signaux de proximité et le profil Google Business Profile évoluent.",
            texte="local seo google business profile local pack",
        ),
        Element(
            cle="rss:2", type="rss", titre="Comment apparaître dans les AI Overviews (GEO)",
            url="https://example.com/geo", source="Search Engine Land", date=il_y_a(4),
            resume="Les bases de l'optimisation pour les moteurs génératifs.",
            texte="generative engine optimization ai overview llms.txt",
        ),
        Element(
            cle="rss:3", type="rss", titre="Support de Vite 8 dans Netlify",
            url="https://example.com/vite", source="Netlify changelog", date=il_y_a(5),
            resume="Les builds Vite sont plus rapides sur Netlify.",
            texte="vite build deploy netlify",
        ),
        Element(
            cle="rss:4", type="rss", titre="Un article <sans> thème & caractères spéciaux",
            url="https://example.com/autre?a=1&b=2", source="Cloudflare blog", date=il_y_a(6),
            resume="Test d'échappement HTML : 1 < 2 & 3 > 2.",
            texte="divers",
        ),
    ]
