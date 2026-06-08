import discord
from discord.ext import commands, tasks
from discord import app_commands
import os, json, asyncio, random, re, threading
from datetime import timedelta, datetime, timezone
from dotenv import load_dotenv
from flask import Flask, jsonify, request
import threading
import hashlib

# --- CONFIGURATION DES RÔLES STAFF ---
ALLOWED_ROLE_IDS = {
    1507854910505353236, # Remplace par l'ID réel du rôle Propriétaire
    1507851921174561030, # Remplace par l'ID réel du rôle Administrateur
    1507852070089134170  # Remplace par l'ID réel du rôle Modérateur
}
# --- CONFIGURATION DES NIVEAUX ---
# Remplace les valeurs par les vrais ID de tes rôles Discord (Clic droit > Copier l'ID)
LEVEL_ROLES = {
    15: 1512151369052717128, # 👑 Dieu du Système
    10: 1512151165423456396, # 🎓 Ingénieur Réseau
    5:  1512150982371446904, # 📈 Administrateur IT
    1:  1507850671548792944  # 🖥️ Stagiaire IT
}
def is_staff(member):
    """Vérifie si le membre possède au moins un rôle autorisé."""
    user_roles = {role.id for role in member.roles}
    return not user_roles.isdisjoint(ALLOWED_ROLE_IDS)
# ============================================================
# 1. INIT ET GESTION DES FICHIERS (Dossier /data)
# ============================================================
from supabase import create_client, Client

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
DASHBOARD_PORT = int(os.getenv('DASHBOARD_PORT', '5000'))

# --- CONNEXION SUPABASE (BOT) ---
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ FATAL: Clés Supabase Bot manquantes !")
    raise SystemExit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
print(f"✅ Supabase BOT connecté !")

# --- CONNEXION SUPABASE (JEU - Pour le /sync) ---
SUPABASE_GAME_URL = os.getenv('SUPABASE_GAME_URL')
SUPABASE_GAME_KEY = os.getenv('SUPABASE_GAME_KEY')

if SUPABASE_GAME_URL and SUPABASE_GAME_KEY:
    supabase_game = create_client(SUPABASE_GAME_URL, SUPABASE_GAME_KEY)
    print("✅ Supabase JEU connecté !")
else:
    supabase_game = None
    print("⚠️ Attention: Clés Supabase Jeu (SUPABASE_GAME_URL) manquantes.")

def _get_pk(table_name):
    """Détermine la colonne clé primaire en fonction de la table"""
    if table_name == 'reminders': return 'id'
    if table_name == 'notes': return 'user_id'
    return 'guild_id'

def _load(filename, default):
    table = filename.replace('.json', '')
    try:
        res = supabase.table(table).select("*").execute()

        if not hasattr(res, 'data') or res.data is None:
            print(f"⚠️ _load({table}) : réponse vide ou nulle")
            return default

        # Cas spécial pour les rappels (liste)
        if isinstance(default, list) and table == 'reminders':
            if res.data: return res.data[0]['data']
            return default

        # Pour tous les autres (dictionnaires guild_id → data)
        result = {}
        pk = _get_pk(table)
        for row in res.data:
            if pk in row and 'data' in row:
                result[str(row[pk])] = row['data']
        return result
    except Exception as e:
        print(f"❌ Erreur _load Supabase ({table}) : {type(e).__name__}: {e}")
        return default

def _save(filename, data):
    table = filename.replace('.json', '')
    try:
        # Cas spécial pour les rappels (liste → 1 seule ligne avec id='global')
        if isinstance(data, list) and table == 'reminders':
            supabase.table(table).upsert({'id': 'global', 'data': data}).execute()
            return

        pk = _get_pk(table)
        rows = [{pk: str(key), 'data': val} for key, val in data.items()]
        if rows:
            # upsert par batch de 50 pour éviter les timeouts
            for i in range(0, len(rows), 50):
                supabase.table(table).upsert(rows[i:i+50]).execute()
    except Exception as e:
        print(f"❌ Erreur _save Supabase ({table}) : {type(e).__name__}: {e}")

def joined_members(): return _load('joined_members.json', {})
def sjoined(d): _save('joined_members.json', d)

def cfg():    return _load('config.json', {})
def scfg(d):  _save('config.json', d)
def eco():    return _load('economy.json', {})
def seco(d):  _save('economy.json', d)
def lvl():    return _load('levels.json', {})
def slvl(d):  _save('levels.json', d)
def wrn():    return _load('warns.json', {})
def swrn(d):  _save('warns.json', d)
def rem():    return _load('reminders.json', [])
def srem(d):  _save('reminders.json', d)
def stats():  return _load('stats.json', {})
def sstats(d):_save('stats.json', d)
def nts():    return _load('notes.json', {})
def snts(d):  _save('notes.json', d)
def inv():    return _load('invites.json', {})
def sinv(d):  _save('invites.json', d)


# ============================================================
# 🎮 SYSTEME DE SYNCHRONISATION DES NIVEAUX DU JEU
# ============================================================


async def update_member_special_roles(member: discord.Member, is_vip: bool, max_money: float):
    # --- REMPLACE PAR TES VRAIS ID DE RÔLES DISCORD ---
    ROLE_VIP_ID = 1512150055837241474  # ID du rôle 💎 VIP
    ROLE_RICHE_ID = 1512090948992106516 # ID du rôle Riche (ex: Milliardaire)
    
    PALIER_RICHE = 1000000000  # Argent nécessaire pour le rôle Riche (Ici: 1 Milliard)

    roles_to_add = []
    
    # 1. Vérification du rôle VIP
    vip_role = member.guild.get_role(ROLE_VIP_ID)
    if vip_role and is_vip and vip_role not in member.roles:
        roles_to_add.append(vip_role)

    # 2. Vérification du rôle Riche
    riche_role = member.guild.get_role(ROLE_RICHE_ID)
    if riche_role and max_money >= PALIER_RICHE and riche_role not in member.roles:
        roles_to_add.append(riche_role)

    # On donne les rôles au joueur s'il en a débloqué
    if roles_to_add:
        try:
            await member.add_roles(*roles_to_add)
        except Exception as e:
            print(f"Impossible de donner les rôles spéciaux à {member.name} : {e}")


@tasks.loop(minutes=15)
async def auto_sync_roles():
    print("🔄 [SCAN] Début de la vérification des niveaux, VIP et richesses...")
    
    GUILD_ID = 1511382754615361626  # ID de ton serveur Discord
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    
    try:
        players_resp = supabase_game.table('players').select('username, discord_id, game_state').not_.is_('discord_id', 'null').execute()
        if not players_resp.data: return
        
        player_stats = {} # Stockera { "discord_id": {"level": X, "money": Y, "vip": bool} }
        username_to_discord = {}
        
        def extract_stats(state):
            if isinstance(state, str):
                try: state = json.loads(state)
                except: return 1, 0.0, False
            if isinstance(state, dict):
                lvl = int(state.get('level', 1))
                money = float(state.get('money', 0.0))
                is_vip = state.get('vip', False) or state.get('is_vip', False)
                return lvl, money, is_vip
            return 1, 0.0, False

        # Lecture des parties en cours
        for row in players_resp.data:
            d_id = str(row['discord_id'])
            username = row.get('username')
            lvl, money, is_vip = extract_stats(row.get('game_state', {}))
            
            player_stats[d_id] = {"level": lvl, "money": money, "vip": is_vip}
            if username:
                username_to_discord[username] = d_id
                
        # Lecture de toutes les sauvegardes
        usernames = list(username_to_discord.keys())
        if usernames:
            saves_resp = supabase_game.table('saves').select('username, game_state').in_('username', usernames).execute()
            for row in saves_resp.data:
                username = row.get('username')
                d_id = username_to_discord.get(username)
                if d_id:
                    lvl, money, is_vip = extract_stats(row.get('game_state', {}))
                    # On garde les meilleures stats
                    player_stats[d_id]["level"] = max(player_stats[d_id]["level"], lvl)
                    player_stats[d_id]["money"] = max(player_stats[d_id]["money"], money)
                    player_stats[d_id]["vip"] = player_stats[d_id]["vip"] or is_vip
                        
        # Distribution
        for member in guild.members:
            if member.bot: continue
            d_id = str(member.id)
            if d_id in player_stats:
                stats = player_stats[d_id]
                await update_member_level_role(member, stats["level"])
                await update_member_special_roles(member, stats["vip"], stats["money"])
                
    except Exception as e:
        print(f"❌ Erreur lors de la synchronisation automatique: {e}")


@tasks.loop(hours=1)
async def auto_update_leaderboard():
    if not supabase_game: return
    try:
        res = supabase_game.table('players').select('username, game_state, is_excluded').execute()
        if not res.data: return
        
        valid_players = [p for p in res.data if not p.get('is_excluded')]
        
        # 1. Extraction et simplification des données une seule fois
        players_data = []
        for p in valid_players:
            st = p.get('game_state', {})
            if isinstance(st, str):
                try: st = json.loads(st)
                except: st = {}
            elif not isinstance(st, dict):
                st = {}
                
            players_data.append({
                'username': p.get('username'),
                'money': float(st.get('money', 0)),
                'level': int(st.get('level', 1)),
                'xp': float(st.get('xp', 0)),
                'is_vip': bool(st.get('is_vip'))
            })

        # 2. Envoi personnalisé pour chaque serveur
        c = cfg()
        for gid_str, data in c.items():
            ch_id = data.get('live_lb_channel')
            if not ch_id: continue
            
            guild = bot.get_guild(int(gid_str))
            if not guild: continue
            
            ch = guild.get_channel(ch_id)
            if not ch: continue

            # 🟢 NOUVEAUTÉ : On lit le critère choisi (par défaut 'money')
            sort_by = data.get('lb_sort_by', 'money')
            
            if sort_by == 'level':
                # Tri par niveau (puis par XP en cas d'égalité)
                players_data.sort(key=lambda x: (x['level'], x['xp']), reverse=True)
                titre = "🏆 TOP 10 MONDIAL - Les plus Hauts Niveaux"
            else:
                # Tri par argent
                players_data.sort(key=lambda x: x['money'], reverse=True)
                titre = "🏆 TOP 10 MONDIAL - Les plus Riches"

            top_10 = players_data[:10]
            
            embed = discord.Embed(title=titre, color=0xffd700, timestamp=discord.utils.utcnow())
            embed.description = "Ce classement s'actualise automatiquement."
            
            medals = ["🥇","🥈","🥉", "4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
            for i, p in enumerate(top_10):
                vip = "💎" if p['is_vip'] else ""
                embed.add_field(name=f"{medals[i]} {p['username']} {vip}", value=f"Niv {p['level']} | {int(p['money']):,} €", inline=False)
                
            # Nettoie les anciens classements du bot et envoie le nouveau
            await ch.purge(limit=5, check=lambda m: m.author == bot.user)
            await ch.send(embed=embed)
            
    except Exception as e:
        print(f"Erreur Auto-Leaderboard: {e}")

# ============================================================

async def update_member_level_role(member: discord.Member, user_level: int):
    """
    Attribue le rôle de niveau correspondant au joueur.

    Règles :
    - 🖥️ Stagiaire IT     (niv 1)  → JAMAIS retiré (rôle de base permanent)
    - 📈 Administrateur IT (niv 5)  → retiré si niv >= 10
    - 🎓 Ingénieur Réseau  (niv 10) → retiré si niv >= 15
    - 👑 Dieu du Système   (niv 15) → jamais retiré (sommet)
    """
    # ID du 🖥️ Stagiaire IT — protégé, ne sera JAMAIS supprimé automatiquement
    STAGIAIRE_ID = LEVEL_ROLES.get(1)

    # 1. Trouver le rôle cible (niveau le plus haut débloqué par user_level)
    target_level = None
    target_role_id = None
    for level_req, role_id in sorted(LEVEL_ROLES.items(), reverse=True):
        if user_level >= level_req:
            target_level = level_req
            target_role_id = role_id
            break

    if not target_role_id:
        return  # Niveau insuffisant pour obtenir un rôle

    target_role = member.guild.get_role(target_role_id)
    if not target_role:
        print(f"⚠️ Rôle ID {target_role_id} introuvable sur le serveur.")
        return

    # 2. Si le joueur a déjà le bon rôle, rien à faire
    if target_role in member.roles:
        return

    # 3. Donner le nouveau rôle
    await member.add_roles(target_role)
    print(f"🎖️ Promotion ! {member.name} → {target_role.name} (niv. {user_level})")

    # 4. Retirer uniquement les rôles de niveau STRICTEMENT INFÉRIEUR au rôle cible
    #    Le 🖥️ Stagiaire IT (niv 1) est TOUJOURS conservé quoi qu'il arrive
    roles_to_remove = []
    for level_req, role_id in LEVEL_ROLES.items():
        if role_id == target_role_id:
            continue          # Ne pas retirer le rôle qu'on vient d'attribuer
        if role_id == STAGIAIRE_ID:
            continue          # 🖥️ Stagiaire IT → JAMAIS retiré
        if level_req < target_level:  # Seulement les niveaux inférieurs au cible
            old_role = member.guild.get_role(role_id)
            if old_role and old_role in member.roles:
                roles_to_remove.append(old_role)

    if roles_to_remove:
        await member.remove_roles(*roles_to_remove)
        print(f"  ↳ Rôles inférieurs retirés : {[r.name for r in roles_to_remove]}")


# ── Envoi dans le salon de logs de modération ──
async def send_log(guild, embed):
    c = cfg()
    lid = c.get(str(guild.id), {}).get('log_channel')
    ch = guild.get_channel(lid) if lid else None
    if ch:
        try: await ch.send(embed=embed)
        except: pass

# ── Envoi dans le salon de modération dédié (messages ban/kick/warn...) ──
async def send_mod_log(guild, embed):
    c = cfg()
    mid = c.get(str(guild.id), {}).get('mod_log_channel')
    ch = guild.get_channel(mid) if mid else None
    if ch:
        try: await ch.send(embed=embed)
        except: pass

def xp_for_level(n): return int(100 * (n ** 1.5))
def get_level(xp):
    n = 0
    while xp >= xp_for_level(n + 1):
        xp -= xp_for_level(n + 1); n += 1
    return n, xp



# ============================================================
# 2. TICKET VIEWS (Avec limite Max paramétrable)
# ============================================================
class TicketClosedView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Reopen", style=discord.ButtonStyle.success, custom_id="ticket_reopen", emoji="🔓")
    async def reopen(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # On recrée un embed pour annoncer la réouverture
        embed = discord.Embed(
            title="🔓 Ticket Réouvert", 
            description=f"Le ticket a été réouvert par {interaction.user.mention}.", 
            color=discord.Color.green()
        )
        
        # On renvoie le message AVEC les boutons du ticket actif (Claim / Close)
        await interaction.channel.send(embed=embed, view=TicketActiveView())
        
        # On supprime l'ancien message de fermeture
        await interaction.message.delete()

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="ticket_delete", emoji="🗑️")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🗑️ Suppression dans 5 secondes...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

class TicketActiveView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, custom_id="ticket_claim", emoji="🎟️")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        # --- VÉRIFICATION DE LA PERMISSION ---
        # On appelle la fonction is_staff que tu as définie tout en haut
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Vous n'avez pas la permission de réclamer ce ticket.", 
                ephemeral=True
            )
        
        # Si le code passe ici, c'est que l'utilisateur est bien Staff
        await interaction.response.send_message(f"✅ Pris en charge par {interaction.user.mention}")
        button.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="ticket_close", emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # --- VÉRIFICATION DE LA PERMISSION ---
        # On appelle la fonction is_staff que tu as définie tout en haut
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Vous n'avez pas la permission de fermer ce ticket.", 
                ephemeral=True
            )

        # Si le code passe ici, c'est que l'utilisateur est bien Staff
        await interaction.response.defer()
        embed = discord.Embed(title="🔒 Ticket Fermé", description=f"Fermé par {interaction.user.mention}.", color=discord.Color.orange())
        await interaction.channel.send(embed=embed, view=TicketClosedView())
        await interaction.message.delete()

