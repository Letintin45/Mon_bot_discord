import discord
from discord.ext import commands, tasks
from discord import app_commands
import os, json, asyncio, random, re
from datetime import timedelta, datetime, timezone
from dotenv import load_dotenv

# ============================================================
# 1. INIT ET GESTION DES FICHIERS (Dossier /data)
# ============================================================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
DASHBOARD_PORT = int(os.getenv('DASHBOARD_PORT', '5000'))

# Crée le dossier data s'il n'existe pas
os.makedirs('data', exist_ok=True)

def _load(filename, default):
    filepath = os.path.join('data', filename)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def _save(filename, data):
    filepath = os.path.join('data', filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

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
        await interaction.response.send_message(f"🔓 Ticket réouvert par {interaction.user.mention}")
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
        await interaction.response.send_message(f"✅ Pris en charge par {interaction.user.mention}")
        button.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="ticket_close", emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        embed = discord.Embed(title=f"🎫 Ticket #{ticket_number:04d}", description=f"Bienvenue {interaction.user.mention} !\nL'équipe va vous répondre bientôt.", color=0x0099ff)
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
    print(f'✅ {bot.user} connecté')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Admin Tycoon 👑"))
    for guild in bot.guilds:
        bot.invites_tracker[guild.id] = await build_invite_snapshot(guild)
    s = stats()
    for guild in bot.guilds:
        gid = str(guild.id)
        if gid not in s: s[gid] = {}
        s[gid]['bot_start'] = datetime.now(timezone.utc).isoformat()
    sstats(s)

@bot.event
async def on_invite_create(invite): bot.invites_tracker[invite.guild.id] = await build_invite_snapshot(invite.guild)

@bot.event
async def on_invite_delete(invite): bot.invites_tracker[invite.guild.id] = await build_invite_snapshot(invite.guild)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    c = cfg(); gid = str(message.guild.id); uid = str(message.author.id); gc = c.get(gid, {})

    s = stats()
    if gid not in s: s[gid] = {}
    s[gid]['messages_total'] = s[gid].get('messages_total', 0) + 1
    sstats(s)

    banned = gc.get('banned_words', [])
    if banned and any(w.lower() in message.content.lower() for w in banned):
        try:
            await message.delete()
            m = await message.channel.send(embed=discord.Embed(description=f"🚫 {message.author.mention}, mot interdit.", color=discord.Color.red()))
            await asyncio.sleep(5); await m.delete()
        except: pass
        return

    if message.channel.id == gc.get('suggestion_channel'):
        embed = discord.Embed(title=f"💡 Suggestion de {message.author.display_name}", description=f"{message.content}\n\nRéagissez avec ✅ et ❌ !", color=0xffffff, timestamp=discord.utils.utcnow())
        embed.set_footer(text=message.author.display_name, icon_url=message.author.display_avatar.url)
        await message.delete()
        msg = await message.channel.send(embed=embed)
        await msg.add_reaction("✅"); await msg.add_reaction("❌")
        await msg.create_thread(name=f"Discussion — {message.content[:50]}")
        await bot.process_commands(message)
        return

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
            
        embed = discord.Embed(title=gc.get('welcome_title', '⚡ Bienvenue !'), description=desc, color=int(gc.get('welcome_color', '00bfff').replace('#',''), 16))
    else:
        embed = discord.Embed(title="⚡ Bienvenue !", description=f"Salut {member.mention} ! Tu es notre **{hc}ème** membre ! 🎉", color=0x00bfff)
        
    embed.set_thumbnail(url=member.display_avatar.url)
    
    # Affichage du petit footer si l'option est cochée sur le dashboard
    if inviter and gc.get('show_inviter', True):
        embed.add_field(name="Invité par", value=f"{inviter.mention} (qui possède {inviter_invites} invitations)")
        
    embed.set_footer(text=member.guild.name, icon_url=member.guild.icon.url if member.guild.icon else None)
    await ch.send(embed=embed)

@bot.event
async def on_member_join(member):
    c = cfg(); gid = str(member.guild.id); gc = c.get(gid, {})
    
    # Condition: Ignorer les bots
    if member.bot and gc.get('ignore_bots_welcome', True): 
        return

    s = stats()
    if gid not in s: s[gid] = {}
    s[gid]['members_joined'] = s[gid].get('members_joined', 0) + 1
    sstats(s)

    ar = gc.get('auto_role')
    if ar:
        role = member.guild.get_role(ar)
        if role:
            try: await member.add_roles(role)
            except: pass

    old_snapshot = bot.invites_tracker.get(member.guild.id, {})
    inviter, invite_code = await find_inviter(member.guild, old_snapshot)

    # Mode Sapphire (Attendre l'acceptation des règles)
    if gc.get('welcome_after_rules'):
        pending = _load('pending_welcome.json', {})
        if gid not in pending: pending[gid] = {}
        pending[gid][str(member.id)] = {
            'inviter_id': str(inviter.id) if inviter else None,
            'invite_code': invite_code
        }
        _save('pending_welcome.json', pending)
        return

    # Sinon, on envoie le message directement
    await _send_welcome(member, inviter, invite_code, gc)

@bot.event
async def on_member_remove(member):
    c = cfg(); gid = str(member.guild.id); gc = c.get(gid, {})
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
@bot.tree.command(name="setup_rules", description="Génère l'embed des règles.")
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

@bot.tree.command(name="setup_ticket", description="Installe le système de tickets.")
@app_commands.default_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction, categorie: discord.CategoryChannel, salon: discord.TextChannel = None):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['ticket_category'] = categorie.id; scfg(c)
    target = salon or interaction.channel
    embed = discord.Embed(title="🎫 Support", description="Clique sur le bouton pour ouvrir un ticket.", color=0x0099ff)
    await target.send(embed=embed, view=TicketOpenerView())
    await interaction.response.send_message(f"✅ Installé dans {target.mention}", ephemeral=True)

