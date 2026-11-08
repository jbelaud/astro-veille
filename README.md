# astro-veille

Outil de veille technique pour les sites Astro. Chaque lundi à 9h (heure de Paris), le programme :

1. collecte les nouveautés (releases GitHub, flux RSS, et Reddit en option, désactivé par défaut) ;
2. garde les ~15 éléments les plus pertinents, classés par thème ;
3. les envoie dans un message Telegram.

Le tout tourne tout seul avec GitHub Actions (dépôt privé), sans rien lancer à la main.

## Fichiers

| Fichier | Rôle |
|---|---|
| `veille.py` | Point d'entrée : enchaîne collecte, tri, envoi, état |
| `sources.py` | Collecte Reddit, GitHub, RSS |
| `tri.py` | Thèmes, déduplication, score de pertinence |
| `telegram.py` | Mise en forme HTML, découpage, envoi, alerte |
| `outils.py` | Config, `state.json`, heure de Paris, masquage des secrets |
| `demo.py` | Données fictives pour tester sans réseau |
| `config.yaml` | Sources et thèmes (à modifier sans toucher au code) |
| `state.json` | Mémoire entre deux exécutions (committée par le workflow) |
| `.github/workflows/veille.yml` | Planification GitHub Actions |
| `tests/` | Tests sans appel réseau |

## Installation locale (Windows, PowerShell)

```powershell
cd C:\Developpement\astro-veille
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`tzdata` est dans `requirements.txt` : sous Windows, Python en a besoin pour connaître le fuseau « Europe/Paris ».

## Tester sans rien envoyer

```powershell
# Avec des données fictives (aucun appel réseau pour la collecte)
python veille.py --demo --dry-run

# Avec les vraies sources, mais sans envoyer et sans modifier state.json
python veille.py --dry-run

# Les tests
python -m unittest -v
```

`--dry-run` affiche le message à l'écran au lieu de l'envoyer sur Telegram, et ne touche pas à `state.json`.

Pour tester l'envoi Telegram seul (avec les données fictives, `state.json` n'est pas modifié) :

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."
$env:TELEGRAM_CHAT_ID = "..."
python veille.py --demo
```

## Secrets à créer sur GitHub

Dans le dépôt : **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Obligatoire | Comment l'obtenir |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | oui | Parler à `@BotFather` sur Telegram, commande `/newbot` |
| `TELEGRAM_CHAT_ID` | oui | Écrire un message à ton bot, puis ouvrir `https://api.telegram.org/bot<TOKEN>/getUpdates` dans un navigateur et relever `chat` → `id` |
| `REDDIT_CLIENT_ID` | non (seulement si Reddit est activé) | Voir « Activer Reddit » plus bas |
| `REDDIT_CLIENT_SECRET` | non (seulement si Reddit est activé) | Voir « Activer Reddit » plus bas |
| `GITHUB_TOKEN` | non | **Rien à créer** : GitHub Actions le fournit automatiquement et le workflow l'utilise. Un secret ne peut d'ailleurs pas porter un nom commençant par `GITHUB_`. Pour un usage local, tu peux définir la variable d'environnement avec un jeton personnel, mais ce n'est pas obligatoire. |

Aucun secret n'est écrit dans le code ni dans les logs. Les messages d'erreur passent par un filtre qui remplace tout secret connu par `***`.