class TicketOpenerView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un Ticket 🎫", style=discord.ButtonStyle.primary, custom_id="btn_open_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        c = cfg(); gid = str(guild.id); gc = c.get(gid, {})
        
        # Récupération de la catégorie et de la limite
        cat_id = gc.get('ticket_category')
        max_tickets = gc.get('ticket_max_open', 0)  # 0 = illimité
        category = discord.utils.get(guild.categories, id=cat_id) if cat_id else None

        # 1. Obtenir le futur numéro du ticket via tes stats
        s = stats()
        if gid not in s: s[gid] = {}
        ticket_number = s[gid].get('tickets_total', 0) + 1  # Le numéro du prochain ticket

        username_format = interaction.user.name.lower()[:15]
        
        # 2. Vérifications (Anti-doublon et Limite Serveur)
        user_has_ticket = False
        open_count = 0
        for ch in guild.text_channels:
            if ch.name.startswith("ticket-"):
                open_count += 1
                # Si le nom du ticket se termine par son pseudo, il en a déjà un
                if ch.name.endswith(f"-{username_format}"):
                    user_has_ticket = True

        if user_has_ticket:
            return await interaction.response.send_message("❌ Tu as déjà un ticket ouvert.", ephemeral=True)

        if max_tickets > 0 and open_count >= max_tickets:
            return await interaction.response.send_message(f"❌ La limite de {max_tickets} ticket(s) ouvert(s) simultanément sur le serveur est atteinte.", ephemeral=True)

        # 3. Création du nom incrémenté (Ex: ticket-0001-pseudo)
        ticket_name = f"ticket-{ticket_number:04d}-{username_format}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        tc = await guild.create_text_channel(name=ticket_name, category=category, overwrites=overwrites)
        await interaction.response.send_message(f"✅ Ticket ouvert : {tc.mention}", ephemeral=True)
        
        # 4. Message à l'intérieur du ticket avec le numéro
        t_title = gc.get('ticket_active_title') or f"🎫 Ticket #{ticket_number:04d}"
        t_title = t_title.replace('{numero}', f"{ticket_number:04d}")
        
        t_desc = gc.get('ticket_active_desc') or f"Bienvenue {interaction.user.mention} !\nL'équipe va vous répondre bientôt."
        t_desc = t_desc.replace('{user}', interaction.user.mention)
        
        embed = discord.Embed(title=t_title, description=t_desc, color=0x0099ff)
        embed.set_footer(text=f"Créé par {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await tc.send(embed=embed, view=TicketActiveView())
        
        # 5. Sauvegarder le nouveau compteur de tickets
        s[gid]['tickets_total'] = ticket_number
        sstats(s)



# ============================================================
# 3. BOT CLASS
# ============================================================
class AdminTycoonBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.invites_tracker = {}  # {guild_id: {code: uses}}

    async def setup_hook(self):
        self.add_view(TicketOpenerView())
        self.add_view(TicketActiveView())
        self.add_view(TicketClosedView())
        await self.tree.sync()
        self.check_reminders.start()
        print("🌍 Commandes synchronisées !")

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        data = rem(); now = datetime.now(timezone.utc).timestamp(); remaining = []
        for r in data:
            if r['time'] <= now:
                ch = self.get_channel(r['channel_id'])
                if ch:
                    try:
                        user = await self.fetch_user(r['user_id'])
                        embed = discord.Embed(title="⏰ Rappel !", description=r['text'], color=0xffd700)
                        await ch.send(f"{user.mention}", embed=embed)
                    except: pass
            else: remaining.append(r)
        srem(remaining)

bot = AdminTycoonBot()

# ============================================================
# 4. INVITE TRACKER (Statistiques et Bienvenue)
# ============================================================
async def build_invite_snapshot(guild):
    """Crée un snapshot {code: uses} des invitations d'un serveur."""
    snapshot = {}
    try:
        invites = await guild.invites()
        for invite in invites:
            snapshot[invite.code] = invite.uses
        if guild.vanity_url_code:
            try:
                vanity = await guild.vanity_invite()
                snapshot['vanity'] = vanity.uses
            except: pass
    except discord.Forbidden: pass
    return snapshot

async def find_inviter(guild, old_snapshot):
    """Compare l'ancien et le nouveau snapshot pour trouver qui a invité."""
    new_snapshot = await build_invite_snapshot(guild)
    inviter = None; invite_code = None
    for code, new_uses in new_snapshot.items():
        old_uses = old_snapshot.get(code, 0)
        if new_uses > old_uses:
            invite_code = code
            try:
                invites = await guild.invites()
                for invite in invites:
                    if invite.code == code: inviter = invite.inviter; break
            except: pass
            break
    bot.invites_tracker[guild.id] = new_snapshot
    if inviter and invite_code:
        inv_data = inv(); gid = str(guild.id); uid = str(inviter.id)
        if gid not in inv_data: inv_data[gid] = {}
        if uid not in inv_data[gid]: inv_data[gid][uid] = {'count': 0, 'names': []}
        inv_data[gid][uid]['count'] += 1
        sinv(inv_data)
    return inviter, invite_code

# ============================================================
# 5. EVENTS
# ============================================================
@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"🔗 {len(synced)} commandes slash synchronisées.")
    except Exception as e:
        print(f"❌ Erreur de synchro : {e}")

    # 👈 Lancement automatique de la boucle de synchronisation des rôles ici
    if not auto_sync_roles.is_running():
        auto_sync_roles.start()
        print("🔄 Boucle automatique de synchronisation des rôles lancée (15 min).")

    if not auto_update_leaderboard.is_running():
        auto_update_leaderboard.start()
        print("🏆 Boucle Auto-Leaderboard lancée (1h).")

@bot.event
async def on_invite_create(invite): bot.invites_tracker[invite.guild.id] = await build_invite_snapshot(invite.guild)

