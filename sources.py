"""Collecte des sources : Reddit, GitHub (releases) et flux RSS/Atom.

Chaque fonction `collecter_*` renvoie une liste d'`Element`.
La partie Reddit reprend la logique de reddit_astro_veille.py (client OAuth,
pause entre les requêtes, nouvelles tentatives, upsert dans SQLite).
"""

import base64
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from outils import (
    USER_AGENT,
    Element,
    lire_iso,
    log,
    nettoyer_texte,
    resume_changelog,
    tronquer,
)

PUBLIC_BASE = "https://www.reddit.com"  # sert seulement à construire les liens (permalinks)
OAUTH_BASE = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REQUEST_DELAY = 1.1  # Reddit demande au plus ~1 requête par seconde


# --------------------------------------------------------------------------- #
# Outils communs
# --------------------------------------------------------------------------- #
def telecharger(url, entetes=None, tentatives=3, timeout=30):
    """Télécharge une URL (octets). Réessaie en cas d'erreur temporaire (429, 5xx)."""
    entetes = dict(entetes or {})
    entetes.setdefault("User-Agent", USER_AGENT)
    for essai in range(tentatives):
        try:
            requete = urllib.request.Request(url, headers=entetes)
            with urllib.request.urlopen(requete, timeout=timeout) as reponse:
                return reponse.read()
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503, 504) and essai < tentatives - 1:
                time.sleep(5 * (essai + 1))
                continue
            raise
        except urllib.error.URLError:
            if essai < tentatives - 1:
                time.sleep(5 * (essai + 1))
                continue
            raise
    raise RuntimeError(f"Échec après {tentatives} tentatives")


def garder_si_mots_cles(texte, mots_cles):
    """Sans mots-clés : on garde tout. Sinon, il faut en trouver au moins un."""
    if not mots_cles:
        return True
    bas = (texte or "").lower()
    return any(mot.lower() in bas for mot in mots_cles)


def depuis_timestamp(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc)


# --------------------------------------------------------------------------- #
# Reddit
# --------------------------------------------------------------------------- #
class RedditClient:
    """Client Reddit OAuth uniquement : pas de repli vers les endpoints publics."""

    def __init__(self, client_id, client_secret):
        if not client_id or not client_secret:
            raise ValueError("REDDIT_CLIENT_ID et REDDIT_CLIENT_SECRET sont requis")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.token_expires = 0.0
        self.base = OAUTH_BASE
        self._last_request = 0.0
        self._authenticate()

    def _authenticate(self):
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={"Authorization": f"Basic {basic}", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        self.token = payload["access_token"]
        self.token_expires = time.time() + int(payload.get("expires_in", 3600)) - 60
        self.base = OAUTH_BASE

    def get(self, path, params=None, retries=3):
        """path sans extension, ex. '/r/astrojs/new'. Renvoie le JSON décodé."""
        if self.token and time.time() > self.token_expires:
            self._authenticate()
        params = dict(params or {}, raw_json=1)
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": USER_AGENT, "Authorization": f"bearer {self.token}"}

        for attempt in range(retries):
            attente = REQUEST_DELAY - (time.time() - self._last_request)
            if attente > 0:
                time.sleep(attente)
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    self._last_request = time.time()
                    return json.load(resp)
            except urllib.error.HTTPError as err:
                self._last_request = time.time()
                if err.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"Échec après {retries} tentatives (Reddit)")


def lister_posts(client, subreddit, tri, limite):
    """Renvoie les posts d'un listing Reddit : 'new' ou 'top' (de la semaine)."""
    posts, after = [], None
    while len(posts) < limite:
        params = {"limit": min(100, limite - len(posts))}
        if tri == "top":
            params["t"] = "week"
        if after:
            params["after"] = after
        data = client.get(f"/r/{subreddit}/{tri}", params)["data"]
        enfants = [c["data"] for c in data["children"] if c.get("kind") == "t3"]
        posts.extend(enfants)
        after = data.get("after")
        if not after or not enfants:
            break
    return posts


def lister_commentaires(client, subreddit, post_id, limite=300):
    """Renvoie la liste à plat de tous les commentaires d'un post."""
    data = client.get(
        f"/r/{subreddit}/comments/{post_id}", {"limit": limite, "depth": 8, "sort": "top"}
    )
    commentaires = []

    def parcourir(enfants):
        for enfant in enfants:
            if enfant.get("kind") != "t1":
                continue  # 'more' : sous-fils non développés, ignorés
            noeud = enfant["data"]
            commentaires.append(noeud)
            reponses = noeud.get("replies")
            if isinstance(reponses, dict):
                parcourir(reponses["data"]["children"])

    parcourir(data[1]["data"]["children"])
    return commentaires


SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id                  TEXT PRIMARY KEY,
    title               TEXT,
    selftext            TEXT,
    author              TEXT,
    score               INTEGER,
    num_comments        INTEGER,
    created_utc         INTEGER,
    permalink           TEXT,
    link_flair          TEXT,
    first_seen          INTEGER,
    comments_synced_num INTEGER
);
CREATE TABLE IF NOT EXISTS comments (
    id           TEXT PRIMARY KEY,
    post_id      TEXT REFERENCES posts(id),
    author       TEXT,
    body         TEXT,
    score        INTEGER,
    created_utc  INTEGER,
    permalink    TEXT,
    is_submitter INTEGER
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_utc);
CREATE INDEX IF NOT EXISTS idx_comments_created ON comments(created_utc);
"""


def ouvrir_db(chemin):
    db = sqlite3.connect(chemin)
    db.executescript(SCHEMA)
    return db


def upsert_post(db, p):
    """Insère ou met à jour un post (upsert)."""
    db.execute(
        """
        INSERT INTO posts (id, title, selftext, author, score, num_comments,
                           created_utc, permalink, link_flair, first_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            selftext = excluded.selftext,
            score = excluded.score,
            num_comments = excluded.num_comments,
            link_flair = excluded.link_flair
        """,
        (
            p["id"],
            p.get("title", ""),
            p.get("selftext", ""),
            p.get("author"),
            p.get("score", 0),
            p.get("num_comments", 0),
            int(p.get("created_utc", 0)),
            PUBLIC_BASE + p.get("permalink", ""),
            p.get("link_flair_text"),
            int(time.time()),
        ),
    )


def sauver_commentaires(db, post_id, commentaires):
    for c in commentaires:
        corps = c.get("body") or ""
        if corps in ("[deleted]", "[removed]", ""):
            continue
        db.execute(
            """
            INSERT INTO comments (id, post_id, author, body, score, created_utc,
                                  permalink, is_submitter)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET body = excluded.body, score = excluded.score
            """,
            (
                c["id"],
                post_id,
                c.get("author"),
                corps,
                c.get("score", 0),
                int(c.get("created_utc", 0)),
                PUBLIC_BASE + c.get("permalink", ""),
                1 if c.get("is_submitter") else 0,
            ),
        )


def collecter_reddit(cfg, depuis, chemin_db):
    """Récupère posts et réponses d'un subreddit, puis renvoie ceux publiés depuis `depuis`."""
    client = RedditClient(os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET"))
    log("[reddit] connecté (OAuth)")

    subreddit = cfg["id"]
    db = ouvrir_db(chemin_db)

    # 1. Les posts (nouveaux + les mieux notés de la semaine)
    for tri in ("new", "top"):
        posts = lister_posts(client, subreddit, tri, cfg.get("limite_posts", 100))
        log(f"[reddit] {tri} : {len(posts)} posts")
        for p in posts:
            upsert_post(db, p)
    db.commit()

    # 2. Les commentaires des fils récents dont le nombre de réponses a changé
    limite_ts = time.time() - cfg.get("jours_commentaires", 14) * 86400
    a_faire = db.execute(
        """
        SELECT id, title FROM posts
        WHERE created_utc >= ? AND num_comments > 0
          AND (comments_synced_num IS NULL OR comments_synced_num != num_comments)
        ORDER BY created_utc DESC LIMIT ?
        """,
        (limite_ts, cfg.get("max_fils", 40)),
    ).fetchall()
    log(f"[reddit] {len(a_faire)} fils à synchroniser")
    for post_id, titre in a_faire:
        try:
            commentaires = lister_commentaires(client, subreddit, post_id)
        except Exception as exc:  # un fil en échec ne bloque pas les autres
            log(f"[reddit] ! fil {post_id} ignoré : {type(exc).__name__}")
            continue
        sauver_commentaires(db, post_id, commentaires)
        db.execute(
            "UPDATE posts SET comments_synced_num = num_comments WHERE id = ?", (post_id,)
        )
        db.commit()

    elements = lire_elements_reddit(db, cfg, depuis)
    db.close()
    return elements


def lire_elements_reddit(db, cfg, depuis):
    """Transforme les lignes de la base en `Element` (posts et réponses bien notées)."""
    ts = depuis.timestamp()
    mots_cles = cfg.get("mots_cles") or []
    seuil = cfg.get("seuil_score_reponse", 5)
    elements = []

    posts = db.execute(
        """SELECT id, title, selftext, score, num_comments, created_utc, permalink
           FROM posts WHERE created_utc >= ?""",
        (ts,),
    ).fetchall()
    for pid, titre, texte, score, nb, cree, lien in posts:
        if not garder_si_mots_cles(f"{titre} {texte}", mots_cles):
            continue
        resume = nettoyer_texte(texte) or f"{nb} réponse(s), score {score}"
        elements.append(
            Element(
                cle=f"reddit:{pid}",
                type="reddit_post",
                titre=titre,
                url=lien,
                source=cfg["nom"],
                date=depuis_timestamp(cree),
                resume=tronquer(resume, 180),
                texte=f"{titre}\n{texte}",
                score=score or 0,
                nb_commentaires=nb or 0,
            )
        )

    reponses = db.execute(
        """SELECT c.id, c.body, c.score, c.created_utc, c.permalink, p.title
           FROM comments c JOIN posts p ON p.id = c.post_id
           WHERE c.created_utc >= ? AND c.score >= ?""",
        (ts, seuil),
    ).fetchall()
    for cid, corps, score, cree, lien, titre_post in reponses:
        if not garder_si_mots_cles(f"{titre_post} {corps}", mots_cles):
            continue
        elements.append(
            Element(
                cle=f"reddit:{cid}",
                type="reddit_reponse",
                titre=f"Réponse sur : {titre_post}",
                url=lien,
                source=cfg["nom"],
                date=depuis_timestamp(cree),
                resume=tronquer(nettoyer_texte(corps), 180),
                texte=f"{titre_post}\n{corps}",
                score=score or 0,
            )
        )
    return elements


# --------------------------------------------------------------------------- #
# GitHub (releases)
# --------------------------------------------------------------------------- #
def garder_dernier_par_paquet(releases):
    """Dans un dépôt "monorepo" (plusieurs paquets), garde la release la plus récente de chaque paquet.

    Exemple : astro@7.4.6 et astro@7.4.7 publiées dans la même semaine -> seule 7.4.7 reste.
    """
    vus = set()
    resultat = []
    for r in sorted(releases, key=lambda r: r["published_at"], reverse=True):
        paquet = r["tag_name"].rsplit("@", 1)[0]
        if paquet in vus:
            continue
        vus.add(paquet)
        resultat.append(r)
    return resultat


def collecter_github(cfg, depuis):
    """Releases d'un dépôt GitHub via l'API REST (jeton GITHUB_TOKEN optionnel)."""
    depot = cfg["id"]
    entetes = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    url = f"https://api.github.com/repos/{depot}/releases?per_page=100"
    token = os.environ.get("GITHUB_TOKEN")
    try:
        if token:
            reponse = telecharger(url, dict(entetes, Authorization=f"Bearer {token}"))
        else:
            reponse = telecharger(url, entetes)
    except urllib.error.HTTPError as err:
        if err.code != 401 or not token:
            raise
        log("[github] jeton refusé (401), nouvel essai sans jeton")
        reponse = telecharger(url, entetes)
    releases = json.loads(reponse)

    prefixes = cfg.get("prefixes_tags") or []
    prioritaires = tuple(cfg.get("prefixes_prioritaires") or [])
    candidates = []
    for r in releases:
        if r.get("draft"):
            continue
        if r.get("prerelease") and not cfg.get("prereleases", False):
            continue
        if not r.get("published_at") or lire_iso(r["published_at"]) < depuis:
            continue
        if prefixes and not r["tag_name"].startswith(tuple(prefixes)):
            continue
        corps = r.get("body") or ""
        if not garder_si_mots_cles(f"{r['tag_name']} {corps}", cfg.get("mots_cles")):
            continue
        candidates.append(r)

    elements = []
    ignorer_sans_notes = cfg.get("ignorer_sans_notes", True)
    for r in garder_dernier_par_paquet(candidates):
        corps = r.get("body") or ""
        resume = resume_changelog(corps)
        prioritaire = bool(prioritaires) and r["tag_name"].startswith(prioritaires)
        # Une release sans notes utiles (souvent une simple mise à jour de dépendances)
        # n'apporte rien : on l'ignore, sauf si elle est prioritaire (ex. astro@).
        if not resume and ignorer_sans_notes and not prioritaire:
            continue
        elements.append(
            Element(
                cle=f"github:{r['id']}",
                type="github",
                titre=r.get("name") or r["tag_name"],
                url=r["html_url"],
                source=cfg["nom"],
                date=lire_iso(r["published_at"]),
                resume=resume or "Voir les notes de version.",
                texte=f"{r['tag_name']}\n{corps[:3000]}",
                prioritaire=prioritaire,
            )
        )
    log(f"[github] {depot} : {len(elements)} release(s) retenue(s)")
    return elements


# --------------------------------------------------------------------------- #
# Flux RSS / Atom
# --------------------------------------------------------------------------- #
NS_ATOM = "{http://www.w3.org/2005/Atom}"
NS_CONTENU = "{http://purl.org/rss/1.0/modules/content/}"
NS_DC = "{http://purl.org/dc/elements/1.1/}"


def lire_date(texte):
    """Lit une date RSS (RFC 822) ou Atom (ISO 8601). Renvoie None si illisible."""
    if not texte:
        return None
    try:
        d = parsedate_to_datetime(texte)
    except (TypeError, ValueError):
        try:
            d = lire_iso(texte.strip())
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _texte(noeud, nom):
    enfant = noeud.find(nom)
    return (enfant.text or "").strip() if enfant is not None else ""


def lire_flux(contenu):
    """Lit un flux RSS 2.0 ou Atom. Renvoie une liste de dictionnaires simples."""
    racine = ET.fromstring(contenu)
    articles = []

    for item in racine.iter("item"):  # RSS 2.0
        lien = _texte(item, "link")
        articles.append(
            {
                "id": _texte(item, "guid") or lien,
                "titre": _texte(item, "title"),
                "lien": lien,
                "date": lire_date(_texte(item, "pubDate") or _texte(item, NS_DC + "date")),
                "resume": _texte(item, NS_CONTENU + "encoded") or _texte(item, "description"),
            }
        )

    for entree in racine.iter(NS_ATOM + "entry"):  # Atom
        lien = ""
        for l in entree.findall(NS_ATOM + "link"):
            if l.get("rel", "alternate") == "alternate":
                lien = l.get("href", "")
                break
        articles.append(
            {
                "id": _texte(entree, NS_ATOM + "id") or lien,
                "titre": _texte(entree, NS_ATOM + "title"),
                "lien": lien,
                "date": lire_date(
                    _texte(entree, NS_ATOM + "published") or _texte(entree, NS_ATOM + "updated")
                ),
                "resume": _texte(entree, NS_ATOM + "summary") or _texte(entree, NS_ATOM + "content"),
            }
        )
    return articles


def collecter_rss(cfg, depuis):
    contenu = telecharger(cfg["id"])
    elements = []
    for a in lire_flux(contenu):
        if a["date"] is None or a["date"] < depuis or not a["lien"] or not a["titre"]:
            continue
        texte = nettoyer_texte(a["resume"])
        if not garder_si_mots_cles(f"{a['titre']} {texte}", cfg.get("mots_cles")):
            continue
        elements.append(
            Element(
                cle=f"rss:{a['id']}",
                type="rss",
                titre=nettoyer_texte(a["titre"]),
                url=a["lien"],
                source=cfg["nom"],
                date=a["date"],
                resume=tronquer(texte, 180),
                texte=f"{a['titre']}\n{texte[:3000]}",
            )
        )
    log(f"[rss] {cfg['nom']} : {len(elements)} article(s) retenu(s)")
    return elements


# --------------------------------------------------------------------------- #
# Toutes les sources
# --------------------------------------------------------------------------- #
def reddit_utilisable(config):
    """Reddit est facultatif et désactivé par défaut (reddit.enabled dans config.yaml).

    - désactivé : on ne fait aucun appel à Reddit (juste une ligne de journal) ;
    - activé mais sans identifiants : avertissement et on ignore Reddit, sans rien tenter d'autre.
    """
    if not (config.get("reddit") or {}).get("enabled", False):
        log("[reddit] désactivé (reddit.enabled: false) : aucun appel")
        return False
    if not os.environ.get("REDDIT_CLIENT_ID") or not os.environ.get("REDDIT_CLIENT_SECRET"):
        log("[reddit] AVERTISSEMENT : reddit.enabled est true mais REDDIT_CLIENT_ID / "
            "REDDIT_CLIENT_SECRET sont absents : source Reddit ignorée")
        return False
    return True


def collecter_tout(config, depuis, chemin_db):
    """Parcourt les sources du config.yaml. Un échec est noté puis on continue.

    Renvoie (liste d'éléments, liste des noms de sources en échec, nombre de sources essayées).
    """
    elements, echecs, essayees = [], [], 0
    for cfg in config.get("sources", []):
        if cfg.get("actif", True) is False:
            continue
        if cfg["type"] == "reddit" and not reddit_utilisable(config):
            continue  # Reddit désactivé ou sans identifiants : aucun appel, pas un échec
        essayees += 1
        try:
            if cfg["type"] == "reddit":
                elements += collecter_reddit(cfg, depuis, chemin_db)
            elif cfg["type"] == "github":
                elements += collecter_github(cfg, depuis)
            elif cfg["type"] == "rss":
                elements += collecter_rss(cfg, depuis)
            else:
                raise ValueError(f"type de source inconnu : {cfg['type']}")
        except Exception as exc:
            log(f"[erreur] source « {cfg.get('nom', '?')} » ignorée : {type(exc).__name__}: {exc}")
            echecs.append(cfg.get("nom", "?"))
    return elements, echecs, essayees