@bot.tree.command(name="set_welcome", description="Salon de bienvenue.")
@app_commands.default_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['welcome_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Bienvenue : {salon.mention}", ephemeral=True)

@bot.tree.command(name="set_leave", description="Salon de départ.")
@app_commands.default_permissions(administrator=True)
async def set_leave(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['leave_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Départ : {salon.mention}", ephemeral=True)

@bot.tree.command(name="set_logs", description="Salon des logs globaux.")
@app_commands.default_permissions(administrator=True)
async def set_logs(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['log_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Logs : {salon.mention}", ephemeral=True)

@bot.tree.command(name="set_modlog", description="Salon des logs de modération (ban/kick/warn...).")
@app_commands.default_permissions(administrator=True)
async def set_modlog(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['mod_log_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Logs modération : {salon.mention}", ephemeral=True)

@bot.tree.command(name="set_sugg", description="Salon des suggestions.")
@app_commands.default_permissions(administrator=True)
async def set_sugg(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['suggestion_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Suggestions : {salon.mention}", ephemeral=True)

@bot.tree.command(name="set_levelchan", description="Salon des annonces de level up.")
@app_commands.default_permissions(administrator=True)
async def set_levelchan(interaction: discord.Interaction, salon: discord.TextChannel):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['level_channel'] = salon.id; scfg(c)
    await interaction.response.send_message(f"✅ Level-up : {salon.mention}", ephemeral=True)

@bot.tree.command(name="set_autorole", description="Rôle automatique à l'arrivée.")
@app_commands.default_permissions(administrator=True)
async def set_autorole(interaction: discord.Interaction, role: discord.Role):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['auto_role'] = role.id; scfg(c)
    await interaction.response.send_message(f"✅ Auto-rôle : {role.mention}", ephemeral=True)

@bot.tree.command(name="set_levelrole", description="Attribue un rôle à un niveau précis.")
@app_commands.default_permissions(administrator=True)
async def set_levelrole(interaction: discord.Interaction, niveau: int, role: discord.Role):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    if 'level_roles' not in c[gid]: c[gid]['level_roles'] = {}
    c[gid]['level_roles'][str(niveau)] = role.id; scfg(c)
    await interaction.response.send_message(f"✅ Niveau **{niveau}** → {role.mention}", ephemeral=True)

@bot.tree.command(name="set_maxtickets", description="Limite le nombre de tickets ouverts simultanément (0 = illimité).")
@app_commands.default_permissions(administrator=True)
async def set_maxtickets(interaction: discord.Interaction, max: int):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['ticket_max_open'] = max; scfg(c)
    msg = f"✅ Max tickets : **{max}**" if max > 0 else "✅ Limite de tickets désactivée."
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="antispam", description="Active/désactive l'anti-spam.")
@app_commands.default_permissions(administrator=True)
async def antispam(interaction: discord.Interaction):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    c[gid]['anti_spam'] = not c[gid].get('anti_spam', False); scfg(c)
    await interaction.response.send_message(f"🛡️ Anti-spam {'activé' if c[gid]['anti_spam'] else 'désactivé'}.", ephemeral=True)

@bot.tree.command(name="banword", description="Ajoute un mot interdit (automod).")
@app_commands.default_permissions(administrator=True)
async def banword(interaction: discord.Interaction, mot: str):
    c = cfg(); gid = str(interaction.guild.id)
    if gid not in c: c[gid] = {}
    bw = c[gid].get('banned_words', [])
    if mot.lower() not in bw: bw.append(mot.lower())
    c[gid]['banned_words'] = bw; scfg(c)
    await interaction.response.send_message(f"✅ `{mot}` ajouté à l'automod.", ephemeral=True)

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

@bot.tree.command(name="unban", description="Débannit un utilisateur par ID.")
@app_commands.default_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ {user} débanni.", ephemeral=True)
    except:
        await interaction.response.send_message("❌ Introuvable.", ephemeral=True)

@bot.tree.command(name="kick", description="Expulse un membre.")
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

@bot.tree.command(name="unmute", description="Retire le timeout d'un membre.")
@app_commands.default_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, membre: discord.Member):
    await membre.timeout(None)
    await interaction.response.send_message(f"✅ {membre.mention} démute.", ephemeral=True)

@bot.tree.command(name="warn", description="Avertit un membre.")
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

@bot.tree.command(name="unwarn", description="Retire le dernier avertissement d'un membre.")
@app_commands.default_permissions(moderate_members=True)
async def unwarn(interaction: discord.Interaction, membre: discord.Member):
    w = wrn(); gid = str(interaction.guild.id); uid = str(membre.id)
    user_warns = w.get(gid, {}).get(uid, [])
    
    if not user_warns:
        return await interaction.response.send_message(f"✅ {membre.mention} n'a aucun warn.", ephemeral=True)
        
    removed = w[gid][uid].pop()
    swrn(w)
    await interaction.response.send_message(f"✅ Dernier warn de {membre.mention} retiré.\n*Raison retirée : {removed['raison']}*", ephemeral=True)

@bot.tree.command(name="warns", description="Voir les avertissements d'un membre.")
@app_commands.default_permissions(moderate_members=True)
async def warns_cmd(interaction: discord.Interaction, membre: discord.Member):
    w = wrn(); user_warns = w.get(str(interaction.guild.id), {}).get(str(membre.id), [])
    if not user_warns:
        return await interaction.response.send_message(f"✅ Aucun avertissement pour {membre.mention}.", ephemeral=True)
        
    embed = discord.Embed(title=f"⚠️ Warns de {membre}", color=discord.Color.orange())
    embed.set_thumbnail(url=membre.display_avatar.url)
    for i, ww in enumerate(user_warns, 1):
        embed.add_field(name=f"#{i} — par {ww['mod']}", value=ww['raison'], inline=False)
    embed.set_footer(text=f"Total : {len(user_warns)}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clearwarns", description="Efface tous les avertissements d'un membre.")
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
@bot.tree.command(name="invites", description="Voir les invitations d'un membre.")
async def invites_cmd(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    inv_data = inv(); user_inv = inv_data.get(str(interaction.guild.id), {}).get(str(m.id), {})
    stored_count = user_inv.get('count', 0)
    
    try:
        discord_invites = await interaction.guild.invites()
        active_count = sum(i.uses for i in discord_invites if i.inviter and i.inviter.id == m.id)
    except:
        active_count = stored_count
        
    embed = discord.Embed(title=f"📨 Invitations de {m.display_name}", color=0x5865F2)
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="Invitations actuelles (Discord)", value=f"**{active_count}** 📨")
    embed.add_field(name="Membres rejoints via lien (Total)", value=f"**{stored_count}** 🎯")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="topinvites", description="Top des inviteurs du serveur.")
async def topinvites(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        discord_invites = await interaction.guild.invites()
    except:
        return await interaction.followup.send("❌ Impossible de lire les invitations.", ephemeral=True)
        
    inv_counts = {}
    for invite in discord_invites:
        if invite.inviter:
            inv_counts[invite.inviter.id] = inv_counts.get(invite.inviter.id, 0) + invite.uses
            
    # Ajout de ceux dans la BDD
    inv_data = inv(); gid = str(interaction.guild.id)
    for uid, d in inv_data.get(gid, {}).items():
        try: uid_int = int(uid)
        except: continue
        if uid_int not in inv_counts: inv_counts[uid_int] = d.get('count', 0)
        
    sorted_inv = sorted(inv_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    medals = ["🥇","🥈","🥉"] + [f"{i}." for i in range(4, 11)]
    
    embed = discord.Embed(title="📨 Top Inviteurs", color=0x5865F2)
    if not sorted_inv: embed.description = "Aucune invitation."
    else:
        for i, (uid, count) in enumerate(sorted_inv):
            try:
                user = await bot.fetch_user(uid)
                embed.add_field(name=f"{medals[i]} {user.name}", value=f"**{count}** invitations", inline=False)
            except: pass
    await interaction.followup.send(embed=embed)

# ============================================================
# 9. ÉCONOMIE
# ============================================================
def get_wallet(gid, uid):
    e = eco()
    if gid not in e: e[gid] = {}
    if uid not in e[gid]: e[gid][uid] = {'coins': 0, 'bank': 0, 'last_daily': 0, 'last_work': 0}
    return e, e[gid][uid]

@bot.tree.command(name="balance", description="Vérifie ton solde.")
async def balance(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    e, wallet = get_wallet(str(interaction.guild.id), str(m.id))
    embed = discord.Embed(title=f"💰 Solde de {m.display_name}", color=0xffd700)
    embed.set_thumbnail(url=m.display_avatar.url)
    embed.add_field(name="Portefeuille", value=f"**{wallet['coins']:,}** 🪙")
    embed.add_field(name="Banque", value=f"**{wallet['bank']:,}** 🏦")
    embed.add_field(name="Total", value=f"**{wallet['coins'] + wallet['bank']:,}** 💎")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="daily", description="Réclame ta récompense journalière.")
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

@bot.tree.command(name="work", description="Travaille (cooldown 1h).")
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

@bot.tree.command(name="deposit", description="Dépose des coins à la banque.")
async def deposit(interaction: discord.Interaction, montant: int):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid)
    if montant <= 0 or montant > wallet['coins']:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
    e[gid][uid]['coins'] -= montant; e[gid][uid]['bank'] += montant; seco(e)
    await interaction.response.send_message(f"🏦 +**{montant}** 🪙 en banque.", ephemeral=True)

@bot.tree.command(name="withdraw", description="Retire des coins de la banque.")
async def withdraw(interaction: discord.Interaction, montant: int):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid)
    if montant <= 0 or montant > wallet['bank']:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
    e[gid][uid]['bank'] -= montant; e[gid][uid]['coins'] += montant; seco(e)
    await interaction.response.send_message(f"💸 +**{montant}** 🪙 retirés.", ephemeral=True)

@bot.tree.command(name="gamble", description="Parie tes coins (50/50).")
async def gamble(interaction: discord.Interaction, montant: int):
    gid = str(interaction.guild.id); uid = str(interaction.user.id)
    e, wallet = get_wallet(gid, uid)
    if montant <= 0 or montant > wallet['coins']:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
    win = random.random() > 0.5
    e[gid][uid]['coins'] += montant if win else -montant; seco(e)
    embed = discord.Embed(title="🎰 Gagné !" if win else "🎰 Perdu !", description=f"{'+'if win else '-'}**{montant}** 🪙", color=discord.Color.green() if win else discord.Color.red())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="give", description="Donne des coins à un autre membre.")
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

@bot.tree.command(name="lb", description="Top 10 économie.")
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
@bot.tree.command(name="remind", description="Crée un rappel.")
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

@bot.tree.command(name="say", description="Fait parler le bot (owner).")
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

@bot.tree.command(name="flip", description="Pile ou face.")
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

@bot.tree.command(name="help", description="Affiche toutes les commandes du bot.")
@app_commands.choices(categorie=[
    app_commands.Choice(name="Setup", value="⚙️ Setup"),
    app_commands.Choice(name="Modération", value="🔨 Modération"),
    app_commands.Choice(name="Invitations", value="📨 Invitations"),
    app_commands.Choice(name="Économie", value="💰 Économie"),
    app_commands.Choice(name="Niveaux", value="⭐ Niveaux"),
    app_commands.Choice(name="Fun", value="🎮 Fun"),
    app_commands.Choice(name="Utils", value="🛠️ Utils")
])
async def help_cmd(interaction: discord.Interaction, categorie: app_commands.Choice[str] = None):
    categories = {
        "⚙️ Setup": [("`/setup_rules`","Règles"),("`/setup_ticket`","Tickets"),("`/set_welcome`","Bienvenue"),("`/set_leave`","Départ"),("`/set_logs`","Logs global"),("`/set_modlog`","Logs modération"),("`/set_sugg`","Suggestions"),("`/set_levelchan`","Level-up"),("`/set_autorole`","Auto-rôle"),("`/set_levelrole`","Rôle niveau"),("`/set_maxtickets`","Max tickets"),("`/antispam`","Anti-spam"),("`/banword`","Mot interdit")],
        "🔨 Modération": [("`/ban`","Ban"),("`/unban`","Unban ID"),("`/kick`","Kick"),("`/mute`","Mute"),("`/unmute`","Unmute"),("`/warn`","Warn"),("`/unwarn`","Unwarn dernier"),("`/warns`","Voir warns"),("`/clearwarns`","Purger warns"),("`/purge`","Purger MSG"),("`/slowmode`","Slowmode"),("`/lock`","Lock salon"),("`/unlock`","Unlock salon")],
        "📨 Invitations": [("`/invites`","Invitations perso"),("`/topinvites`","Top inviteurs")],
        "💰 Économie": [("`/balance`","Solde"),("`/daily`","Quotidien"),("`/work`","Travailler"),("`/deposit`","Déposer"),("`/withdraw`","Retirer"),("`/gamble`","Parier"),("`/give`","Donner"),("`/lb`","Top économie")],
        "⭐ Niveaux": [("`/rank`","Niveau"),("`/leveltop`","Top niveaux")],
        "🎮 Fun": [("`/poll`","Sondage"),("`/giveaway`","Giveaway"),("`/remind`","Rappel"),("`/flip`","Pile/Face"),("`/roll`","Dés"),("`/8ball`","Magique")],
        "🛠️ Utils": [("`/embed`","Embed"),("`/userinfo`","Infos User"),("`/serverinfo`","Infos Serveur"),("`/avatar`","Avatar"),("`/ping`","Ping"),("`/note`","Ajouter Note"),("`/notes`","Mes Notes"),("`/say`","Dire")],
    }
    
    if categorie:
        cat_name = categorie.value
        embed = discord.Embed(title=f"❓ {cat_name}", color=0x5865F2)
        for cmd, desc in categories[cat_name]: 
            # C'est ici que la magie s'opère : inline=True crée les colonnes !
            embed.add_field(name=cmd, value=desc, inline=True)
    else:
        embed = discord.Embed(title="❓ Aide Administrateur", description="Utilise `/help [catégorie]` pour les détails.", color=0x5865F2, timestamp=discord.utils.utcnow())
        for cat_name, cmds_list in categories.items():
            embed.add_field(name=cat_name, value=f"`{len(cmds_list)}` commandes", inline=True)
            
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================================================
# 13. DASHBOARD API FLASK (Tourne en arrière-plan) - SÉCURISÉE 🔒
# ============================================================
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading

app_flask = Flask(__name__)
CORS(app_flask, origins=['*'])

# 🔐 Récupération du mot de passe
DASHBOARD_PASSWORD = os.getenv('DASHBOARD_PASSWORD', 'admin123')

@app_flask.before_request
def require_auth():
    if request.method == 'OPTIONS':
        return
    if request.path == '/api/login':
        return
    provided_pass = request.headers.get('Authorization')
    if provided_pass != DASHBOARD_PASSWORD:
        return jsonify({'success': False, 'error': 'Non autorisé. Mot de passe invalide.'}), 401

@app_flask.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    if data.get('password') == DASHBOARD_PASSWORD:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Mot de passe incorrect'}), 401

@app_flask.route('/api/test/welcome/<guild_id>', methods=['POST'])
def api_test_welcome(guild_id):
    g = bot.get_guild(int(guild_id))
    if g and g.owner: asyncio.run_coroutine_threadsafe(send_welcome(g.owner, g, force=True), bot.loop)
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
def get_guilds(): return jsonify([{'id': str(g.id), 'name': g.name, 'member_count': g.member_count} for g in bot.guilds])

@app_flask.route('/api/config/<guild_id>', methods=['GET'])
def get_config(guild_id): return jsonify(cfg().get(guild_id, {}))

@app_flask.route('/api/config/<guild_id>', methods=['POST'])
def update_config(guild_id):
    c = cfg()
    if guild_id not in c: c[guild_id] = {}
    c[guild_id].update(request.json); scfg(c)
    return jsonify({'success': True, 'config': c[guild_id]})

@app_flask.route('/api/stats/<guild_id>')
def get_stats(guild_id):
    s = stats(); e = eco(); l = lvl(); w = wrn(); inv_data = inv()
    gs = s.get(guild_id, {}); ge = e.get(guild_id, {}); gw = w.get(guild_id, {}); gi = inv_data.get(guild_id, {})
    total_coins = sum(v.get('coins',0)+v.get('bank',0) for v in ge.values())
    total_warns = sum(len(v) for v in gw.values())
    top_inv = max(gi.items(), key=lambda x: x[1].get('count',0), default=(None,{'count':0}))
    open_tickets = 0
    g = bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
    if g: open_tickets = sum(1 for ch in g.text_channels if ch.name.startswith('ticket-'))
    return jsonify({**gs, 'total_coins_circulating': total_coins, 'total_warns': total_warns,
                    'active_members_economy': len(ge), 'active_members_levels': len(l.get(guild_id,{})),
                    'top_inviter_count': top_inv[1].get('count',0), 'open_tickets': open_tickets})

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
def get_invites_api(guild_id): return jsonify(inv().get(guild_id, {}))

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

# /!\ TRÈS IMPORTANT : Le host est 0.0.0.0 pour l'hébergement web /!\
# Tout à la fin de bot.py
def run_flask():
    # Render donne son port via la variable d'environnement 'PORT'
    port = int(os.environ.get("PORT"
    , 5000))
    app_flask.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)