@bot.event
async def on_invite_delete(invite): bot.invites_tracker[invite.guild.id] = await build_invite_snapshot(invite.guild)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    c = cfg(); gid = str(message.guild.id); gc = c.get(gid, {})
    uid = str(message.author.id)

    

    # 1. Stats globales
    s = stats()
    if gid not in s: s[gid] = {}
    s[gid]['messages_total'] = s[gid].get('messages_total', 0) + 1
    sstats(s)

    # 2. Automod (Mots interdits) - Unique et efficace
    banned_words = gc.get('banned_words', [])
    if banned_words:
        # Regex pour matcher les mots entiers (\b) et ignorer la casse
        content_lower = message.content.lower()
        if any(re.search(r'\b' + re.escape(w.lower()) + r'\b', content_lower) for w in banned_words):
            try:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, message supprimé (mot interdit).", delete_after=5)
                return # Arrête l'exécution ici
            except: pass

    # --- NOUVEAU : 3. Anti-Pub Intelligent (Liens Discord) ---
    match = re.search(r'(?:discord\.gg/|discord\.com/invite/)([a-zA-Z0-9-]+)', message.content, re.IGNORECASE)
    if match:
        code = match.group(1) # Récupère juste le code (ex: "X9a2B")
        
        # On vérifie si ce code appartient à CE serveur
        tracked_invites = bot.invites_tracker.get(message.guild.id, {})
        is_own_invite = (code in tracked_invites) or (code == message.guild.vanity_url_code)
        
        # Si c'est une pub pour un AUTRE serveur ET que ce n'est pas un staff
        if not is_own_invite and not is_staff(message.author) and not message.author.guild_permissions.administrator:
            try:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, la publicité pour d'autres serveurs est strictement interdite !", delete_after=8)
                
                # Envoi d'une alerte dans les logs
                embed_pub = discord.Embed(title="🚨 Tentative de Publicité", description=f"{message.author.mention} a essayé d'envoyer un lien d'invitation externe.", color=discord.Color.red(), timestamp=discord.utils.utcnow())
                embed_pub.add_field(name="Salon", value=message.channel.mention)
                embed_pub.add_field(name="Lien", value=message.content[:1000], inline=False)
                await send_mod_log(message.guild, embed_pub)
                return # Arrête l'exécution
            except: pass

    # ── Système de Suggestions ──
    if message.channel.id == gc.get('suggestion_channel'):
        # On ignore les messages du bot (sinon il supprimerait ses propres messages en boucle)
        if message.author == bot.user:
            return
            
        # 1. Traitement de la suggestion du joueur
        embed = discord.Embed(
            title=f"💡 Suggestion de {message.author.display_name}", 
            description=f"{message.content}\n\n**Statut :** En attente de vote\n\nRéagissez avec ✅ et ❌ !", 
            color=0x5865f2,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.set_footer(text="Admin-Tycoon Suggestions")
        
        await message.delete() # On supprime le message brut du joueur
        msg = await message.channel.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        await msg.create_thread(name=f"Discussion : {message.content[:30]}...")

        # 2. Rafraîchissement des règles (Suppression de l'ancien + Envoi du nouveau)
        old_rules_id = gc.get('suggestion_rules_id')
        if old_rules_id:
            try:
                old_msg = await message.channel.fetch_message(old_rules_id)
                await old_msg.delete()
            except: 
                pass # Si le message a déjà été supprimé manuellement, on ignore
            
        s_title = gc.get('sugg_panel_title') or "💡 Salon de Suggestions — Admin-Tycoon"
        s_desc = gc.get('sugg_panel_desc') or "Bienvenue dans le salon des suggestions de **Admin-Tycoon** !\n\nTapez simplement votre idée dans ce salon.\nLe bot la transformera automatiquement en suggestion officielle.\n\n**Directives :**\n• Soyez clair et précis.\n• Une seule idée par message.\n• Soyez constructifs.\n\n*Un fil de discussion sera créé sous chaque suggestion !*"
        
        new_rules_embed = discord.Embed(title=s_title, description=s_desc, color=0xffcc00)

        new_rules_embed.set_footer(text="Admin-Tycoon — Système automatique")
        new_msg = await message.channel.send(embed=new_rules_embed)
        
        # Sauvegarde du nouvel ID dans la base de données
        c[gid]['suggestion_rules_id'] = new_msg.id
        scfg(c)
        return

    # 4. Système de Niveaux (avec exclusion de salons et commandes)
    excluded = gc.get('excluded_level_channels', [])
    
    # On vérifie que le message n'est pas une commande (commence par !, /, ?, -)
    is_command = message.content.startswith(('!', '/', '?', '-'))
    
    # Si le salon n'est pas exclu ET que ce n'est pas une commande, on donne l'XP
    if message.channel.id not in excluded and not is_command:
        levels = lvl()
        if gid not in levels: levels[gid] = {}
        if uid not in levels[gid]: levels[gid][uid] = {'xp': 0, 'total_xp': 0, 'messages': 0}
        
        gain = random.randint(15, 25)
        levels[gid][uid]['total_xp'] += gain
        levels[gid][uid]['messages'] = levels[gid][uid].get('messages', 0) + 1
        
        old_lvl, _ = get_level(levels[gid][uid]['total_xp'] - gain)
        new_lvl, _ = get_level(levels[gid][uid]['total_xp'])
        
        if new_lvl > old_lvl:
            lvl_ch_id = gc.get('level_channel')
            lvl_ch = message.guild.get_channel(lvl_ch_id) if lvl_ch_id else message.channel
            embed = discord.Embed(description=f"🎉 {message.author.mention} vient d'atteindre le **niveau {new_lvl}** !", color=0xffd700)
            await lvl_ch.send(embed=embed)
            reward_id = gc.get('level_roles', {}).get(str(new_lvl))
            if reward_id:
                role = message.guild.get_role(reward_id)
                if role: await message.author.add_roles(role)
        
        slvl(levels)

    if gc.get('anti_spam'):
        if not hasattr(bot, '_spam_tracker'): bot._spam_tracker = {}
        key = f"{gid}_{uid}"; now = datetime.now(timezone.utc).timestamp()
        if key not in bot._spam_tracker: bot._spam_tracker[key] = []
        bot._spam_tracker[key] = [t for t in bot._spam_tracker[key] if now - t < 5]
        bot._spam_tracker[key].append(now)
        if len(bot._spam_tracker[key]) >= 5:
            try:
                await message.author.timeout(timedelta(minutes=1), reason="Anti-spam")
                m = await message.channel.send(f"⚠️ {message.author.mention} mute 1 minute pour spam.")
                await asyncio.sleep(10); await m.delete()
            except: pass

    

    await bot.process_commands(message)

async def _send_welcome(member, inviter, invite_code, gc):
    wid = gc.get('welcome_channel')
    ch = member.guild.get_channel(wid) if wid else None
    if not ch: return
    
    hc = sum(1 for m in member.guild.members if not m.bot)
    
    # --- NOUVEAUTÉ : On récupère le nombre d'invitations de l'inviteur ---
    inviter_invites = 0
    if inviter:
        inv_data = inv()
        # On va chercher dans invites.json le score actuel de l'inviteur
        inviter_invites = inv_data.get(str(member.guild.id), {}).get(str(inviter.id), {}).get('count', 0)
    # ---------------------------------------------------------------------

    welcome_template = gc.get('welcome_message', '')
    
    if welcome_template:
        desc = welcome_template \
            .replace('{user}', member.mention) \
            .replace('{username}', member.display_name) \
            .replace('{server}', member.guild.name) \
            .replace('{count}', str(hc)) \
            .replace('{inviter}', inviter.mention if inviter else 'Inconnu') \
            .replace('{inviter_invites}', str(inviter_invites)) # <-- VARIABLE AJOUTÉE ICI
            
        raw_color = gc.get('welcome_color', '00bfff').lstrip('#') or '00bfff'
        try:
            embed_color = int(raw_color, 16)
        except ValueError:
            embed_color = 0x00bfff
        embed = discord.Embed(title=gc.get('welcome_title', '⚡ Bienvenue !'), description=desc, color=embed_color)
    else:
        embed = discord.Embed(title="⚡ Bienvenue !", description=f"Salut {member.mention} ! Tu es notre **{hc}ème** membre ! 🎉", color=0x00bfff)
        
    embed.set_thumbnail(url=member.display_avatar.url)
    
    # Affichage du petit footer si l'option est cochée sur le dashboard
    if inviter and gc.get('show_inviter', True):
        embed.add_field(name="Invité par", value=f"{inviter.mention} (qui possède {inviter_invites} invitations)")
        
    embed.set_footer(text=member.guild.name, icon_url=member.guild.icon.url if member.guild.icon else None)
    await ch.send(embed=embed)



@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    
    # Prépare l'embed de base
    embed = discord.Embed(title="🗑️ Message Supprimé", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_author(name=message.author, icon_url=message.author.display_avatar.url)
    embed.add_field(name="Salon", value=message.channel.mention, inline=True)
    
    # 👻 Détection de Ghost Ping (S'il a mentionné quelqu'un d'autre que lui-même ou un bot)
    if message.mentions:
        mentions_str = " ".join([m.mention for m in message.mentions if not m.bot and m != message.author])
        if mentions_str:
            embed.title = "👻 Ghost Ping Détecté !"
            embed.color = discord.Color.dark_orange()
            embed.add_field(name="Mentions visées", value=mentions_str, inline=True)

    content = message.content or "*(Message sans texte, potentiellement une image/embed)*"
    if len(content) > 1024: content = content[:1020] + "..."
    embed.add_field(name="Contenu", value=content, inline=False)
    
    await send_mod_log(message.guild, embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild: return
    # On ignore si le texte est le même (souvent causé par l'apparition de l'aperçu d'un lien)
    if before.content == after.content: return 
    
    embed = discord.Embed(title="✏️ Message Modifié", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    embed.set_author(name=before.author, icon_url=before.author.display_avatar.url)
    embed.add_field(name="Salon", value=before.channel.mention, inline=False)
    
    b_content = before.content if len(before.content) < 1000 else before.content[:1000] + "..."
    a_content = after.content if len(after.content) < 1000 else after.content[:1000] + "..."
    
    embed.add_field(name="Avant", value=b_content or "*Vide*", inline=False)
    embed.add_field(name="Après", value=a_content or "*Vide*", inline=False)
    
    # On ajoute un bouton pour sauter directement au message modifié !
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Aller au message", url=after.jump_url))
    
    c = cfg(); mid = c.get(str(before.guild.id), {}).get('mod_log_channel')
    ch = before.guild.get_channel(mid) if mid else None
    if ch:
        try: await ch.send(embed=embed, view=view)
        except: pass


@bot.event
async def on_member_join(member):
    c = cfg(); gid = str(member.guild.id); gc = c.get(gid, {})
    
    # 1. Condition: Ignorer les bots
    if member.bot and gc.get('ignore_bots_welcome', True): 
        return

    # 2. ANTI-ALT : Vérification de l'âge du compte
    min_days = gc.get('min_account_age', 0)
    account_age = (datetime.now(timezone.utc) - member.created_at).days
    is_valid_invite = account_age >= min_days

    # 3. Statistiques join
    s = stats()
    if gid not in s: s[gid] = {}
    s[gid]['members_joined'] = s[gid].get('members_joined', 0) + 1
    sstats(s)

    # 4. Autorole
    ar = gc.get('auto_role')
    if ar:
        role = member.guild.get_role(ar)
        if role:
            try: await member.add_roles(role)
            except: pass

    # 5. Gestion des invitations
    old_snapshot = bot.invites_tracker.get(member.guild.id, {})
    inviter, invite_code = await find_inviter(member.guild, old_snapshot)

    # Sauvegarde du membre pour le suivi
    if inviter:
        jm = joined_members()
        if gid not in jm: jm[gid] = {}
        # On sauvegarde TOUT (qui a invité, si c'est valide, ET l'heure d'arrivée)
        jm[gid][str(member.id)] = {
            'inviter_id': str(inviter.id), 
            'is_valid': is_valid_invite,
            'join_time': datetime.now(timezone.utc).timestamp() # ⏳ Chronomètre lancé !
        }
        sjoined(jm)
        
        # Si c'est un FAUX COMPTE (trop récent), on lui retire tout de suite 
        # le point que la fonction find_inviter vient de lui donner par défaut.
        if not is_valid_invite:
            inv_data = inv()
            if gid in inv_data and str(inviter.id) in inv_data[gid]:
                inv_data[gid][str(inviter.id)]['count'] = max(0, inv_data[gid][str(inviter.id)]['count'] - 1)
                sinv(inv_data)

    # 6. Mode Sapphire (Attente règles)
    if gc.get('welcome_after_rules'):
        pending = _load('pending_welcome.json', {})
        if gid not in pending: pending[gid] = {}
        pending[gid][str(member.id)] = {
            'inviter_id': str(inviter.id) if inviter else None,
            'invite_code': invite_code
        }
        _save('pending_welcome.json', pending)
        return

    await _send_welcome(member, inviter, invite_code, gc)

@bot.event
async def on_member_remove(member):
    c = cfg()
    gid = str(member.guild.id)
    gc = c.get(gid, {})
    
    # 1. ANTI-LEAVER : Retirer l'invitation si le membre avait été compté
    jm = joined_members()
    data = jm.get(gid, {}).get(str(member.id))
    
    if data:
        # On vérifie si l'invitation était valide à la base
        if isinstance(data, dict) and data.get('is_valid'):
            join_time = data.get('join_time', 0)
            now = datetime.now(timezone.utc).timestamp()
            
            # S'il a quitté en moins de 24h (86400 secondes), on retire le point !
            # Sinon, il est resté + de 24h, donc le point est gagné définitivement.
            if (now - join_time) <= 86400:
                inviter_id = data.get('inviter_id')
                inv_data = inv()
                if gid in inv_data and inviter_id in inv_data[gid]:
                    inv_data[gid][inviter_id]['count'] = max(0, inv_data[gid][inviter_id]['count'] - 1)
                    sinv(inv_data)
                
        # On supprime la trace du membre qui est parti pour garder la BDD propre
        if str(member.id) in jm.get(gid, {}):
            del jm[gid][str(member.id)]
            sjoined(jm)

    # 2. Log départ
    s = stats()
    if gid not in s: s[gid] = {}
    s[gid]['members_left'] = s[gid].get('members_left', 0) + 1
    sstats(s)
    lid = gc.get('leave_channel')
    ch = member.guild.get_channel(lid) if lid else None
    if ch:
        embed = discord.Embed(description=f"👋 **{member}** a quitté le serveur. Il reste {member.guild.member_count} membres.", color=0xff6b6b)
        await ch.send(embed=embed)


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    if not member: return
    c = cfg(); data = c.get(str(payload.guild_id), {})

    # Validation des Règles
    if payload.message_id == data.get('rules_message_id') and str(payload.emoji) == '✅':
        role = guild.get_role(data.get('rules_role_id'))
        if role and member:
            try: await member.add_roles(role)
            except: pass
            
        # Si le Mode Sapphire est activé, on envoie le message de bienvenue maintenant
        if data.get('welcome_after_rules'):
            pending = _load('pending_welcome.json', {})
            gid = str(guild.id); uid = str(member.id)
            entry = pending.get(gid, {}).pop(uid, None)
            _save('pending_welcome.json', pending)
            if entry:
                inviter = None
                if entry.get('inviter_id'):
                    try: inviter = await bot.fetch_user(int(entry['inviter_id']))
                    except: pass
                await _send_welcome(member, inviter, entry.get('invite_code'), data)
        return

    # Reaction roles
    rr = data.get('reaction_roles', {})
    emoji_str = str(payload.emoji)
    key = f"{payload.message_id}_{emoji_str}"
    
    # Gestion des émojis customisés
    if key not in rr and hasattr(payload.emoji, 'name'):
        alt = f"{payload.message_id}_{payload.emoji.name}"
        if alt in rr: key = alt
        
    if key in rr:
        role = guild.get_role(rr[key])
        if role and member:
            try: await member.add_roles(role)
            except: pass

@bot.event
async def on_raw_reaction_remove(payload):
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    if not member: return
    c = cfg(); data = c.get(str(payload.guild_id), {})
    
    if payload.message_id == data.get('rules_message_id') and str(payload.emoji) == '✅':
        role = guild.get_role(data.get('rules_role_id'))
        if role and member:
            try: await member.remove_roles(role)
            except: pass
        return
        
    rr = data.get('reaction_roles', {})
    emoji_str = str(payload.emoji)
    key = f"{payload.message_id}_{emoji_str}"
    if key not in rr and hasattr(payload.emoji, 'name'):
        alt = f"{payload.message_id}_{payload.emoji.name}"
        if alt in rr: key = alt
    if key in rr:
        role = guild.get_role(rr[key])
        if role and member:
            try: await member.remove_roles(role)
            except: pass

# ============================================================
# 6. SETUP & CONFIGURATION (Commandes Slash)
# ============================================================
@bot.tree.command(name="sync", description="Synchronise tes rôles Discord (Niveau, VIP, Richesse)")
async def sync_roles(interaction: discord.Interaction):
    await interaction.response.defer() 

    # 🔐 On reproduit EXACTEMENT le même hachage sécurisé
    secret_salt = "Tycoon_SecretKey_2026!Admintycoongame202645BonChanceqsdqsdqsd,;s:sdfsdfscfgretg"
    texte_a_hacher = secret_salt + str(interaction.user.id)
    hashed_uid = hashlib.sha256(texte_a_hacher.encode('utf-8')).hexdigest()
    
    try:
        discord_id_str = str(interaction.user.id)
        player_response = supabase_game.table('players').select('username, game_state').eq('discord_id', discord_id_str).execute()
        
        if not player_response.data:
            await interaction.followup.send("❌ Aucun compte trouvé ! Va sur le jeu et clique sur **🔗 Rôles Discord** d'abord.")
            return
            
        player_data = player_response.data[0]
        username = player_data.get('username')
        active_state = player_data.get('game_state', {})
        
        # Petite fonction interne pour tout lire d'un coup (Niveau, Argent, VIP)
        def extract_stats(state):
            if isinstance(state, str):
                try: state = json.loads(state)
                except: return 1, 0.0, False
            if isinstance(state, dict):
                lvl = int(state.get('level', 1))
                money = float(state.get('money', 0.0))
                # Vérifie la présence d'une clé 'vip' ou 'is_vip' à true
                is_vip = state.get('vip', False) or state.get('is_vip', False)
                return lvl, money, is_vip
            return 1, 0.0, False

        # Variables pour stocker le maximum de toutes les sauvegardes
        max_level = 1
        max_money = 0.0
        has_vip = False

        # 1. On lit la partie en cours (table players)
        lvl, money, is_vip = extract_stats(active_state)
        max_level = max(max_level, lvl)
        max_money = max(max_money, money)
        has_vip = has_vip or is_vip
        
        # 2. On fouille les autres sauvegardes (table saves)
        if username:
            saves_response = supabase_game.table('saves').select('game_state').eq('username', username).execute()
            for row in saves_response.data:
                save_state = row.get('game_state', {})
                lvl, money, is_vip = extract_stats(save_state)
                max_level = max(max_level, lvl)
                max_money = max(max_money, money)
                has_vip = has_vip or is_vip
                    
        # 3. On distribue les rôles de Niveau ET les rôles Spéciaux !
        await update_member_level_role(interaction.user, max_level)
        await update_member_special_roles(interaction.user, has_vip, max_money)
        
        # 4. Message de succès personnalisé
        msg = f"✅ Rôles synchronisés ! Niveau max : **Niveau {max_level}**."
        if has_vip:
            msg += "\n💎 **Statut VIP détecté !** Rôle attribué."
        if max_money >= 1000000000:
            msg += "\n💰 **Félicitations, tu es Milliardaire !** Rôle Riche attribué."
            
        await interaction.followup.send(msg)
        
    except Exception as e:
        print(f"❌ Erreur lors de la commande /sync : {e}")
        await interaction.followup.send(f"⚠️ Une erreur technique a empêché la synchronisation : `{e}`")

@bot.tree.command(name="config-regles", description="Génère l'embed des règles.")
@app_commands.default_permissions(administrator=True)
async def setup_rules(interaction: discord.Interaction, salon: discord.TextChannel, role: discord.Role):
    c = cfg(); gid = str(interaction.guild.id); gc = c.get(gid, {})
    rules_text = gc.get('rules_text', f"Veuillez lire et accepter les règles.\n\n✅ Réagissez pour obtenir le rôle {role.mention}.")
    embed = discord.Embed(title=gc.get('rules_title', '📜 RÈGLES'), description=rules_text, color=0x0099ff)
    await interaction.response.send_message("✅ Envoyé.", ephemeral=True)
    msg = await salon.send(embed=embed)
    await msg.add_reaction("✅")
    if gid not in c: c[gid] = {}
    c[gid].update({'rules_message_id': msg.id, 'rules_role_id': role.id})
    scfg(c)

@bot.tree.command(name="config-leaderboard", description="Configure le classement mondial automatique du jeu")
@app_commands.default_permissions(administrator=True)
@app_commands.choices(
    critere=[
        app_commands.Choice(name="💰 Classer par Argent", value="money"),
        app_commands.Choice(name="⭐ Classer par Niveau (XP)", value="level")
    ],
    frequence=[
        app_commands.Choice(name="Toutes les 2 minutes", value=0.033333),
        app_commands.Choice(name="Toutes les 30 minutes", value=0.5),
        app_commands.Choice(name="Toutes les heures", value=1.0),
        app_commands.Choice(name="Toutes les 2 heures", value=2.0),
        app_commands.Choice(name="Toutes les 6 heures", value=6.0),
        app_commands.Choice(name="Toutes les 12 heures", value=12.0),
        app_commands.Choice(name="Une fois par jour (24h)", value=24.0)
    ]
)
# 🟢 On utilise "str" et "float", beaucoup plus simple !
async def config_lb_cmd(interaction: discord.Interaction, salon: discord.TextChannel, critere: str, frequence: float):
    await interaction.response.defer(ephemeral=True)
    
    guild_id = str(interaction.guild.id)
    c = cfg()
    if guild_id not in c: c[guild_id] = {}
        
    c[guild_id]['live_lb_channel'] = salon.id
    c[guild_id]['lb_sort_by'] = critere
    
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(c, f, indent=4)
        
    if auto_update_leaderboard.is_running():
        auto_update_leaderboard.change_interval(hours=frequence)
    else:
        auto_update_leaderboard.start()
        auto_update_leaderboard.change_interval(hours=frequence)

    await interaction.followup.send(f"✅ **Leaderboard configuré !**\n📍 Salon : {salon.mention}\n📊 Trié par : **{critere}**")

@bot.tree.command(name="config-exclure-salon", description="Exclure un salon du système d'XP.")
@app_commands.default_permissions(administrator=True)
async def exclude_channel(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    if 'excluded_level_channels' not in c[gid]: c[gid]['excluded_level_channels'] = []
    
    if salon.id not in c[gid]['excluded_level_channels']:
        c[gid]['excluded_level_channels'].append(salon.id)
        scfg(c)
        await interaction.response.send_message(f"✅ {salon.mention} est maintenant exclu du système d'XP.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {salon.mention} est déjà exclu.", ephemeral=True)

@bot.tree.command(name="config-inclure-salon", description="Ré-inclure un salon dans le système d'XP.")
@app_commands.default_permissions(administrator=True)
async def include_channel(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    if 'excluded_level_channels' in c[gid] and salon.id in c[gid]['excluded_level_channels']:
        c[gid]['excluded_level_channels'].remove(salon.id)
        scfg(c)
        await interaction.response.send_message(f"✅ {salon.mention} est de nouveau inclus dans le système d'XP.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {salon.mention} n'était pas exclu.", ephemeral=True)

@bot.tree.command(name="config-tickets", description="Installe le système de tickets.")
@app_commands.default_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction, categorie: discord.CategoryChannel, salon: discord.TextChannel = None):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['ticket_category'] = categorie.id; scfg(c)
    target = salon or interaction.channel
    
    t_title = c[gid].get('ticket_panel_title') or "🎫 Support"
    t_desc = c[gid].get('ticket_panel_desc') or "Clique sur le bouton pour ouvrir un ticket."
    
    embed = discord.Embed(title=t_title, description=t_desc, color=0x0099ff)
    await target.send(embed=embed, view=TicketOpenerView())
    await interaction.response.send_message(f"✅ Installé dans {target.mention}", ephemeral=True)

@bot.tree.command(name="config-bienvenue", description="Salon de bienvenue.")
@app_commands.default_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['welcome_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Bienvenue : {salon.mention}", ephemeral=True)

@bot.tree.command(name="config-depart", description="Salon de départ.")
@app_commands.default_permissions(administrator=True)
async def set_leave(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['leave_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Départ : {salon.mention}", ephemeral=True)

@bot.tree.command(name="config-logs", description="Salon des logs globaux.")
@app_commands.default_permissions(administrator=True)
async def set_logs(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['log_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Logs : {salon.mention}", ephemeral=True)

@bot.tree.command(name="config-modlog", description="Salon des logs de modération (ban/kick/warn...).")
@app_commands.default_permissions(administrator=True)
async def set_modlog(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['mod_log_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Logs modération : {salon.mention}", ephemeral=True)

@bot.tree.command(name="config-mot-interdit", description="Gérer la liste des mots interdits (Automod).")
@app_commands.choices(action=[
    app_commands.Choice(name="➕ Ajouter un mot", value="add"),
    app_commands.Choice(name="➖ Retirer un mot", value="remove"),
    app_commands.Choice(name="📜 Voir la liste", value="list"),
    app_commands.Choice(name="🚨 Ajouter la liste par défaut (Insultes FR)", value="default")
])
@app_commands.default_permissions(administrator=True)
async def config_mot_interdit(interaction: discord.Interaction, action: app_commands.Choice[str], mot: str = None):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    if 'banned_words' not in c[gid]: c[gid]['banned_words'] = []
    
    words = c[gid]['banned_words']
    
    # Action : Liste par défaut
    if action.value == "default":
        mots_base = [
            "putain", "merde", "connard", "connasse", "salope", "salop", "enculé", "encule", 
            "batard", "bâtard", "fdp", "tg", "ntm", "bite", "couille", "pute", 
            "pd", "trouduc", "bouffon", "chier", "conne"
        ]
        ajoutes = 0
        for m in mots_base:
            if m not in words:
                words.append(m)
                ajoutes += 1
        scfg(c)
        return await interaction.response.send_message(f"✅ **{ajoutes} mots par défaut** ont été ajoutés à la liste d'interdiction du serveur.", ephemeral=True)

    # Action : Voir la liste
    elif action.value == "list":
        if not words:
            return await interaction.response.send_message("ℹ️ Aucun mot interdit n'est configuré.", ephemeral=True)
        return await interaction.response.send_message(f"📜 **Mots interdits ({len(words)}) :**\n`{', '.join(words)}`", ephemeral=True)

    # Sécurité pour Add/Remove
    if not mot:
        return await interaction.response.send_message("❌ Tu dois préciser le champ `mot` pour cette action !", ephemeral=True)
    
    mot = mot.lower().strip()

    # Action : Ajouter
    if action.value == "add":
        if mot in words:
            return await interaction.response.send_message(f"⚠️ Le mot `{mot}` est déjà interdit.", ephemeral=True)
        words.append(mot)
        scfg(c)
        await interaction.response.send_message(f"✅ Le mot `{mot}` a été ajouté.", ephemeral=True)
        
    # Action : Retirer
    elif action.value == "remove":
        if mot in words:
            words.remove(mot)
            scfg(c)
            await interaction.response.send_message(f"✅ Le mot `{mot}` a été retiré.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Le mot `{mot}` n'est pas dans la liste.", ephemeral=True)

@bot.tree.command(name="config-suggestions", description="Définit le salon des suggestions et envoie le guide.")
@app_commands.default_permissions(administrator=True)
async def config_suggestions(interaction: discord.Interaction, salon: discord.TextChannel):
    # 1. Sauvegarde du salon
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['suggestion_channel'] = salon.id
    
    s_title = c[gid].get('sugg_panel_title') or "💡 Salon de Suggestions — Admin-Tycoon"
    s_desc = c[gid].get('sugg_panel_desc') or "Bienvenue dans le salon des suggestions de **Admin-Tycoon** !\n\nTapez simplement votre idée dans ce salon.\nLe bot la transformera automatiquement en suggestion officielle.\n\n**Directives :**\n• Soyez clair et précis.\n• Une seule idée par message.\n• Soyez constructifs.\n\n*Un fil de discussion sera créé sous chaque suggestion !*"

    embed = discord.Embed(title=s_title, description=s_desc, color=0xffcc00)
    embed.set_footer(text="Admin-Tycoon — Système automatique")
    
    # 3. Envoi et sauvegarde de l'ID du message
    msg = await salon.send(embed=embed)
    c[gid]['suggestion_rules_id'] = msg.id  # On sauvegarde l'ID ici
    scfg(c)
    
    await interaction.response.send_message(f"✅ Salon {salon.mention} configuré !", ephemeral=True)



    
@bot.tree.command(name="config-levelup", description="Salon des annonces de level up.")
@app_commands.default_permissions(administrator=True)
async def set_levelchan(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['level_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Level-up : {salon.mention}", ephemeral=True)

@bot.tree.command(name="config-autorole", description="Rôle automatique à l'arrivée.")
@app_commands.default_permissions(administrator=True)
async def set_autorole(interaction: discord.Interaction, role: discord.Role):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['auto_role'] = role.id; scfg(c)
    await interaction.response.send_message(f"✅ Auto-rôle : {role.mention}", ephemeral=True)

@bot.tree.command(name="config-levelrole", description="Attribue un rôle à un niveau précis.")
@app_commands.default_permissions(administrator=True)
async def set_levelrole(interaction: discord.Interaction, niveau: int, role: discord.Role):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    if 'level_roles' not in c[gid]: c[gid]['level_roles'] = {}
    c[gid]['level_roles'][str(niveau)] = role.id; scfg(c)
    await interaction.response.send_message(f"✅ Niveau **{niveau}** → {role.mention}", ephemeral=True)

@bot.tree.command(name="config-maxtickets", description="Limite le nombre de tickets ouverts simultanément (0 = illimité).")
@app_commands.default_permissions(administrator=True)
async def set_maxtickets(interaction: discord.Interaction, max: int):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['ticket_max_open'] = max; scfg(c)
    msg = f"✅ Max tickets : **{max}**" if max > 0 else "✅ Limite de tickets désactivée."
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="config-antispam", description="Active/désactive l'anti-spam.")
@app_commands.default_permissions(administrator=True)
async def antispam(interaction: discord.Interaction):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['anti_spam'] = not c[gid].get('anti_spam', False); scfg(c)
    await interaction.response.send_message(f"🛡️ Anti-spam {'activé' if c[gid]['anti_spam'] else 'désactivé'}.", ephemeral=True)


# ============================================================
# 7. MODÉRATION
# ============================================================
@bot.tree.command(name="ban", description="Bannit un membre.")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    if membre.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Impossible.", ephemeral=True)
    try:
        await membre.ban(reason=raison)
        embed = discord.Embed(title="🔨 Ban", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Membre", value=f"{membre} ({membre.id})")
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await send_mod_log(interaction.guild, embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)

@bot.tree.command(name="deban", description="Révoquer le bannissement d'un utilisateur.")
@app_commands.default_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ {user} débanni.", ephemeral=True)
    except:
        await interaction.response.send_message("❌ Introuvable.", ephemeral=True)

@bot.tree.command(name="expulser", description="Expulser un membre.")
@app_commands.default_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    if membre.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Impossible.", ephemeral=True)
    try:
        await membre.kick(reason=raison)
        embed = discord.Embed(title="👢 Kick", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Membre", value=f"{membre}"); embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await send_mod_log(interaction.guild, embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)

@bot.tree.command(name="mute", description="Timeout un membre.")
@app_commands.default_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, membre: discord.Member, duree: int = 10, raison: str = "Aucune raison"):
    if membre.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Impossible.", ephemeral=True)
    try:
        await membre.timeout(timedelta(minutes=min(duree, 40320)), reason=raison)
        embed = discord.Embed(title="🔇 Mute", color=discord.Color.yellow(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Membre", value=membre.mention); embed.add_field(name="Durée", value=f"{duree}min")
        embed.add_field(name="Modérateur", value=interaction.user.mention); embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await send_mod_log(interaction.guild, embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)

@bot.tree.command(name="demute", description="Retirer la réduction au silence d'un membre.")
@app_commands.default_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, membre: discord.Member):
    await membre.timeout(None)
    await interaction.response.send_message(f"✅ {membre.mention} démute.", ephemeral=True)

@bot.tree.command(name="avertir", description="Avertir un membre.")
@app_commands.default_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, membre: discord.Member, raison: str):
    w = wrn(); gid = str(interaction.guild.id); uid = str(membre.id)
    if gid not in w: w[gid] = {}
    if uid not in w[gid]: w[gid][uid] = []
    w[gid][uid].append({'raison': raison, 'mod': str(interaction.user), 'time': str(discord.utils.utcnow())})
    swrn(w); total = len(w[gid][uid])
    
    embed = discord.Embed(title="⚠️ Avertissement", color=discord.Color.yellow(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Membre", value=membre.mention); embed.add_field(name="Total Warns", value=f"**{total}**")
    embed.add_field(name="Raison", value=raison, inline=False); embed.add_field(name="Modérateur", value=interaction.user.mention)
    
    await interaction.response.send_message(embed=embed)
    await send_mod_log(interaction.guild, embed)

@bot.tree.command(name="infractions-retirer", description="Retirer la dernière infraction d'un membre.")
@app_commands.default_permissions(moderate_members=True)
async def unwarn(interaction: discord.Interaction, membre: discord.Member):
    w = wrn(); gid = str(interaction.guild.id); uid = str(membre.id)
    user_warns = w.get(gid, {}).get(uid, [])
    
    if not user_warns:
        return await interaction.response.send_message(f"✅ {membre.mention} n'a aucun warn.", ephemeral=True)
        
    removed = w[gid][uid].pop()
    swrn(w)
    await interaction.response.send_message(f"✅ Dernier warn de {membre.mention} retiré.\n*Raison retirée : {removed['raison']}*", ephemeral=True)

@bot.tree.command(name="infractions-lister", description="Afficher les infractions d'un membre.")
@app_commands.default_permissions(moderate_members=True)
async def warns_cmd(interaction: discord.Interaction, membre: discord.Member):
    w = wrn(); user_warns = w.get(str(interaction.guild.id), {}).get(str(membre.id), [])
    if not user_warns:
        return await interaction.response.send_message(f"✅ Aucune infraction pour {membre.mention}.", ephemeral=True)
        
    embed = discord.Embed(title=f"⚠️ Infractions de {membre}", color=discord.Color.orange())
    embed.set_thumbnail(url=membre.display_avatar.url)
    for i, ww in enumerate(user_warns, 1):
        embed.add_field(name=f"#{i} — par {ww['mod']}", value=ww['raison'], inline=False)
    embed.set_footer(text=f"Total : {len(user_warns)}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="infractions-reinitialiser", description="Réinitialiser les infractions d'un membre.")
@app_commands.default_permissions(administrator=True)
async def clearwarns(interaction: discord.Interaction, membre: discord.Member):
    w = wrn(); gid = str(interaction.guild.id); uid = str(membre.id)
    if gid in w: w[gid][uid] = []
    swrn(w)
    await interaction.response.send_message(f"✅ Warns effacés pour {membre.mention}.", ephemeral=True)

@bot.tree.command(name="purge", description="Supprime des messages (1-100). Le message s'auto-supprime.")
@app_commands.default_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, nombre: int):
    if not 1 <= nombre <= 100:
        return await interaction.response.send_message("❌ Entre 1 et 100.", ephemeral=True)
        
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=nombre)
    
    # Message normal dans le salon qui s'efface tout seul
    msg = await interaction.channel.send(f"🗑️ {len(deleted)} messages supprimés par {interaction.user.mention}.")
    await interaction.delete_original_response()
    await asyncio.sleep(5)
    try: await msg.delete()
    except: pass

@bot.tree.command(name="slowmode", description="Définit le slowmode du salon.")
@app_commands.default_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, secondes: int):
    await interaction.channel.edit(slowmode_delay=secondes)
    await interaction.response.send_message(f"🐢 Slowmode défini sur : **{secondes}s**", ephemeral=True)

@bot.tree.command(name="lock", description="Verrouille ce salon.")
@app_commands.default_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Salon verrouillé.")

@bot.tree.command(name="unlock", description="Déverrouille ce salon.")
@app_commands.default_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Salon déverrouillé.")

# ============================================================
# 8. INVITATIONS
# ============================================================
@bot.tree.command(name="invitations-reinitialiser", description="Réinitialise les invitations d'un membre à 0.")
@app_commands.default_permissions(administrator=True)
async def resetinvites(interaction: discord.Interaction, membre: discord.Member):
    inv_data = inv()
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    
    # Vérifie si le serveur et le membre existent dans la base de données
    if gid in inv_data and uid in inv_data[gid]:
        # On remet le compteur à 0
        inv_data[gid][uid]['count'] = 0
        sinv(inv_data)
        await interaction.response.send_message(f"✅ Les invitations de {membre.mention} ont été réinitialisées à **0**.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ {membre.mention} n'a aucune invitation enregistrée dans la base de données.", ephemeral=True)

@bot.tree.command(name="invites", description="Voir les invitations d'un membre.")
async def invites_cmd(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    inv_data = inv()
    user_inv = inv_data.get(str(interaction.guild.id), {}).get(str(m.id), {})
    
    # On lit UNIQUEMENT la base de données (qui gère les réinitialisations)
    stored_count = user_inv.get('count', 0)
        
    embed = discord.Embed(title=f"📨 Invitations de {m.display_name}", color=0x5865F2)
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="Invitations Vérifiées", value=f"**{stored_count}** 🎯")
    embed.set_footer(text="Système Anti-Leave activé.")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="topinvites", description="Top des inviteurs du serveur.")
async def topinvites(interaction: discord.Interaction):
    await interaction.response.defer()
    
    # 1. On charge UNIQUEMENT la base de données
    inv_data = inv()
    gid = str(interaction.guild.id)
    server_invites = inv_data.get(gid, {})
        
    # 2. On trie du plus grand au plus petit score
    sorted_inv = sorted(server_invites.items(), key=lambda x: x[1].get('count', 0), reverse=True)
    medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    
    embed = discord.Embed(title="📨 Top Inviteurs", color=0x5865F2)
    embed.set_footer(text="Seules les invitations vérifiées sont comptées.")
    
    added = 0
    for uid, data in sorted_inv:
        count = data.get('count', 0)
        
        # On ignore ceux qui ont 0 invitation (comme ça ils disparaissent si on les réinitialise)
        if count <= 0:
            continue
            
        if added >= 10:
            break
            
        try:
            user = await bot.fetch_user(int(uid))
            embed.add_field(name=f"{medals[added]} {user.name}", value=f"**{count}** invitations", inline=False)
            added += 1
        except:
            pass
            
    if added == 0:
        embed.description = "Aucune invitation valide pour le moment."

    await interaction.followup.send(embed=embed)



# ============================================================
# 9. ÉCONOMIE
# ============================================================
def get_wallet(gid, uid):
    e = eco()
    if gid not in e: e[gid] = {}
    if uid not in e[gid]: e[gid][uid] = {'coins': 0, 'bank': 0, 'last_daily': 0, 'last_work': 0}
    return e, e[gid][uid]

@bot.tree.command(name="solde", description="Vérifie ton solde.")
async def balance(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    e, wallet = get_wallet(str(interaction.guild.id), str(m.id))
    embed = discord.Embed(title=f"💰 Solde de {m.display_name}", color=0xffd700)
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="Portefeuille", value=f"**{wallet['coins']:,}** 🪙")
    embed.add_field(name="Banque", value=f"**{wallet['bank']:,}** 🏦")
    embed.add_field(name="Total", value=f"**{wallet['coins'] + wallet['bank']:,}** 💎")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="journalier", description="Réclame ta récompense journalière.")
async def daily(interaction: discord.Interaction):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid); now = datetime.now(timezone.utc).timestamp()
    if now - wallet.get('last_daily', 0) < 86400:
        reste = 86400 - (now - wallet['last_daily']); h, m = int(reste // 3600), int((reste % 3600) // 60)
        return await interaction.response.send_message(f"⏳ Reviens dans **{h}h {m}min**.", ephemeral=True)
    amount = random.randint(100, 500)
    e[gid][uid]['coins'] += amount; e[gid][uid]['last_daily'] = now; seco(e)
    embed = discord.Embed(title="🎁 Daily !", description=f"+**{amount}** 🪙", color=0xffd700)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="travail", description="Travaille (cooldown 1h).")
async def work(interaction: discord.Interaction):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid); now = datetime.now(timezone.utc).timestamp()
    if now - wallet.get('last_work', 0) < 3600:
        return await interaction.response.send_message(f"⏳ Reviens dans **{int((3600-(now-wallet['last_work']))//60)}min**.", ephemeral=True)
    jobs = ["développeur", "streamer", "modérateur", "gamer", "trader"]
    amount = random.randint(50, 200)
    e[gid][uid]['coins'] += amount; e[gid][uid]['last_work'] = now; seco(e)
    embed = discord.Embed(title="💼 Travail !", description=f"En tant que **{random.choice(jobs)}** : +**{amount}** 🪙", color=0x00bfff)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="déposer", description="Dépose des coins à la banque.")
async def deposit(interaction: discord.Interaction, montant: int):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid)
    if montant <= 0 or montant > wallet['coins']:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
    e[gid][uid]['coins'] -= montant; e[gid][uid]['bank'] += montant; seco(e)
    await interaction.response.send_message(f"🏦 +**{montant}** 🪙 en banque.", ephemeral=True)

@bot.tree.command(name="retirer", description="Retire des coins de la banque.")
async def withdraw(interaction: discord.Interaction, montant: int):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid)
    if montant <= 0 or montant > wallet['bank']:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
    e[gid][uid]['bank'] -= montant; e[gid][uid]['coins'] += montant; seco(e)
    await interaction.response.send_message(f"💸 +**{montant}** 🪙 retirés.", ephemeral=True)

@bot.tree.command(name="parier", description="Parie tes coins (50/50).")
async def gamble(interaction: discord.Interaction, montant: int):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid)
    if montant <= 0 or montant > wallet['coins']:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
    win = random.random() > 0.5
    e[gid][uid]['coins'] += montant if win else -montant; seco(e)
    embed = discord.Embed(title="🎰 Gagné !" if win else "🎰 Perdu !", description=f"{'+'if win else '-'}**{montant}** 🪙", color=discord.Color.green() if win else discord.Color.red())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="payer", description="Donne des coins à un autre membre.")
async def give(interaction: discord.Interaction, membre: discord.Member, montant: int):
    if membre.bot or membre == interaction.user:
        return await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
    gid = str(interaction.guild.id)
    e, sender = get_wallet(gid, str(interaction.user.id))
    if montant <= 0 or montant > sender['coins']:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
    get_wallet(gid, str(membre.id))
    e[gid][str(interaction.user.id)]['coins'] -= montant
    e[gid][str(membre.id)]['coins'] += montant; seco(e)
    await interaction.response.send_message(f"✅ **{montant}** 🪙 → {membre.mention}")

@bot.tree.command(name="leaderboard", description="Top 10 économie.")
async def lb(interaction: discord.Interaction):
    e = eco(); gid = str(interaction.guild.id)
    sorted_users = sorted(e.get(gid, {}).items(), key=lambda x: x[1].get('coins', 0) + x[1].get('bank', 0), reverse=True)[:10]
    embed = discord.Embed(title="🏆 Leaderboard Économie", color=0xffd700)
    medals = ["🥇","🥈","🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, (uid, data) in enumerate(sorted_users):
        try:
            user = await bot.fetch_user(int(uid))
            embed.add_field(name=f"{medals[i]} {user.name}", value=f"{(data.get('coins',0)+data.get('bank',0)):,} 🪙", inline=False)
        except: pass
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="shop", description="Affiche la boutique du serveur.")
async def shop(interaction: discord.Interaction):
    embed = discord.Embed(title="🛒 Boutique du Serveur", description="Utilisez `/buy [article]` pour acheter un objet avec vos pièces (🪙).", color=0xffd700)
    embed.add_field(name="[1] Couleur Rouge 🔴", value="Prix: **10,000** 🪙\n*Donne une couleur rouge à ton pseudo.*", inline=False)
    embed.add_field(name="[2] Couleur Bleue 🔵", value="Prix: **10,000** 🪙\n*Donne une couleur bleue à ton pseudo.*", inline=False)
    embed.add_field(name="[3] Rôle Riche 💎", value="Prix: **50,000** 🪙\n*Montre à tout le monde ta richesse légendaire.*", inline=False)
    embed.add_field(name="[4] Ticket de Loterie 🎟️", value="Prix: **500** 🪙\n*Un ticket pour le prochain tirage au sort !*", inline=False)
    embed.add_field(name="[5] Boost Jeu 🚀", value="Prix: **5,000** 🪙\n*+20% de revenus sur vos serveurs Web pendant 1 heure.*", inline=False)
    
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="buy", description="Acheter un article dans la boutique.")
@app_commands.choices(article=[
    app_commands.Choice(name="1 - Couleur Rouge (10k 🪙)", value=1),
    app_commands.Choice(name="2 - Couleur Bleue (10k 🪙)", value=2),
    app_commands.Choice(name="3 - Rôle Riche (50k 🪙)", value=3),
    app_commands.Choice(name="4 - Ticket de Loterie (500 🪙)", value=4),
    app_commands.Choice(name="5 - Boost Jeu 1h (5k 🪙)", value=5) # 🟢 NOUVEAU
])
async def buy(interaction: discord.Interaction, article: app_commands.Choice[int]):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid)
    
    # ⚙️ CONFIGURATION DES RÔLES (À remplacer par tes vrais IDs)
    ROLE_ROUGE_ID = 1512092336509816952
    ROLE_BLEU_ID = 1512092117353234482
    ROLE_RICHE_ID = 1512090948992106516 
    
    articles = {
        1: {"nom": "Couleur Rouge", "prix": 10000, "role_id": ROLE_ROUGE_ID, "type": "couleur"},
        2: {"nom": "Couleur Bleue", "prix": 10000, "role_id": ROLE_BLEU_ID, "type": "couleur"},
        3: {"nom": "Rôle Riche", "prix": 50000, "role_id": ROLE_RICHE_ID, "type": "role"},
        4: {"nom": "Ticket de Loterie", "prix": 500, "role_id": None, "type": "item"},
        5: {"nom": "Boost Jeu", "prix": 5000, "role_id": None, "type": "boost"} # 🟢 NOUVEAU
    }
    
    choix = articles[article.value]
    
    # 1. Vérification de l'argent du joueur
    if wallet['coins'] < choix['prix']:
        return await interaction.response.send_message(f"❌ Tu n'as pas assez d'argent ! Il te faut **{choix['prix']}** 🪙 dans ton portefeuille.", ephemeral=True)
        
    # 2. On retire l'argent
    e[gid][uid]['coins'] -= choix['prix']
    seco(e)
    
    # 3A. Si c'est une Couleur
    if choix['type'] == "couleur":
        role = interaction.guild.get_role(choix['role_id'])
        if not role:
            e[gid][uid]['coins'] += choix['prix'] # Remboursement
            seco(e)
            return await interaction.response.send_message("❌ Cette couleur n'est pas encore configurée par le Fondateur. Tu as été remboursé.", ephemeral=True)
            
        if role in interaction.user.roles:
            e[gid][uid]['coins'] += choix['prix']
            seco(e)
            return await interaction.response.send_message(f"❌ Tu possèdes déjà la **{choix['nom']}** ! Tu as été remboursé.", ephemeral=True)
            
        try:
            couleurs_possibles = [interaction.guild.get_role(ROLE_ROUGE_ID), interaction.guild.get_role(ROLE_BLEU_ID)]
            roles_a_retirer = [r for r in couleurs_possibles if r and r in interaction.user.roles]
            if roles_a_retirer: await interaction.user.remove_roles(*roles_a_retirer)
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"🎨 Félicitations {interaction.user.mention} ! Ton pseudo est maintenant équipé de la **{choix['nom']}** !")
        except discord.Forbidden:
            e[gid][uid]['coins'] += choix['prix']
            seco(e)
            await interaction.response.send_message("❌ Erreur : Mon rôle de bot est placé trop bas. (Tu as été remboursé)", ephemeral=True)

    # 3B. Si c'est le Rôle Riche
    elif choix['type'] == "role":
        role = interaction.guild.get_role(choix['role_id'])
        if not role:
            e[gid][uid]['coins'] += choix['prix']
            seco(e)
            return await interaction.response.send_message("❌ Ce rôle n'est pas encore configuré. Tu as été remboursé.", ephemeral=True)
            
        if role in interaction.user.roles:
            e[gid][uid]['coins'] += choix['prix']
            seco(e)
            return await interaction.response.send_message(f"❌ Tu es déjà **{choix['nom']}** ! Tu as été remboursé.", ephemeral=True)
            
        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"💎 Félicitations {interaction.user.mention} ! Tu es maintenant officiellement **{choix['nom']}** !")
        except discord.Forbidden:
            e[gid][uid]['coins'] += choix['prix']
            seco(e)
            await interaction.response.send_message("❌ Erreur : Mon rôle de bot est placé trop bas. (Tu as été remboursé)", ephemeral=True)

    # 3C. Si c'est un ticket de loterie
    elif choix['type'] == "item":
        n = nts() 
        if uid not in n: n[uid] = []
        n[uid].append({'texte': f'🎟️ {choix["nom"]} (Shop)', 'time': str(discord.utils.utcnow())})
        snts(n)
        await interaction.response.send_message(f"🎟️ Tu as acheté un **{choix['nom']}** pour {choix['prix']} 🪙 !\n*(Tu peux voir tes tickets en tapant `/notes`)*")

    # 3D. 🟢 NOUVEAUTÉ : Le Boost de Jeu Web
    elif choix['type'] == "boost":
        # Hachage sécurisé de l'acheteur
        secret_salt = "Tycoon_SecretKey_2026!Admintycoongame202645BonChanceqsdqsdqsd,;s:sdfsdfscfgretg"
        texte_a_hacher = secret_salt + str(interaction.user.id)
        hashed_uid = hashlib.sha256(texte_a_hacher.encode('utf-8')).hexdigest()

        # On utilise hashed_uid !
        res = supabase_game.table('players').select('username, game_state').eq('discord_id', hashed_uid).execute()
        if not res.data:
            e[gid][uid]['coins'] += choix['prix'] # Remboursement auto !
            seco(e)
            return await interaction.response.send_message("❌ Tu dois d'abord lier ton compte sur le jeu web (Bouton 🔗 Rôles Discord). Tu as été remboursé.", ephemeral=True)
        
        # Applique le boost sur le jeu
        username = res.data[0]['username']
        state = res.data[0]['game_state']
        if isinstance(state, str): state = json.loads(state)
        now = datetime.now(timezone.utc).timestamp()
        state['discord_boost_until'] = now + 3600
        
        supabase_game.table('players').update({'game_state': state}).eq('username', username).execute()
        saves = supabase_game.table('saves').select('id, game_state').eq('username', username).execute()
        for s in saves.data:
            s_st = s['game_state']
            if isinstance(s_st, str): s_st = json.loads(s_st)
            s_st['discord_boost_until'] = now + 3600
            supabase_game.table('saves').update({'game_state': s_st}).eq('id', s['id']).execute()
            
        await interaction.response.send_message(f"🚀 **Achat réussi {interaction.user.mention} !** Tes serveurs génèrent maintenant **+20% de revenus** pendant 1 heure ! Retourne vite sur le jeu !")


# --- ADMIN : GESTION ÉCONOMIE ---
@bot.tree.command(name="eco-add", description="Ajouter des coins à un membre (Admin uniquement).")
@app_commands.default_permissions(administrator=True)
async def eco_add(interaction: discord.Interaction, membre: discord.Member, montant: int):
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    # On récupère le portefeuille
    e, wallet = get_wallet(gid, uid)
    
    # On ajoute le montant
    e[gid][uid]['coins'] += montant
    seco(e)
    
    await interaction.response.send_message(f"✅ Ajouté **{montant}** 🪙 à {membre.mention}.", ephemeral=True)

@bot.tree.command(name="eco-remove", description="Retirer des coins à un membre (Admin uniquement).")
@app_commands.default_permissions(administrator=True)
async def eco_remove(interaction: discord.Interaction, membre: discord.Member, montant: int):
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    e, wallet = get_wallet(gid, uid)
    
    # On retire le montant
    e[gid][uid]['coins'] = max(0, e[gid][uid]['coins'] - montant)
    seco(e)
    
    await interaction.response.send_message(f"✅ Retiré **{montant}** 🪙 à {membre.mention}.", ephemeral=True)

# ============================================================
# 10. LEVELS
# ============================================================
@bot.tree.command(name="rank", description="Affiche ton niveau.")
async def rank(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    levels = lvl(); gid = str(interaction.guild.id); uid = str(m.id)
    data = levels.get(gid, {}).get(uid, {'total_xp': 0, 'messages': 0})
    total_xp = data.get('total_xp', 0)
    current_lvl, current_xp = get_level(total_xp); needed = xp_for_level(current_lvl + 1)
    
    embed = discord.Embed(title=f"⭐ Niveau de {m.display_name}", color=0xffd700)
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="Niveau", value=f"**{current_lvl}**")
    embed.add_field(name="XP", value=f"**{current_xp}/{needed}**")
    embed.add_field(name="Total XP", value=f"**{total_xp}**")
    embed.add_field(name="Messages", value=f"**{data.get('messages', 0)}**")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="level-reset", description="Réinitialiser les niveaux et l'XP d'un membre.")