Le dépôt doit autoriser le workflow à écrire : **Settings → Actions → General → Workflow permissions** (le fichier `veille.yml` demande déjà `contents: write`, mais un réglage d'organisation plus strict pourrait le bloquer).

## Planification : pourquoi 7h et 8h UTC

GitHub Actions travaille en UTC et ne gère pas l'heure d'été. 9h à Paris, c'est :

- 8h UTC en hiver (UTC+1) ;
- 7h UTC en été (UTC+2).

Le workflow se déclenche donc à `0 7 * * 1` **et** `0 8 * * 1` (chaque lundi). Une première étape vérifie qu'il est bien entre 9h00 et 9h59 à Paris : sinon, le job s'arrête sans rien envoyer. Un seul des deux déclencheurs passe donc chaque lundi.

Deux limites à connaître :

- GitHub peut retarder les lancements planifiés (parfois de plusieurs dizaines de minutes aux heures chargées). Si le retard dépasse 1h, le message de la semaine est sauté ; relance-le alors à la main (**Actions → Veille Astro → Run workflow**, sans test d'heure).
- Si le dépôt reste inactif longtemps, GitHub peut désactiver les workflows planifiés. Le commit hebdomadaire de `state.json` devrait l'éviter, mais je n'ai pas pu le vérifier ; si les messages s'arrêtent, regarde l'onglet Actions.

## Ajouter une source ou un thème

Tout se passe dans `config.yaml`.

**Une source** : ajoute un bloc dans `sources:`.

```yaml
  - type: rss                      # reddit, github ou rss
    id: "https://exemple.com/feed.xml"
    nom: "Mon blog préféré"       # nom affiché dans Telegram
    mots_cles: ["astro", "seo"]   # optionnel : ne garde que les éléments qui en contiennent un
```

Pour GitHub, `id` est de la forme `propriétaire/dépôt`. Pour suivre un autre paquet d'un monorepo, ajoute son préfixe de tag dans `prefixes_tags` (par exemple `"@astrojs/vue@"`). Pour retirer une source sans la supprimer : `actif: false`.

**Un thème** : ajoute une ligne dans `themes:`.

```yaml
  "Mon nouveau thème": ["mot-clé un", "mot-clé deux"]
```

Un mot-clé doit commencer un mot (`ssr` ne correspond pas à `classroom`, `hydrat` correspond à `hydration`). Un élément peut avoir plusieurs thèmes : il est affiché sous le principal (celui avec le plus de mots-clés trouvés) et les autres sont indiqués en « aussi ».

## Comment les éléments sont choisis

- Seuls les éléments publiés depuis la dernière exécution réussie sont gardés (au premier lancement : 7 jours).
- Les doublons sont supprimés d'après leur identifiant (id de release GitHub, `guid` ou lien RSS, et id Reddit si Reddit est activé) et ceux déjà envoyés ne sont pas renvoyés.
- Tri : releases d'Astro et réponses Reddit très notées (si Reddit est activé) d'abord, puis le reste. Limite : 15 éléments (`max_elements`). Les éléments en trop sont abandonnés, pas reportés à la semaine suivante.
- Pour les dépôts qui publient plusieurs paquets (comme `withastro/astro`), seule la dernière release de chaque paquet est gardée.
- Si une source échoue, l'erreur est journalisée, les autres continuent, et le message se termine par la liste des sources en échec. Si **toutes** les sources échouent, ou en cas d'erreur grave, une alerte courte est envoyée sur Telegram et le job est marqué en échec (`state.json` n'est alors pas mis à jour).

## Flux RSS : état de la vérification

Le 8/11/2026, je n'ai pas pu télécharger les flux directement depuis mon environnement. Je me suis appuyé sur des contenus de flux vus dans des résultats de recherche. À toi de confirmer les flux marqués « non confirmé » en les ouvrant dans un navigateur (ou en lançant `python veille.py --dry-run` et en regardant les lignes `[erreur]` dans le journal).

| Flux | URL | État |
|---|---|---|
| Blog Astro | `https://astro.build/rss.xml` | Confirmé (RSS 2.0 avec `guid` et `pubDate` vu) |
| Netlify changelog | `https://www.netlify.com/changelog/feed.xml` | Confirmé (RSS 2.0 vu) |
| Google Search Central | `https://developers.google.com/search/blog/feed.xml` | Confirmé (RSS 2.0 vu) |
| Search Engine Land | `https://feeds.feedburner.com/searchengineland` | Partiel : donné comme fonctionnel par un annuaire tiers ; je n'ai pas vu le flux lui-même. `https://searchengineland.com/feed` n'a pas été confirmé non plus. |
| Cloudflare blog | `https://blog.cloudflare.com/rss/` | Non confirmé : les flux par auteur et par tag de ce blog existent (même format), mais pas la racine |
| Cloudflare changelog | `https://developers.cloudflare.com/changelog/index.xml` | Non confirmé : l'URL est citée dans un article du blog Cloudflare, mais je n'ai pas vu le contenu |
| Whitespark | `https://whitespark.ca/feed/` | Non confirmé : vu uniquement dans un annuaire tiers |
| BrightLocal | `https://www.brightlocal.com/feed/` | Non confirmé : aucune URL officielle trouvée, et un annuaire tiers montre des articles anciens, le flux est peut-être inactif |

Le blog Astro (`astro.build/rss.xml`) ne faisait pas partie de ta liste : je l'ai ajouté parce qu'il annonce les versions majeures. Retire-le dans `config.yaml` si tu n'en veux pas.

Les releases GitHub (API REST) ont été testées en réel depuis ton poste (voir le récapitulatif de la livraison).

## Activer Reddit

Reddit est une source **facultative, désactivée par défaut** (`reddit.enabled: false` dans `config.yaml`). Tant que ce réglage vaut `false`, le programme ne fait **aucun appel à Reddit** (ni authentifié, ni public) et tout le reste (GitHub, flux RSS, Telegram) fonctionne normalement.

Reddit exige une approbation explicite avant tout accès à son API, même pour un usage personnel. Pour l'activer :

1. **Obtiens d'abord l'approbation de Reddit** pour ton usage de l'API (je n'ai pas pu vérifier la procédure actuelle : suis les indications de Reddit pour les développeurs).
2. Une fois approuvé, crée l'application de type « script » sur https://www.reddit.com/prefs/apps et relève l'identifiant et le secret.
3. Crée les secrets GitHub `REDDIT_CLIENT_ID` et `REDDIT_CLIENT_SECRET` (en local : les variables d'environnement du même nom).
4. Mets `enabled: true` sous `reddit:` dans `config.yaml`.

Règles à respecter :

- Si `reddit.enabled` vaut `true` mais que les deux identifiants manquent, le programme journalise un avertissement et ignore Reddit, sans rien tenter d'autre (il n'y a plus de repli vers les adresses publiques de Reddit).
- L'usage de l'API doit respecter la Responsible Builder Policy de Reddit. Aucune donnée Reddit ne doit servir à entraîner un modèle d'IA ni être republiée.
- Aucune donnée Reddit n'est committée dans le dépôt : `state.json` ne contient que des identifiants et la date de dernière exécution, et la base SQLite (`*.sqlite`) est exclue par `.gitignore`. Ne la committe jamais.

## Mise en route sur GitHub

```powershell
git init
git add .
git commit -m "Veille Astro"
git branch -M main
git remote add origin https://github.com/jbelaud/astro-veille.git
git push -u origin main
```

Puis crée les secrets (voir plus haut) et lance une première fois à la main : **Actions → Veille Astro → Run workflow**.
