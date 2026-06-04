# ⚡ Admin Tycoon Bot — Guide Complet

## 📦 Installation

```bash
pip install -r requirements.txt
```

## ⚙️ Configuration .env

```env
DISCORD_TOKEN=ton_token_ici
OWNER_ID=ton_id_discord
```

## 🚀 Lancer le bot

```bash
python bot.py
```

Le bot démarre + l'API dashboard sur `http://127.0.0.1:5000`

## 🌐 Dashboard en ligne (GitHub Pages)

Le dashboard est hébergé gratuitement et accessible en ligne à l'adresse suivante :
`https://VOTRE-PSEUDO-GITHUB.github.io/NOM-DE-VOTRE-DEPOT/`

*Le bot (hébergé sur Render) doit être en ligne pour que le dashboard puisse communiquer avec l'API.*

---

## 🔧 CORRECTIFS APPORTÉS

### ✅ Fix Reaction Roles (problème principal)
**Problème** : Les rôles n'étaient pas donnés car Discord envoie les emoji en plusieurs formats
et le guild/member pouvait être `None` avec `on_raw_reaction_add`.

**Corrections** :
- Récupération du `guild` et `member` via `bot.get_guild()` / `guild.get_member()`
- Gestion des emoji custom Discord (format `<:nom:id>`)
- Logs console pour débugger
- Try/except avec messages d'erreur précis

**⚠️ Vérification permissions** : Le rôle du bot doit être **au-dessus** des rôles qu'il attribue dans la liste des rôles du serveur !

### ✅ Fix Invite Tracker
**Problème** : L'ancien code comparait mal les snapshots et ne sauvegardait pas les données.

**Corrections** :
- Système de snapshot `{code: uses}` propre
- Événements `on_invite_create` et `on_invite_delete` pour garder le tracker à jour
- Sauvegarde dans `invites.json`
- Nouvelles commandes `/invites` et `/inviteleaderboard`

### ✅ Fix Modération (kick/ban)
**Problème** : Pas de gestion des erreurs de permission.

**Corrections** :
- Try/except sur tous les kick/ban/mute
- Messages d'erreur clairs si permissions insuffisantes

### ✅ Nouveau : /help
Commande `/help` avec toutes les catégories, utilise `/help [catégorie]` pour le détail.

### ✅ Nouveau : Message de bienvenue personnalisable
Variables disponibles dans le message :
- `{user}` → mention du membre
- `{username}` → nom du membre
- `{server}` → nom du serveur
- `{count}` → nombre de membres
- `{inviter}` → mention de celui qui a invité

---

## 📊 Dashboard — Fonctionnalités

| Section | Ce que tu peux faire |
|---------|---------------------|
| Vue d'ensemble | Stats globales (messages, membres, tickets, coins) |
| Bienvenue | Titre, couleur, message avec variables, aperçu live |
| Règles | Titre et texte des règles (appliqué au prochain /setup_rules) |
| Salons | Définir welcome/leave/logs/suggestions/levels |
| Rôles & Niveaux | Auto-rôle, rôles par niveau (ajouter/supprimer) |
| Automod | Toggle anti-spam, gestion mots interdits |
| Reaction Roles | Voir, ajouter, supprimer les reaction roles |
| Invitations | Top inviteurs du serveur |
| Avertissements | Tous les warns par membre |
| Économie | Classement coins/banque/total |

---

## 🎟️ Comment configurer les Reaction Roles

### Via Dashboard (recommandé)
1. Ouvre `dashboard.html`
2. Va dans "Reaction Roles"
3. Entre l'ID du message (clic droit → Copier l'identifiant)
4. Entre l'emoji exact
5. Choisis le rôle
6. Clique "Ajouter"

### Via commande Discord
```
/reactionrole message_id:123456789 emoji:✅ role:@MonRole
```

### ⚠️ Problème de permission fréquent
Le bot doit avoir :
- Permission "Gérer les rôles"
- Son rôle doit être **PLUS HAUT** que les rôles à attribuer

---

## 📨 Invite Tracker

Le tracker se met à jour automatiquement. Les données sont dans `invites.json`.

Commandes disponibles :
- `/invites` — Voir ses invitations (ou celles d'un membre)
- `/inviteleaderboard` — Top des inviteurs

---

## ❓ Help

Commande `/help` dans Discord pour voir toutes les commandes.
Utilise `/help ⚙️ Setup` (ou autre catégorie) pour le détail.

---

## 📁 Stockage des Données

Le bot n'utilise plus de fichiers JSON locaux. Toutes les données (Économie, Niveaux, Warns, Invitations) sont stockées en toute sécurité dans une base de données cloud **Supabase (PostgreSQL)** pour garantir une stabilité maximale et éviter toute perte de données.