@app_commands.default_permissions(administrator=True)
async def reset_level(interaction: discord.Interaction, membre: discord.Member):
    levels = lvl() # On récupère la base de données des niveaux
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    
    if gid in levels and uid in levels[gid]:
        # On remet tout à zéro
        levels[gid][uid] = {'total_xp': 0, 'messages': 0}
        slvl(levels) # On sauvegarde
        await interaction.response.send_message(f"✅ Niveaux de {membre.mention} réinitialisés à 0.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Ce membre n'a pas encore gagné d'XP.", ephemeral=True)

@bot.tree.command(name="leveltop", description="Top 10 des niveaux.")
async def leveltop(interaction: discord.Interaction):
    levels = lvl(); gid = str(interaction.guild.id)
    sorted_users = sorted(levels.get(gid, {}).items(), key=lambda x: x[1].get('total_xp', 0), reverse=True)[:10]
    embed = discord.Embed(title="⭐ Classement Niveaux", color=0xffd700)
    medals = ["🥇","🥈","🥉"] + [f"{i}." for i in range(4, 11)]
    for i, (uid, data) in enumerate(sorted_users):
        try:
            user = await bot.fetch_user(int(uid))
            lvl_num, _ = get_level(data.get('total_xp', 0))
            embed.add_field(name=f"{medals[i]} {user.name}", value=f"Niv. {lvl_num} — {data.get('total_xp',0)} XP", inline=False)
        except: pass
    await interaction.response.send_message(embed=embed)

# ============================================================
# 11. POLLS & GIVEAWAYS
# ============================================================
@bot.tree.command(name="poll", description="Crée un sondage.")
@app_commands.default_permissions(manage_messages=True)
async def poll(interaction: discord.Interaction, question: str, option1: str, option2: str, option3: str = None, option4: str = None):
    options = [o for o in [option1, option2, option3, option4] if o]
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣"]
    desc = "\n".join([f"{emojis[i]} {opt}" for i, opt in enumerate(options)])
    embed = discord.Embed(title=f"📊 {question}", description=desc, color=0x0099ff, timestamp=discord.utils.utcnow())
    embed.set_footer(text=f"Sondage par {interaction.user}", icon_url=interaction.user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    for i in range(len(options)): await msg.add_reaction(emojis[i])

@bot.tree.command(name="giveaway", description="Lance un giveaway.")
@app_commands.default_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, duree: int, gagnants: int, prix: str):
    await interaction.response.defer()
    embed = discord.Embed(title="🎉 GIVEAWAY 🎉", description=f"**Prix :** {prix}\n**Gagnants :** {gagnants}\n**Fin dans :** {duree}s\n\nRéagissez avec 🎉 !", color=0xff69b4, timestamp=discord.utils.utcnow())
    embed.set_footer(text=f"Par {interaction.user}", icon_url=interaction.user.display_avatar.url)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")
    await interaction.followup.send("✅ Giveaway lancé !", ephemeral=True)
    
    await asyncio.sleep(duree)
    msg = await interaction.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    participants = [u async for u in reaction.users() if not u.bot] if reaction else []
    
    if not participants:
        end_embed = discord.Embed(title="🎉 Terminé", description="Aucun participant.", color=discord.Color.red())
    else:
        choix = random.sample(participants, min(gagnants, len(participants)))
        end_embed = discord.Embed(title="🎉 Giveaway Terminé !", description=f"**Prix :** {prix}\n🏆 {' '.join([u.mention for u in choix])}", color=0xff69b4)
    await msg.edit(embed=end_embed)
    await interaction.channel.send(embed=end_embed)

# ============================================================
# 12. RAPPELS & UTILITAIRES
# ============================================================
@bot.tree.command(name="aide-jeux", description="Affiche le guide des mini-jeux du serveur.")
async def aide_jeux(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 Guide des Mini-Jeux du Serveur",
        description=(
            "Bienvenue dans l'espace détente ! Voici comment utiliser les mini-jeux disponibles :\n\n"
            "🪙 **1. Pile ou Face (`/pile-face`)**\n"
            "Le grand classique ! Le bot lance une pièce virtuelle en l'air. Vous avez une chance sur deux de tomber sur Pile ou sur Face.\n\n"
            "🎱 **2. La Boule Magique (`/8ball [question]`)**\n"
            "Posez une question fermée (oui/non) à notre Boule Magique. Elle vous donnera une réponse aléatoire parmi nos prédictions.\n\n"
            "🎲 **3. Lancer de Dés (`/roll [vos dés]`)**\n"
            "Idéal pour les jeux de rôle ! Attachez les chiffres avec la lettre **d** (sans espace).\n"
            "👉 *Format :* `XdY` (X = nombre de dés, Y = nombre de faces).\n"
            "• `/roll 1d6` ➔ Lance 1 dé à 6 faces.\n"
            "• `/roll 2d20` ➔ Lance 2 dés à 20 faces.\n\n"
            "🎰 **4. Le Casino / Pari (`/parier [montant]`)**\n"
            "Un véritable Quitte ou Double (50% de chance) :\n"
            "• 🟢 **Gagné :** Vous remportez 2x votre mise (ex: Pari 100 = Vous récupérez 200).\n"
            "• 🔴 **Perdu :** La banque garde votre mise.\n"
            "*À utiliser avec modération !*"
        ),
        color=0x5865f2
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rappel-creer", description="Créer un rappel.")
async def remind(interaction: discord.Interaction, duree: int, unite: str, texte: str):
    multipliers = {'s': 1, 'min': 60, 'h': 3600, 'j': 86400}
    mult = multipliers.get(unite, 60)
    trigger = datetime.now(timezone.utc).timestamp() + (duree * mult)
    data = rem()
    data.append({'user_id': interaction.user.id, 'channel_id': interaction.channel.id, 'time': trigger, 'text': texte})
    srem(data)
    await interaction.response.send_message(f"⏰ Rappel dans **{duree}{unite}** !", ephemeral=True)

@bot.tree.command(name="embed", description="Crée un embed personnalisé.")
@app_commands.default_permissions(manage_messages=True)
async def embed_cmd(interaction: discord.Interaction, titre: str, description: str, couleur: str = "0099ff", salon: discord.TextChannel = None):
    target = salon or interaction.channel
    try: color_int = int(couleur.replace('#',''), 16)
    except: color_int = 0x0099ff
    embed = discord.Embed(title=titre, description=description, color=color_int, timestamp=discord.utils.utcnow())
    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Envoyé dans {target.mention}", ephemeral=True)

@bot.tree.command(name="userinfo", description="Infos d'un membre.")
async def userinfo(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    roles = [r.mention for r in m.roles[1:]] or ["Aucun"]
    embed = discord.Embed(title=f"👤 {m}", color=m.color, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="ID", value=m.id); embed.add_field(name="Surnom", value=m.display_name); embed.add_field(name="Bot", value="Oui" if m.bot else "Non")
    embed.add_field(name="Créé le", value=discord.utils.format_dt(m.created_at, 'D')); embed.add_field(name="Rejoint le", value=discord.utils.format_dt(m.joined_at, 'D') if m.joined_at else "?")
    embed.add_field(name=f"Rôles ({len(m.roles)-1})", value=" ".join(roles[:8]) + ("..." if len(roles) > 8 else ""), inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="Infos du serveur.")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"🏠 {g.name}", color=0x0099ff, timestamp=discord.utils.utcnow())
    if g.icon: embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="ID", value=g.id); embed.add_field(name="Propriétaire", value=g.owner.mention if g.owner else "?"); embed.add_field(name="Membres", value=g.member_count)
    embed.add_field(name="Salons", value=len(g.channels)); embed.add_field(name="Rôles", value=len(g.roles)); embed.add_field(name="Boosts", value=f"Niv.{g.premium_tier} ({g.premium_subscription_count})")
    embed.add_field(name="Créé le", value=discord.utils.format_dt(g.created_at, 'D'))
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="avatar", description="Avatar d'un membre.")
async def avatar(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    embed = discord.Embed(title=f"🖼️ {m.display_name}", color=m.color)
    embed.set_image(url=m.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="Latence du bot.")
async def ping(interaction: discord.Interaction):
    ms = round(bot.latency * 1000)
    c = discord.Color.green() if ms < 100 else discord.Color.orange() if ms < 200 else discord.Color.red()
    embed = discord.Embed(title="🏓 Pong !", description=f"**{ms}ms**", color=c)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="envoyer", description="Envoyer un message sous l'identité du bot.")
async def say(interaction: discord.Interaction, texte: str, salon: discord.TextChannel = None):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("❌ Owner seulement.", ephemeral=True)
    target = salon or interaction.channel
    await target.send(texte)
    await interaction.response.send_message("✅ Envoyé.", ephemeral=True)

@bot.tree.command(name="note", description="Sauvegarde une note personnelle.")
async def note(interaction: discord.Interaction, texte: str):
    n = nts(); uid = str(interaction.user.id)
    if uid not in n: n[uid] = []
    n[uid].append({'texte': texte, 'time': str(discord.utils.utcnow())}); snts(n)
    await interaction.response.send_message("📝 Note sauvegardée !", ephemeral=True)

@bot.tree.command(name="notes", description="Voir tes notes.")
async def notes(interaction: discord.Interaction):
    n = nts(); user_notes = n.get(str(interaction.user.id), [])
    if not user_notes:
        return await interaction.response.send_message("Aucune note.", ephemeral=True)
    embed = discord.Embed(title="📝 Tes notes", color=0x0099ff)
    for i, note_item in enumerate(user_notes[-10:], 1):
        embed.add_field(name=f"#{i}", value=note_item['texte'], inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="pile-face", description="Jouer à pile ou face.")
async def flip(interaction: discord.Interaction):
    await interaction.response.send_message(f"**{random.choice(['Pile 🪙', 'Face 🌟'])}** !")

@bot.tree.command(name="roll", description="Lance un dé (ex: 2d6).")
async def roll(interaction: discord.Interaction, de: str = "1d6"):
    try:
        parts = de.lower().split('d'); n, faces = int(parts[0]) if parts[0] else 1, int(parts[1])
        n = min(n, 20); faces = min(faces, 1000)
        results = [random.randint(1, faces) for _ in range(n)]
        embed = discord.Embed(title=f"🎲 {de}", description=f"**{', '.join(map(str, results))}**\nTotal : **{sum(results)}**", color=0x0099ff)
        await interaction.response.send_message(embed=embed)
    except: await interaction.response.send_message("❌ Format invalide. Ex: `2d6`", ephemeral=True)

@bot.tree.command(name="8ball", description="Boule magique.")
async def eightball(interaction: discord.Interaction, question: str):
    answers = ["Oui, absolument.", "C'est certain.", "Sans aucun doute.", "Très probablement.", "Oui.", "Je ne sais pas...", "Impossible à dire.", "Peut-être.", "Non.", "Certainement pas."]
    embed = discord.Embed(title="🎱 Boule Magique", color=0x6a0dad)
    embed.add_field(name="❓", value=question); embed.add_field(name="🔮", value=random.choice(answers))
    await interaction.response.send_message(embed=embed)

# 🟢 1. LA FONCTION D'AUTOCOMPLÉTION DYNAMIQUE
async def aide_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    # On vérifie si le joueur est admin/staff PENDANT qu'il tape la commande
    is_admin = interaction.user.guild_permissions.administrator or is_staff(interaction.user)

    # La liste pour TOUS les joueurs
    choix = [
        app_commands.Choice(name="Invitations", value="📨 Invitations"),
        app_commands.Choice(name="Économie", value="💰 Économie"),
        app_commands.Choice(name="Niveaux", value="⭐ Niveaux"),
        app_commands.Choice(name="Fun & Jeux", value="🎮 Fun & Jeux"),
        app_commands.Choice(name="Informations", value="ℹ️ Informations"),
        app_commands.Choice(name="Admin Tycoon (Jeu)", value="🌐 Le Jeu")
    ]

    # Si c'est un Staff, on rajoute secrètement les catégories Admin dans sa liste
    if is_admin:
        choix.insert(0, app_commands.Choice(name="Setup (Admin)", value="⚙️ Setup"))
        choix.insert(1, app_commands.Choice(name="Modération (Staff)", value="🔨 Modération"))
        choix.insert(2, app_commands.Choice(name="Outils Admin (Staff)", value="🛠️ Outils Admin"))

    # Retourne les choix (permet aussi la recherche si l'utilisateur commence à taper des lettres)
    return [c for c in choix if current.lower() in c.name.lower()]


# 🟢 2. LA COMMANDE AIDE PRINCIPALE
@bot.tree.command(name="aide", description="Affiche les commandes du bot.")
@app_commands.autocomplete(categorie=aide_autocomplete) # 👈 On relie la commande à la fonction au-dessus !
async def aide_cmd(interaction: discord.Interaction, categorie: str = None): # 👈 "categorie" est maintenant un texte (str)
    
    is_admin = interaction.user.guild_permissions.administrator or is_staff(interaction.user)

    # Commandes PUBIQUES (Visibles par tous les joueurs)
    # Commandes PUBLIQUES (Visibles par tous les joueurs)
    categories = {
        "📨 Invitations": [("`/invites`","Invitations perso"),("`/topinvites`","Top inviteurs")],
        "💰 Économie": [("`/solde`","Solde"),("`/journalier`","Quotidien"),("`/travail`","Travailler"),
                        ("`/déposer`","Déposer"),("`/retirer`","Retirer"),("`/parier`","Parier"),
                        ("`/payer`","Donner"),("`/leaderboard`","Top économie"),
                        ("`/shop`","Voir la boutique"),("`/buy`","Acheter un article")],
        "⭐ Niveaux": [("`/rank`","Niveau"),("`/leveltop`","Top niveaux")],
        "🎮 Fun & Jeux": [("`/aide-jeux`", "Guide des jeux"),("`/pile-face`","Pile/Face"),
                          ("`/roll`","Dés"),("`/8ball`","Magique")],
        "ℹ️ Informations": [("`/rappel-creer`","Créer rappel"),("`/userinfo`","Infos User"),
                            ("`/serverinfo`","Infos Serveur"),("`/avatar`","Avatar"),("`/ping`","Ping")],
                            
        # 🟢 NOUVEAUTÉ : On actualise la rubrique Jeu
        "🌐 Le Jeu": [("`/sync`","Réclamer ses rôles (Nécessite de lier son compte en jeu)"),
                      ("`/shop`","Acheter le Boost Jeu (+20% de revenus) via la boutique"),
                      ("Lien du jeu", "https://admin-tycoon.onrender.com/")]
    }

    # Commandes CACHÉES (Visibles uniquement par le Staff/Admin)
    admin_categories = {
        "⚙️ Setup": [("`/config-regles`","Règles"),("`/config-tickets`","Tickets"),
                     ("`/config-bienvenue`","Bienvenue"),("`/config-depart`","Départ"),
                     ("`/config-logs`","Logs global"),("`/config-modlog`","Logs modération"),
                     ("`/config-suggestions`","Suggestions"),("`/config-levelup`","Level-up"),
                     ("`/config-autorole`","Auto-rôle"),("`/config-levelrole`","Rôle niveau"),
                     ("`/config-maxtickets`","Max tickets"),("`/config-antispam`","Anti-spam"),
                     ("`/config-mot-interdit`","Mot interdit"), ("`/config-exclure-salon`", "Exclure XP"),
                     ("`/config-inclure-salon`", "Inclure XP"), ("`/config-leaderboard`","Auto-actualisation du Top 10")],
        "🔨 Modération": [("`/ban`","Bannir"),("`/deban`","Débannir"),("`/expulser`","Expulser"),
                          ("`/mute`","Rendre muet"),("`/demute`","Démute"),("`/avertir`","Avertir"),
                          ("`/infractions-retirer`","Unwarn"),("`/infractions-lister`","Voir warns"),
                          ("`/infractions-reinitialiser`","Purger warns"), ("`/purge`","Purger messages"),
                          ("`/slowmode`","Slowmode"),("`/lock`","Lock salon"),("`/unlock`","Unlock salon")],
        "🛠️ Outils Admin": [("`/invitations-reinitialiser`","Purger les invitations"),
                            ("`/level-reset`","Réinitialiser le niveau d'un joueur"),
                            ("`/envoyer`","Faire parler le bot"),
                            ("`/embed`","Créer un Embed personnalisé"),
                            ("`/giveaway`","Lancer un Giveaway"),
                            ("`/poll`","Lancer un Sondage officiel"),
                            ("`/note`","Ajouter une note de modération"),
                            ("`/notes`","Voir les notes d'un joueur")]
    }

    if is_admin:
        categories.update(admin_categories)

    if categorie:
        cat_name = categorie 
        
        if cat_name in admin_categories and not is_admin:
            return await interaction.response.send_message("❌ Tu n'as pas la permission de voir cette catégorie.", ephemeral=True)
            
        embed = discord.Embed(title=f"❓ {cat_name}", color=0x5865F2)
        
        if cat_name in categories:
            for cmd, desc in categories[cat_name]: 
                embed.add_field(name=cmd, value=desc, inline=True)
            
        if cat_name == "🌐 Le Jeu":
            embed.description = "**Admin Tycoon** est notre jeu de gestion de serveurs sur navigateur.\n\nPour obtenir tes rôles Discord, va sur le jeu, clique sur **🔗 Rôles Discord**, puis reviens ici et tape `/sync`.\n\nUtilise l'argent virtuel de Discord pour acheter le **Boost Jeu** dans le `/shop` !"
            
    else:
        embed = discord.Embed(title="❓ Menu d'aide", description="Sélectionne une catégorie avec `/aide [catégorie]`.", color=0x5865F2)
        for cat_name, cmds_list in categories.items():
            embed.add_field(name=cat_name, value=f"`{len(cmds_list)}` commandes", inline=True)
            
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ban-jeu", description="Bannir un joueur du jeu web")
@app_commands.default_permissions(administrator=True)
async def ban_jeu_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str = "Non-respect des règles"):
    await interaction.response.defer()
    
    # 🔐 On hache l'ID pour correspondre à Supabase
    secret_salt = "Tycoon_SecretKey_2026!Admintycoongame202645BonChanceqsdqsdqsd,;s:sdfsdfscfgretg"
    texte_a_hacher = secret_salt + str(membre.id)
    hashed_uid = hashlib.sha256(texte_a_hacher.encode('utf-8')).hexdigest()
    
    res = supabase_game.table('players').update({'is_excluded': True}).eq('discord_id', hashed_uid).execute()
    
    if res.data:
        await interaction.followup.send(f"🔨 **{membre.name}** a été banni du jeu web !\nRaison : {raison}")
        try:
            await membre.send(f"🚨 **ALERTE SYSTÈME**\nTu as été banni de *Admin Tycoon* par un administrateur.\n**Raison :** {raison}")
        except:
            pass # Le joueur a bloqué ses MP
    else:
        await interaction.followup.send("❌ Impossible de trouver ce joueur (compte non lié).", ephemeral=True)

@bot.tree.command(name="unban-jeu", description="Débannir un joueur du jeu web")
@app_commands.default_permissions(administrator=True)
async def unban_jeu_cmd(interaction: discord.Interaction, membre: discord.Member):
    await interaction.response.defer()
    
    secret_salt = "Tycoon_SecretKey_2026!Admintycoongame202645BonChanceqsdqsdqsd,;s:sdfsdfscfgretg"
    texte_a_hacher = secret_salt + str(membre.id)
    hashed_uid = hashlib.sha256(texte_a_hacher.encode('utf-8')).hexdigest()
    
    res = supabase_game.table('players').update({'is_excluded': False}).eq('discord_id', hashed_uid).execute()
    
    if res.data:
        await interaction.followup.send(f"✅ **{membre.name}** a été débanni du jeu web et remis dans le Leaderboard !")
    else:
        await interaction.followup.send("❌ Impossible de trouver ce joueur.", ephemeral=True)

# ============================================================
# 13. DASHBOARD API FLASK (Tourne en arrière-plan) - SÉCURISÉE 🔒
# ============================================================
from flask import Flask, request, jsonify
from flask_cors import CORS
import urllib.request
import json

app_flask = Flask(__name__)

# ✅ CORS géré uniquement par Flask-CORS
CORS(app_flask,
     resources={r"/*": {"origins": ["https://letintin45.github.io"]}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=False)

# 🔐 Cache des connexions Discord
auth_cache = {}

@app_flask.before_request
def require_auth():
    # 🟢 On retourne "None" au lieu de 204 pour laisser Flask-CORS faire son travail
    if request.method == 'OPTIONS':
        return 
        
    if request.path in ('/ping', '/api/debug'):
        return

    auth_header = request.headers.get('Authorization', '')
    token = auth_header.replace('Bearer ', '').strip()

    if not token:
        return jsonify({'success': False, 'error': 'Non autorisé.'}), 401

    if token not in auth_cache:
        req = urllib.request.Request("https://discord.com/api/users/@me")
        req.add_header("Authorization", f"Bearer {token}")
        # ⚠️ INDISPENSABLE : Discord bloque les requêtes sans "User-Agent" !
        req.add_header("User-Agent", "AdminTycoonBot (https://letintin45.github.io, 1.0)")
        
        try:
            with urllib.request.urlopen(req) as response:
                user_data = json.loads(response.read())
                auth_cache[token] = int(user_data['id'])
        except Exception as e:
            print(f"❌ Erreur Token Discord : {e}")
            return jsonify({'success': False, 'error': 'Token invalide.'}), 401

# --- PING pour UptimeRobot ---
@app_flask.route('/ping', methods=['GET', 'OPTIONS'])
def ping_server():
    return "OK", 200

# --- DEBUG : vérifie que Supabase répond ---
@app_flask.route('/api/debug', methods=['GET'])
def api_debug():
    try:
        res = supabase.table('config').select('guild_id').limit(3).execute()
        return jsonify({
            'supabase': 'OK',
            'rows_config': len(res.data),
            'sample': [r['guild_id'] for r in res.data],
            'bot_guilds': [str(g.id) for g in bot.guilds] if bot.is_ready() else []
            # La ligne du mot de passe a été supprimée !
        })
    except Exception as e:
        return jsonify({'supabase': 'ERREUR', 'detail': str(e)}), 500
    
@app_flask.route('/api/login', methods=['POST'])
def api_login():
    # Plus de vérification manuelle OPTIONS ici, Flask-CORS gère tout !
    token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    user_id = auth_cache.get(token)
    return jsonify({'success': True, 'user_id': user_id})

@app_flask.route('/api/test/welcome/<guild_id>', methods=['POST'])
def api_test_welcome(guild_id):
    g = bot.get_guild(int(guild_id))
    if g and g.owner:
        # On charge la configuration du serveur pour la passer à la fonction
        c = cfg()
        gc = c.get(str(guild_id), {})
        
        # On appelle la bonne fonction _send_welcome avec l'owner du serveur comme test
        asyncio.run_coroutine_threadsafe(_send_welcome(g.owner, None, None, gc), bot.loop)
        
    return jsonify({'success': True})

@app_flask.route('/api/test/rules/<guild_id>', methods=['POST'])
def api_test_rules(guild_id):
    c = cfg(); gc = c.get(str(guild_id), {})
    g = bot.get_guild(int(guild_id))
    if g:
        ch = g.get_channel(gc.get('welcome_channel'))
        if ch:
            embed = discord.Embed(title=gc.get('rules_title', 'Règles'), description=gc.get('rules_text', 'Test'), color=0x0099ff)
            asyncio.run_coroutine_threadsafe(ch.send(embed=embed), bot.loop)
    return jsonify({'success': True})

@app_flask.route('/api/guilds', methods=['GET'])
def get_guilds():
    token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    user_id = auth_cache.get(token)

    authorized_guilds = []
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member:
            # 1. On détermine son grade
            role = "user"
            if guild.owner_id == user_id or member.guild_permissions.administrator:
                role = "admin"
            elif is_staff(member):
                role = "modo"

            # 2. S'il est staff, on lui donne accès au serveur avec son grade
            if role != "user":
                authorized_guilds.append({
                    'id': str(guild.id),
                    'name': guild.name,
                    'member_count': guild.member_count,
                    'role': role # <-- Le site web utilisera ça pour cacher certains menus !
                })
                
    return jsonify(authorized_guilds)


#NE SURTOUT PAS SUPPRIMER : C'est la route centrale pour récupérer et mettre à jour la configuration d'un serveur depuis le dashboard.
def sanitize_for_json(data):
    """Convertit les grands entiers en chaînes pour éviter la perte de précision JS (limite 53 bits)."""
    if isinstance(data, dict):
        return {k: sanitize_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_for_json(v) for v in data]
    elif isinstance(data, int) and data > 9999999999:
        return str(data)
    return data

@app_flask.route('/api/config/<guild_id>', methods=['GET'])
def get_config(guild_id):
    # 🟢 On protège les données avant de les envoyer au Dashboard
    return jsonify(sanitize_for_json(cfg().get(guild_id, {})))

@app_flask.route('/api/config/<guild_id>', methods=['POST'])
def update_config(guild_id):
    # --- 🔒 VIGILE BACKEND (SÉCURITÉ ABSOLUE) ---
    token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    user_id = auth_cache.get(token)
    
    guild = bot.get_guild(int(guild_id))
    if not guild: 
        return jsonify({'success': False, 'error': 'Serveur introuvable'}), 404
        
    member = guild.get_member(user_id)
    # Si la personne n'est pas sur le serveur OU n'est pas Administrateur/Owner : DEHORS !
    if not member or (guild.owner_id != user_id and not member.guild_permissions.administrator):
        return jsonify({'success': False, 'error': 'Fraude détectée : Accès refusé.'}), 403
    # --------------------------------------------

    c = cfg()
    if guild_id not in c: c[guild_id] = {}

    CHANNEL_KEYS = {'welcome_channel', 'leave_channel', 'log_channel', 'mod_log_channel',
                    'suggestion_channel', 'level_channel', 'ticket_category', 'live_lb_channel'}
    ROLE_KEYS = {'auto_role', 'rules_role_id'}
    TEXT_KEYS = {
        'rules_title', 'rules_text', 'welcome_title', 'welcome_message',
        'welcome_color', 'leave_message', 'leave_title',
        'ticket_panel_title', 'ticket_panel_desc', 
        'ticket_active_title', 'ticket_active_desc',
        'sugg_panel_title', 'sugg_panel_desc'
    }

    patch = {}
    for k, v in request.json.items():
        if v is None: continue

        if k in CHANNEL_KEYS or k in ROLE_KEYS:
            if v == '' or v == 0 or v is False: continue
            try: patch[k] = int(v) # Le bot convertit proprement en vrai Entier Python
            except: continue
            
        elif k in TEXT_KEYS:
            patch[k] = str(v)
            
        elif isinstance(v, list):
            parsed = []
            for item in v:
                try: parsed.append(int(item))
                except: parsed.append(item)
            patch[k] = parsed
            
        else:
            patch[k] = v

    c[guild_id].update(patch)
    scfg(c)
    print(f"✅ Config sauvegardée pour {guild_id} : {list(patch.keys())}")
    
    # 🟢 NOUVEAUTÉ : Mise à jour de l'horloge du Leaderboard (Utilise float() !)
    if 'lb_interval' in patch:
        nouvel_interval = float(patch['lb_interval'])
        if auto_update_leaderboard.is_running():
            auto_update_leaderboard.change_interval(hours=nouvel_interval)
        else:
            auto_update_leaderboard.start()
            auto_update_leaderboard.change_interval(hours=nouvel_interval)
            
    # 🟢 Retourne les données protégées
    return jsonify({'success': True, 'config': sanitize_for_json(c[guild_id])})

@app_flask.route('/api/stats/<guild_id>')
def get_stats(guild_id):
    s = stats(); e = eco(); l = lvl(); w = wrn(); inv_data = inv()
    gs = s.get(guild_id, {}); ge = e.get(guild_id, {}); gw = w.get(guild_id, {}); gi = inv_data.get(guild_id, {})
    total_coins = sum(v.get('coins',0)+v.get('bank',0) for v in ge.values())
    total_warns = sum(len(v) for v in gw.values())
    top_inv = max(gi.items(), key=lambda x: x[1].get('count',0), default=(None,{'count':0}))
    
    total_game_players = 0
    total_game_money = 0
    if supabase_game:
        # 🟢 NOUVEAU : On récupère aussi la colonne is_excluded
        pres = supabase_game.table('players').select('game_state, is_excluded').execute()
        if pres.data:
            # 🟢 NOUVEAU : On filtre pour NE GARDER QUE les joueurs non exclus
            valid_players = [p for p in pres.data if not p.get('is_excluded')]
            
            total_game_players = len(valid_players)
            for p in valid_players:
                st = p.get('game_state', {})
                if isinstance(st, str): 
                    try: st = json.loads(st)
                    except: st = {}
                total_game_money += float(st.get('money', 0)) if isinstance(st, dict) else 0

    open_tickets = 0
    g = bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
    if g: open_tickets = sum(1 for ch in g.text_channels if ch.name.startswith('ticket-'))
    return jsonify({**gs, 'total_coins_circulating': total_coins, 'total_warns': total_warns,
                    'active_members_economy': len(ge), 'active_members_levels': len(l.get(guild_id,{})),
                    'top_inviter_count': top_inv[1].get('count',0), 'open_tickets': open_tickets,
                    'total_game_players': total_game_players, 'total_game_money': total_game_money})

@app_flask.route('/api/guild/<guild_id>/channels')
def get_channels(guild_id):
    g = bot.get_guild(int(guild_id))
    return jsonify([{'id': str(c.id), 'name': c.name} for c in g.text_channels] if g else [])

@app_flask.route('/api/guild/<guild_id>/roles')
def get_roles(guild_id):
    g = bot.get_guild(int(guild_id))
    return jsonify([{'id': str(r.id), 'name': r.name, 'color': str(r.color)} for r in g.roles if r.name != '@everyone'] if g else [])

@app_flask.route('/api/guild/<guild_id>/categories')
def get_categories(guild_id):
    g = bot.get_guild(int(guild_id))
    return jsonify([{'id': str(c.id), 'name': c.name} for c in g.categories] if g else [])

@app_flask.route('/api/economy/<guild_id>')
def get_economy(guild_id): return jsonify(eco().get(guild_id, {}))

@app_flask.route('/api/warns/<guild_id>')
def get_warns(guild_id): return jsonify(wrn().get(guild_id, {}))

@app_flask.route('/api/warns/<guild_id>/<user_id>/pop', methods=['POST'])
def pop_warn(guild_id, user_id):
    w = wrn()
    if guild_id in w and user_id in w[guild_id] and w[guild_id][user_id]:
        w[guild_id][user_id].pop(); swrn(w)
    return jsonify({'success': True})

@app_flask.route('/api/levels/<guild_id>')
def get_levels(guild_id): return jsonify(lvl().get(guild_id, {}))

@app_flask.route('/api/invites/<guild_id>')
def get_invites_api(guild_id):
    """
    Retourne les invitations stockées dans Supabase (comptes anti-leave/anti-alt).
    Ajoute aussi un debug pour savoir si la table existe bien.
    """
    stored = inv().get(guild_id, {})

    # Si vide, on essaie de construire depuis le snapshot Discord live en mémoire
    if not stored:
        guild = bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
        if guild:
            # Le snapshot mémoire du bot = {code: uses} — pas de user_id ici
            # On retourne un objet vide avec un flag pour informer le dashboard
            return jsonify({'__debug__': 'Aucune invitation trackée dans Supabase. La table invites doit être créée ou un membre doit rejoindre via invitation.'})
    
    return jsonify(stored)

@app_flask.route('/api/send_message', methods=['POST'])
def send_message_api():
    data = request.json
    channel_id = data.get('channel_id'); content = data.get('content', ''); embed_data = data.get('embed')
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if not channel: return jsonify({'success': False})
    async def _send():
        if embed_data:
            embed = discord.Embed(title=embed_data.get('title',''), description=embed_data.get('description',''), color=int(embed_data.get('color','0099ff').replace('#',''),16))
            await channel.send(content=content or None, embed=embed)
        else: await channel.send(content)
    asyncio.run_coroutine_threadsafe(_send(), bot.loop)
    return jsonify({'success': True})

@app_flask.route('/api/reaction_roles_create', methods=['POST'])
def create_rr_message():
    data = request.json
    channel_id = data.get('channel_id'); guild_id = data.get('guild_id'); title = data.get('title', 'Choisis tes rôles'); description = data.get('description', 'Réagis !'); pairs = data.get('pairs', [])
    guild = bot.get_guild(int(guild_id)) if guild_id else None
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if not guild or not channel: return jsonify({'success': False})
    async def _create():
        desc = description + '\n\n'
        for pair in pairs:
            role = guild.get_role(int(pair['role_id']))
            if role: desc += f"{pair['emoji']} → {role.mention}\n"
        msg = await channel.send(embed=discord.Embed(title=title, description=desc, color=0x5865f2))
        c = cfg()
        if str(guild_id) not in c: c[str(guild_id)] = {}
        if 'reaction_roles' not in c[str(guild_id)]: c[str(guild_id)]['reaction_roles'] = {}
        for pair in pairs:
            c[str(guild_id)]['reaction_roles'][f"{msg.id}_{pair['emoji']}"] = int(pair['role_id'])
            try: await msg.add_reaction(pair['emoji'])
            except: pass
        scfg(c)
    asyncio.run_coroutine_threadsafe(_create(), bot.loop)
    return jsonify({'success': True})

@app_flask.route('/api/create_poll', methods=['POST'])
def create_poll_api():
    data = request.json
    channel_id = data.get('channel_id'); question = data.get('question','Sondage'); options = data.get('options',[])
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if not channel or not options: return jsonify({'success': False})
    async def _poll():
        emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣"]
        desc = '\n'.join([f"{emojis[i]} {opt}" for i, opt in enumerate(options[:6])])
        msg = await channel.send(embed=discord.Embed(title=f"📊 {question}", description=desc, color=0x0099ff))
        for i in range(len(options[:6])): await msg.add_reaction(emojis[i])
    asyncio.run_coroutine_threadsafe(_poll(), bot.loop)
    return jsonify({'success': True})

@app_flask.route('/api/create_discord', methods=['POST'])
def create_discord():
    data = request.json
    guild_id = data.get('guild_id'); item_type = data.get('type'); name = data.get('name')
    guild = bot.get_guild(int(guild_id)) if guild_id else None
    if not guild or not name: return jsonify({'success': False})
    async def _create():
        if item_type == 'category': await guild.create_category(name)
        elif item_type == 'channel':
            cat = guild.get_channel(int(data.get('category_id'))) if data.get('category_id') else None
            await guild.create_text_channel(name, category=cat)
        elif item_type == 'role':
            color = int(data.get('color', '000000').replace('#', ''), 16) if data.get('color') else 0
            await guild.create_role(name=name, color=discord.Color(color))
    asyncio.run_coroutine_threadsafe(_create(), bot.loop)
    return jsonify({'success': True})

@app_flask.route('/api/joined_members/<guild_id>', methods=['GET'])
def get_joined_members(guild_id):
    return jsonify(joined_members().get(guild_id, {}))

# --- GESTIONNAIRE DE MEMBRES (ADMIN DASHBOARD) ---
@app_flask.route('/api/guild/<guild_id>/members', methods=['GET'])
def api_guild_members(guild_id):
    token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    user_id = auth_cache.get(token)
    guild = bot.get_guild(int(guild_id))
    if not guild: return jsonify([])
    
    member = guild.get_member(user_id)
    # Vérification de sécurité absolue :
    if not member or (guild.owner_id != user_id and not member.guild_permissions.administrator and not is_staff(member)):
        return jsonify([])

    e = eco().get(str(guild_id), {})
    l = lvl().get(str(guild_id), {})
    w = wrn().get(str(guild_id), {})

    members_data = []
    for m in guild.members:
        if not m.bot:
            uid = str(m.id)
            user_eco = e.get(uid, {'coins': 0, 'bank': 0})
            user_lvl = l.get(uid, {'total_xp': 0})
            user_warns = w.get(uid, [])
            
            members_data.append({
                'id': uid,
                'name': m.name,
                'avatar': m.display_avatar.url,
                'coins': user_eco.get('coins', 0) + user_eco.get('bank', 0),
                'xp': user_lvl.get('total_xp', 0),
                'warns': len(user_warns)
            })
    return jsonify(members_data)

@app_flask.route('/api/admin/action', methods=['POST'])
def api_admin_action():
    token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    user_id = auth_cache.get(token)
    data = request.json
    gid = str(data.get('guild_id'))
    uid = str(data.get('user_id'))
    action = data.get('action')
    amount = int(data.get('amount', 0))
    
    guild = bot.get_guild(int(gid))
    if not guild: return jsonify({'success': False})
    
    member = guild.get_member(user_id)
    if not member or (guild.owner_id != user_id and not member.guild_permissions.administrator and not is_staff(member)):
        return jsonify({'success': False, 'error': 'Accès refusé'})

    if action in ['add_eco', 'remove_eco']:
        e, wallet = get_wallet(gid, uid)
        if action == 'add_eco': e[gid][uid]['coins'] += amount
        else: e[gid][uid]['coins'] = max(0, e[gid][uid]['coins'] - amount)
        seco(e)
        
    elif action in ['add_xp', 'remove_xp']:
        levels = lvl()
        if gid not in levels: levels[gid] = {}
        if uid not in levels[gid]: levels[gid][uid] = {'total_xp': 0, 'messages': 0}
        if action == 'add_xp': levels[gid][uid]['total_xp'] += amount
        else: levels[gid][uid]['total_xp'] = max(0, levels[gid][uid]['total_xp'] - amount)
        slvl(levels)
        
    elif action == 'clear_warns':
        w = wrn()
        if gid in w and uid in w[gid]:
            w[gid][uid] = []
            swrn(w)
            
    return jsonify({'success': True})

# ==========================================
# ROUTES JEU (Leaderboard dashboard)
# ==========================================

@app_flask.route('/api/game_players', methods=['GET'])
def get_game_players():
    if not supabase_game:
        return jsonify({"error": "Supabase JEU non configuré (SUPABASE_GAME_URL manquant sur Render)"}), 503
    try:
        res = supabase_game.table('players').select('username, game_state, is_excluded').execute()
        players = res.data
        def safe_money(p):
            state = p.get('game_state', {})
            if isinstance(state, str):
                try: state = json.loads(state)
                except: return 0
            return state.get('money', 0) if isinstance(state, dict) else 0
        players.sort(key=safe_money, reverse=True)
        return jsonify(players)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app_flask.route('/api/game_players/exclude', methods=['POST'])
def toggle_game_exclusion():
    if not supabase_game:
        return jsonify({"error": "Supabase JEU non configuré"}), 503
    data = request.json
    username = data.get('username')
    new_state = data.get('is_excluded')
    try:
        supabase_game.table('players').update({'is_excluded': new_state}).eq('username', username).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500




# /!\ TRÈS IMPORTANT : Le host est 0.0.0.0 pour l'hébergement web /!\
# Tout à la fin de bot.py
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Flask démarré sur le port {port}")
    app_flask.run(host='0.0.0.0', port=port, debug=False, threaded=True, use_reloader=False)




if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)