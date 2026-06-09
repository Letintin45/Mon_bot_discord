// 1. GESTION DU TOKEN DISCORD AU CHARGEMENT DE LA PAGE
const fragment = new URLSearchParams(window.location.hash.slice(1));
const accessToken = fragment.get('access_token');
if (accessToken) {
    localStorage.setItem('discord_token', accessToken);
    window.history.replaceState(null, null, window.location.pathname); 
}

const API = 'https://admin-tycoon-bot-2spd.onrender.com/api';
let currentGuild = null;
let guildChannels = [];
let guildRoles = [];
let currentConfig = {};
let rrPairs = [];
let guildsData = []; 

const originalFetch = window.fetch;

// 2. INTERCEPTEUR : Ajoute le token Discord aux requêtes
window.fetch = async function() {
    let [resource, config] = arguments;
    if(config === undefined) config = {};
    if(config.headers === undefined) config.headers = {};
    
    const token = localStorage.getItem('discord_token');
    if (token) config.headers['Authorization'] = 'Bearer ' + token;
    
    return await originalFetch(resource, config);
};

// --- FONCTIONS UTILITAIRES (Elles avaient disparu !) ---
function toast(msg, type = 'success') {
    const t = document.getElementById('toast');
    if(!t) return;
    t.textContent = msg;
    t.style.background = type === 'error' ? '#ff3366' : '#00cc66';
    t.className = 'show';
    setTimeout(() => t.className = t.className.replace('show', ''), 3000);
}

function showPage(pageId, elem = null) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById('page-' + pageId);
    if (page) page.classList.add('active');

    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    if (elem) {
        elem.classList.add('active');
    } else {
        document.querySelectorAll('.nav-item').forEach(n => {
            if (n.getAttribute('onclick') && n.getAttribute('onclick').includes(`'${pageId}'`)) {
                n.classList.add('active');
            }
        });
    }
    localStorage.setItem('activeTab', pageId);

    // Rechargement des données selon la page affichée
    if (!currentGuild) return;
    if (pageId === 'reactionroles') {
        // Toujours recharger la config depuis l'API puis afficher
        fetch(`${API}/config/${currentGuild}`)
            .then(r => r.json())
            .then(cfg => {
                currentConfig = cfg;
                loadReactionRoles();
            })
            .catch(() => {
                document.getElementById('rrList').innerHTML = '<p style="color:#ff6b6b">❌ Erreur de connexion au bot.</p>';
            });
    } else if (pageId === 'invites') {
        loadInvites();
        loadJoinedMembers();
    } else if (pageId === 'warns') {
        loadWarns();
    } else if (pageId === 'economy') {
        loadEconomy();
    } else if (pageId === 'members') {
        loadMembersList();
    } else if (pageId === 'overview') {
        loadStats();
    }
}
// --------------------------------------------------------

// 3. INITIALISATION & CONNEXION
async function init() {
  try {
    const res = await fetch(`${API}/guilds`);
    if (!res.ok) throw new Error("Non autorisé");
    
    guildsData = await res.json();
    const sel = document.getElementById('guildSelect');
    sel.innerHTML = guildsData.map(g => `<option value="${g.id}">${g.name} (${g.member_count} membres)</option>`).join('');

    if (guildsData.length > 0) {
      document.getElementById('botName').textContent = 'Connecté avec Discord ✓';
      document.getElementById('statusDot').classList.remove('offline');
      document.getElementById('apiUrlDisplay').textContent = 'Accès sécurisé';
      await loadGuild();
      
      const active = localStorage.getItem('activeTab') || 'overview';
      showPage(active, null); // C'est ici que ça crashait !
    } else {
      toast("Vous n'êtes Administrateur/Modérateur sur aucun serveur avec ce bot.", "error");
    }
  } catch (e) {
    console.error("Erreur critique:", e);
    document.getElementById('botName').textContent = 'Hors ligne';
    document.getElementById('statusDot').classList.add('offline');
    document.getElementById('apiUrlDisplay').textContent = 'API injoignable';
    toast('Session expirée ou non connecté.', 'error');
    localStorage.removeItem('discord_token');
    document.getElementById('loginOverlay').style.display = 'flex';
  }
}

// 4. GESTION DES PERMISSIONS
function applyPermissions() {
    const currentGuildData = guildsData.find(g => String(g.id) === String(currentGuild));
    if (!currentGuildData) return;

    const role = currentGuildData.role; 
    const adminOnlyItems = document.querySelectorAll('.admin-only'); 
    
    if (role === 'modo') {
        adminOnlyItems.forEach(el => el.style.display = 'none');
        const adminTabs = ['welcome', 'rules', 'channels', 'roles', 'automod', 'reactionroles', 'create'];
        if (adminTabs.includes(localStorage.getItem('activeTab'))) {
            showPage('overview');
        }
    } else {
        adminOnlyItems.forEach(el => el.style.display = 'block');
    }
}

async function loadGuild() {
  currentGuild = document.getElementById('guildSelect').value;
  if (!currentGuild) return;

  applyPermissions();          // Gardé (de la fonction 1)
  await loadCurrentConfig();   // Gardé (Doit être en premier comme le disait la fonction 2)
  await populateSelects();     // Gardé
  await loadStats();           // Gardé
  await loadMembersList();     // Gardé (de la fonction 1)
}

async function populateSelects() {
  try {
    const [chRes, rRes, catRes] = await Promise.all([
        fetch(`${API}/guild/${currentGuild}/channels`), 
        fetch(`${API}/guild/${currentGuild}/roles`),
        fetch(`${API}/guild/${currentGuild}/categories`)
    ]);
    guildChannels = await chRes.json();
    guildRoles = await rRes.json();
    const guildCats = await catRes.json();

    const chOpt = (id) => `<option value="">Aucun</option>` + guildChannels.map(c => `<option value="${c.id}" ${id && currentConfig[id] && String(currentConfig[id]) === String(c.id) ? 'selected' : ''}>#${c.name}</option>`).join('');
    const rOpt = (id) => `<option value="">Aucun</option>` + guildRoles.map(r => `<option value="${r.id}" ${id && currentConfig[id] && String(currentConfig[id]) === String(r.id) ? 'selected' : ''}>${r.name}</option>`).join('');
    const catOpt = `<option value="">Aucune catégorie</option>` + guildCats.map(c => `<option value="${c.id}">${c.name}</option>`).join('');

    document.getElementById('ch_welcome').innerHTML = chOpt('welcome_channel');
    document.getElementById('ch_leave').innerHTML = chOpt('leave_channel');
    document.getElementById('ch_logs').innerHTML = chOpt('log_channel');
    document.getElementById('ch_modlog').innerHTML = chOpt('mod_log_channel');
    document.getElementById('ch_suggestions').innerHTML = chOpt('suggestion_channel');
    document.getElementById('ch_levels').innerHTML = chOpt('level_channel');
    document.getElementById('ch_leaderboard').innerHTML = chOpt('live_lb_channel');
    if (currentConfig.lb_sort_by) document.getElementById('lb_sort_by').value = currentConfig.lb_sort_by;
    if (currentConfig.lb_interval) document.getElementById('lb_interval').value = currentConfig.lb_interval;

    document.getElementById('msg_channel').innerHTML = chOpt('');
    document.getElementById('poll_channel').innerHTML = chOpt('');
    document.getElementById('rrChannel').innerHTML = chOpt('');
    
    if (document.getElementById('create_ch_cat')) {
        document.getElementById('create_ch_cat').innerHTML = catOpt;
    }

    document.getElementById('autoRole').innerHTML = rOpt('auto_role');
    document.getElementById('levelRole').innerHTML = rOpt('');

    // Remplir le dropdown checkboxes d'exclusion XP
    renderExcludedDropdown(guildChannels, (currentConfig.excluded_level_channels || []).map(String));

    renderLevelRoles();
  } catch(e) {}
}

async function refreshAll() { await loadGuild(); toast('Données rafraîchies !'); }

async function loadStats() {
  try {
    const res = await fetch(`${API}/stats/${currentGuild}`);
    const data = await res.json();
    document.getElementById('statsGrid').innerHTML = `
      <div class="stat-card"><span class="stat-icon">💬</span><div class="stat-value">${data.messages_total || 0}</div><div class="stat-label">Messages totaux</div></div>
      <div class="stat-card"><span class="stat-icon">📥</span><div class="stat-value">${data.members_joined || 0}</div><div class="stat-label">Membres rejoints</div></div>
      <div class="stat-card"><span class="stat-icon">🎫</span><div class="stat-value">${data.tickets_total || 0}</div><div class="stat-label">Tickets créés</div></div>
      <div class="stat-card"><span class="stat-icon">🔓</span><div class="stat-value">${data.open_tickets || 0}</div><div class="stat-label">Tickets ouverts</div></div>
      <div class="stat-card"><span class="stat-icon">💰</span><div class="stat-value">${data.total_coins_circulating || 0}</div><div class="stat-label">Coins en circulation</div></div>
      <div class="stat-card"><span class="stat-icon">⚠️</span><div class="stat-value">${data.total_warns || 0}</div><div class="stat-label">Warns actifs</div></div>
      <div class="stat-card"><span class="stat-icon">👥</span><div class="stat-value">${data.active_members_economy || 0}</div><div class="stat-label">Membres actifs éco</div></div>
      <div class="stat-card"><span class="stat-icon">📨</span><div class="stat-value">${data.top_inviter_count || 0}</div><div class="stat-label">Record invitations</div></div>
      <div class="stat-card" style="border:1px solid #00e5ff; background: rgba(0,229,255,0.05);"><span class="stat-icon">🎮</span><div class="stat-value">${data.total_game_players || 0}</div><div class="stat-label" style="color:#00e5ff;">Comptes Jeu Créés</div></div>
      <div class="stat-card" style="border:1px solid #00e5ff; background: rgba(0,229,255,0.05);"><span class="stat-icon">💶</span><div class="stat-value">${Number(data.total_game_money || 0).toLocaleString()} €</div><div class="stat-label" style="color:#00e5ff;">Argent Global (Jeu)</div></div>    
    `;
  } catch(e) {}
}

async function loadCurrentConfig() {
  try {
    const res = await fetch(`${API}/config/${currentGuild}`);
    currentConfig = await res.json();

    document.getElementById('welcomeTitle').value = currentConfig.welcome_title || '';
    document.getElementById('welcomeColor').value = currentConfig.welcome_color || '00bfff';
    document.getElementById('welcomeMessage').value = currentConfig.welcome_message || '';
    document.getElementById('welcomeIgnoreBots').checked = currentConfig.ignore_bots_welcome !== false;
    document.getElementById('welcomeShowInviter').checked = currentConfig.show_inviter !== false;
    document.getElementById('welcomeOnVerification').checked = currentConfig.welcome_after_rules || false;
    document.getElementById('minAccountAge').value = currentConfig.min_account_age || 0;

    document.getElementById('rulesTitle').value = currentConfig.rules_title || '';
    document.getElementById('rulesText').value = currentConfig.rules_text || '';
    document.getElementById('ticketMax').value = currentConfig.ticket_max_open || 0;
    document.getElementById('ticketPanelTitle').value = currentConfig.ticket_panel_title || '';
    document.getElementById('ticketPanelDesc').value = currentConfig.ticket_panel_desc || '';
    document.getElementById('ticketActiveTitle').value = currentConfig.ticket_active_title || '';
    document.getElementById('ticketActiveDesc').value = currentConfig.ticket_active_desc || '';
    
    document.getElementById('suggPanelTitle').value = currentConfig.sugg_panel_title || '';
    document.getElementById('suggPanelDesc').value = currentConfig.sugg_panel_desc || '';

    document.getElementById('antiSpamToggle').checked = currentConfig.anti_spam || false;
    renderBannedWords(currentConfig.banned_words || []);
    updatePreview();
  } catch(e) {}
}



async function saveExcludedChannels() {
    await saveConfig({ excluded_level_channels: excludedChannelIds });
    updateExcludedDropdownLabel(excludedChannelIds);
    toast('Exclusions sauvegardées !');
}

async function createDiscordItem(type) {
  let payload = { guild_id: currentGuild, type: type };
  
  if (type === 'category') {
    payload.name = document.getElementById('create_cat_name').value;
    if (!payload.name) return toast('Nom requis', 'error');
  } else if (type === 'channel') {
    payload.name = document.getElementById('create_ch_name').value;
    payload.category_id = document.getElementById('create_ch_cat').value;
    if (!payload.name) return toast('Nom requis', 'error');
  } else if (type === 'role') {
    payload.name = document.getElementById('create_role_name').value;
    payload.color = document.getElementById('create_role_color').value;
    if (!payload.name) return toast('Nom requis', 'error');
  }

  try {
    await fetch(`${API}/create_discord`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
    toast('Création réussie sur Discord !');
    setTimeout(() => populateSelects(), 1000);
  } catch(e) { toast('Erreur', 'error'); }
}

function updatePreview() {
  if(!document.getElementById('previewTitle')) return;
  document.getElementById('previewTitle').textContent = document.getElementById('welcomeTitle').value || '⚡ Bienvenue !';
  document.getElementById('previewDesc').textContent = (document.getElementById('welcomeMessage').value || 'Salut {user} ! Tu es notre {count}ème membre ! 🎉').replace('{user}', '@NouvelUtilisateur').replace('{username}', 'NouvelUtilisateur').replace('{count}', '42').replace('{server}', 'Mon Serveur');
  document.querySelector('.preview-box').style.borderLeftColor = '#' + (document.getElementById('welcomeColor').value || '00bfff');
  document.getElementById('previewFooter').style.display = document.getElementById('welcomeShowInviter').checked ? 'block' : 'none';
}

async function saveWelcomeConfig() {
  // ✅ Tous les champs envoyés, même vides
  const patch = {
    ignore_bots_welcome: document.getElementById('welcomeIgnoreBots').checked,
    show_inviter:        document.getElementById('welcomeShowInviter').checked,
    welcome_after_rules: document.getElementById('welcomeOnVerification').checked,
    min_account_age:     parseInt(document.getElementById('minAccountAge').value) || 0,
    welcome_title:       document.getElementById('welcomeTitle').value,
    welcome_color:       document.getElementById('welcomeColor').value,
    welcome_message:     document.getElementById('welcomeMessage').value,
  };
  await saveConfig(patch);
  updatePreview();
  toast('Config Bienvenue sauvegardée !');
}

async function testWelcome() {
    try { await fetch(`${API}/test/welcome/${currentGuild}`, { method: 'POST' }); toast('Message envoyé !'); } catch(e) { toast('Erreur.', 'error'); }
}

async function saveRules() {
  // ✅ On envoie TOUJOURS les deux champs, même vides
  // (pour pouvoir effacer du contenu existant)
  const patch = {
    rules_title: document.getElementById('rulesTitle').value,
    rules_text:  document.getElementById('rulesText').value,
  };
  await saveConfig(patch);
  toast('Règles sauvegardées ! Refais /setup_rules dans Discord.');
}

async function saveChannels() {
  const patch = {};
  const channelFields = {
    welcome_channel:    document.getElementById('ch_welcome').value,
    leave_channel:      document.getElementById('ch_leave').value,
    log_channel:        document.getElementById('ch_logs').value,
    mod_log_channel:    document.getElementById('ch_modlog').value,
    suggestion_channel: document.getElementById('ch_suggestions').value,
    level_channel:      document.getElementById('ch_levels').value,
    live_lb_channel:    document.getElementById('ch_leaderboard').value, // <-- LA VIRGULE EST ICI !
    lb_sort_by:         document.getElementById('lb_sort_by').value,
    lb_interval:        parseFloat(document.getElementById('lb_interval').value)
  };
  
  // 🟢 On envoie le texte brut sans parseInt pour protéger l'ID Discord
  for (const [key, val] of Object.entries(channelFields)) {
    if (val && val !== '') patch[key] = val; 
  }
  
  // ticketMax est un petit nombre (ex: 10), donc parseInt est ok
  const maxT = parseInt(document.getElementById('ticketMax').value);
  if (!isNaN(maxT)) patch.ticket_max_open = maxT;
  
  await saveConfig(patch);
  toast('Salons & Limites sauvegardés !');
}

async function saveTicketText() {
  const patch = {
    ticket_panel_title: document.getElementById('ticketPanelTitle').value,
    ticket_panel_desc: document.getElementById('ticketPanelDesc').value,
    ticket_active_title: document.getElementById('ticketActiveTitle').value,
    ticket_active_desc: document.getElementById('ticketActiveDesc').value
  };
  await saveConfig(patch);
  toast('Textes des tickets sauvegardés ! Refaites la commande /config-tickets sur Discord.');
}

async function saveSuggText() {
  const patch = {
    sugg_panel_title: document.getElementById('suggPanelTitle').value,
    sugg_panel_desc: document.getElementById('suggPanelDesc').value
  };
  await saveConfig(patch);
  toast('Textes des suggestions sauvegardés ! Refaites la commande /config-suggestions sur Discord.');
}

async function addDefaultWords() {
    const mots = ["putain", "merde", "connard", "connasse", "salope", "salop", "enculé", "encule", "batard", "bâtard", "fdp", "tg", "ntm", "bite", "couille", "pute", "pd", "trouduc", "bouffon", "chier", "conne"];
    let current = currentConfig.banned_words || [];
    mots.forEach(m => { if(!current.includes(m)) current.push(m); });
    await saveConfig({ banned_words: current });
    renderBannedWords(current);
    toast('Liste par défaut ajoutée !');
}

// (doublon supprimé — saveExcludedChannels est définie plus haut)

async function saveAutoRole() {
  const val = document.getElementById('autoRole').value;
  if (val && val !== '') {
    await saveConfig({ auto_role: val }); // 🟢 Plus de parseInt
    toast('Auto-rôle ok !');
  } else {
    toast('Aucun rôle sélectionné', 'error');
  }
}

function renderLevelRoles() {
  const lr = currentConfig.level_roles || {};
  const c = document.getElementById('levelRolesTable');
  if (!Object.keys(lr).length) return c.innerHTML = `<div class="empty-state"><p>Aucun rôle par niveau</p></div>`;
  c.innerHTML = `<table><thead><tr><th>Niveau</th><th>Rôle</th><th>Action</th></tr></thead><tbody>` +
    Object.entries(lr).sort((a,b)=>a[0]-b[0]).map(([lvl, rId]) => {
      const role = guildRoles.find(r => r.id == rId);
      return `<tr><td><span class="badge badge-blue">Niv ${lvl}</span></td><td>${role ? role.name : rId}</td><td><button class="btn btn-danger" onclick="removeLevelRole('${lvl}')">✕</button></td></tr>`;
    }).join('') + `</tbody></table>`;
}

async function addLevelRole() {
  const lvl = document.getElementById('levelNum').value;
  const rId = document.getElementById('levelRole').value; // 🟢 Plus de parseInt
  if (!lvl || !rId) return toast('Remplis tout', 'error');
  if (!currentConfig.level_roles) currentConfig.level_roles = {};
  currentConfig.level_roles[lvl] = rId;
  await saveConfig({ level_roles: currentConfig.level_roles }); 
  renderLevelRoles(); 
  toast('Ajouté !');
}

async function removeLevelRole(lvl) { delete currentConfig.level_roles[lvl]; await saveConfig({ level_roles: currentConfig.level_roles }); renderLevelRoles(); }

async function saveAutomod() { await saveConfig({ anti_spam: document.getElementById('antiSpamToggle').checked }); toast('Automod maj !'); }

function renderBannedWords(w) {
  document.getElementById('bannedWordsList').innerHTML = w.map(x => `<span class="badge badge-red" style="padding:6px; font-size:12px">${x} <span style="cursor:pointer" onclick="removeBannedWord('${x}')">✕</span></span>`).join('');
}
async function addBannedWord() {
  const v = document.getElementById('newBannedWord').value.trim().toLowerCase();
  if(!v) return;
  const bw = currentConfig.banned_words || [];
  if(!bw.includes(v)) { bw.push(v); await saveConfig({ banned_words: bw }); renderBannedWords(bw); }
  document.getElementById('newBannedWord').value = '';
}
async function removeBannedWord(w) {
  currentConfig.banned_words = currentConfig.banned_words.filter(x => x !== w);
  await saveConfig({ banned_words: currentConfig.banned_words }); renderBannedWords(currentConfig.banned_words);
}

// ── REACTION ROLES MULTIPLES ──
function renderRRPairs() {
  const container = document.getElementById('rrPairsList');

  // Construire le HTML avec data-index pour éviter les conflits de guillemets
  container.innerHTML = rrPairs.map((p, i) =>
    `<div style="display:flex;gap:10px;margin-bottom:10px;align-items:center" data-pair="${i}">
      <input
        type="text"
        placeholder="emoji ex: 🎉"
        value="${p.emoji.replace(/"/g, '&quot;')}"
        data-index="${i}"
        data-type="emoji"
        style="width:120px;flex-shrink:0"
      >
      <select data-index="${i}" data-type="role" style="flex:1">
        <option value="">Choisir un rôle</option>
        ${guildRoles.map(r =>
          `<option value="${r.id}" ${String(p.role_id) === String(r.id) ? 'selected' : ''}>${r.name}</option>`
        ).join('')}
      </select>
      <button
        data-index="${i}"
        data-type="remove"
        class="btn btn-danger"
        style="padding:6px 10px;font-size:12px"
      >✕</button>
    </div>`
  ).join('');

  // Attacher les événements proprement APRÈS avoir injecté le HTML
  container.querySelectorAll('input[data-type="emoji"]').forEach(input => {
    input.addEventListener('input', function() {
      rrPairs[parseInt(this.dataset.index)].emoji = this.value;
    });
  });

  container.querySelectorAll('select[data-type="role"]').forEach(select => {
    select.addEventListener('change', function() {
      rrPairs[parseInt(this.dataset.index)].role_id = this.value;
    });
  });

  container.querySelectorAll('button[data-type="remove"]').forEach(btn => {
    btn.addEventListener('click', function() {
      rrPairs.splice(parseInt(this.dataset.index), 1);
      renderRRPairs();
    });
  });
}
function addRRPair() { rrPairs.push({ emoji: '', role_id: '' }); renderRRPairs(); }
function removeRRPair(i) { rrPairs.splice(i, 1); renderRRPairs(); }

async function createRRMessage() {
  const channel_id = document.getElementById('rrChannel').value;
  const title = document.getElementById('rrTitle').value || '🎭 Choisis tes rôles';
  const description = document.getElementById('rrDesc').value || 'Réagis pour obtenir un rôle !';
  const valid = rrPairs.filter(p=>p.emoji&&p.role_id);
  if (!channel_id || !valid.length) return toast('Salon ou paires invalides', 'error');
  try {
    await fetch(`${API}/reaction_roles_create`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ channel_id, guild_id: currentGuild, title, description, pairs: valid }) });
    rrPairs = []; renderRRPairs(); await loadCurrentConfig(); loadReactionRoles(); toast('Message RR créé !');
  } catch(e) { toast('Erreur', 'error'); }
}

async function loadReactionRoles() {
  const c = document.getElementById('rrList');
  c.innerHTML = '<p style="color:var(--text-muted)">Chargement...</p>';

  try {
    // Fetch frais depuis l'API pour avoir les données à jour
    const res = await fetch(`${API}/config/${currentGuild}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const freshConfig = await res.json();
    currentConfig = freshConfig;

    const rr = freshConfig.reaction_roles || {};

    if (!Object.keys(rr).length) {
      c.innerHTML = '<p style="color:var(--text-muted);padding:20px;text-align:center">Aucun reaction role configuré.</p>';
      return;
    }

    c.innerHTML = Object.entries(rr).map(([k, rId]) => {
      const parts = k.split('_');
      const msgId = parts[0];
      const emoji = parts.slice(1).join('_');
      const role = guildRoles.find(r => String(r.id) === String(rId));
      return `<div class="rr-item">
        <div class="rr-emoji">${emoji}</div>
        <div class="rr-info">
          <strong>${role ? role.name : '⚠️ Rôle ID: ' + rId}</strong>
          <small>Message ID: ${msgId}</small>
        </div>
        <button class="btn btn-danger" style="padding:5px 10px;font-size:12px" onclick="removeRR('${k}')">✕</button>
      </div>`;
    }).join('');
  } catch(e) {
    c.innerHTML = `<p style="color:#ff6b6b;padding:20px">❌ Erreur: ${e.message}</p>`;
    console.error('loadReactionRoles:', e);
  }
}
async function removeRR(k) { delete currentConfig.reaction_roles[k]; await saveConfig({ reaction_roles: currentConfig.reaction_roles }); loadReactionRoles(); }

// ── ENVOI DE MESSAGES ──
async function sendEmbedMessage() {
  const channel_id = document.getElementById('msg_channel').value;
  const title = document.getElementById('msg_title').value;
  const description = document.getElementById('msg_desc').value;
  const color = document.getElementById('msg_color').value || '0099ff';
  if(!channel_id || !title) return toast('Salon et Titre requis', 'error');
  await fetch(`${API}/send_message`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel_id, embed:{title,description,color}})});
  toast('Embed envoyé !');
}

async function sendPoll() {
  const channel_id = document.getElementById('poll_channel').value;
  const question = document.getElementById('poll_question').value;
  const options = ['poll_opt1','poll_opt2','poll_opt3','poll_opt4'].map(id=>document.getElementById(id).value).filter(Boolean);
  if(!channel_id || !question || options.length < 2) return toast('Il faut un salon, une question et 2 options minimum', 'error');
  await fetch(`${API}/create_poll`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel_id, question, options})});
  toast('Sondage créé !');
}

// ── DONNEES ──
async function loadInvites() {
  try {
    const res = await fetch(`${API}/invites/${currentGuild}`);
    const data = await res.json();
    const container = document.getElementById('invitesTable');

    // Cas debug : la table Supabase invites n'existe pas encore
    if (data.__debug__) {
      container.innerHTML = `<div style="color:var(--text-muted);padding:20px;text-align:center;">
        <div style="font-size:28px;margin-bottom:10px">📨</div>
        <p style="margin-bottom:8px">Aucune invitation enregistrée pour le moment.</p>
        <p style="font-size:12px;color:var(--text-dim)">Les données apparaîtront ici dès qu'un membre rejoindra via une invitation trackée.</p>
        <p style="font-size:11px;color:#ff6b6b;margin-top:8px">⚠️ Si le problème persiste, vérifie que la table <code>invites</code> existe dans ton Supabase bot (colonnes : <code>guild_id</code>, <code>data</code>).</p>
      </div>`;
      return;
    }

    // Filtrer les entrées avec count > 0
    const sorted = Object.entries(data)
      .filter(([, d]) => (d.count || 0) > 0)
      .sort((a, b) => (b[1].count || 0) - (a[1].count || 0))
      .slice(0, 20);

    if (!sorted.length) {
      container.innerHTML = `<div style="color:var(--text-muted);padding:20px;text-align:center;">
        <div style="font-size:28px;margin-bottom:10px">📨</div>
        <p>Aucune invitation valide enregistrée pour ce serveur.</p>
        <p style="font-size:12px;margin-top:8px">Les données apparaissent dès qu'un membre rejoint via une invitation trackée.</p>
      </div>`;
      return;
    }

    container.innerHTML = `<table style="width:100%">
      <thead><tr><th>User ID</th><th>Invitations vérifiées</th></tr></thead>
      <tbody>
        ${sorted.map(([u, d], i) => {
          const medals = ['🥇','🥈','🥉'];
          const medal = medals[i] || `${i+1}.`;
          return `<tr>
            <td><code style="font-size:12px">${u}</code></td>
            <td>${medal} <span class="badge badge-green">${d.count} invite${d.count > 1 ? 's' : ''}</span></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
  } catch(e) {
    document.getElementById('invitesTable').innerHTML = `<p style="color:var(--red)">❌ Erreur de chargement : ${e.message}</p>`;
    console.error('loadInvites:', e);
  }
}

async function loadJoinedMembers() {
    const tbody = document.getElementById('joinedMembersBody');
    if (!tbody) return;

    try {
        const response = await fetch(`${API}/joined_members/${currentGuild}`);
        const data = await response.json();

        tbody.innerHTML = '';

        if (!data || Object.keys(data).length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:16px">Aucun membre n\'a encore rejoint via invitation trackée.</td></tr>';
            return;
        }

        // Trier : les plus récents en premier (join_time décroissant)
        const entries = Object.entries(data).sort((a, b) => {
            const tA = typeof a[1] === 'object' ? (a[1].join_time || 0) : 0;
            const tB = typeof b[1] === 'object' ? (b[1].join_time || 0) : 0;
            return tB - tA;
        });

        for (const [memberId, info] of entries) {
            const row = document.createElement('tr');

            let inviterId = 'Aucun';
            let isValid = true;
            let joinDate = '';

            if (typeof info === 'object') {
                inviterId = info.inviter_id || 'Aucun';
                isValid = info.is_valid !== false;
                if (info.join_time) {
                    joinDate = new Date(info.join_time * 1000).toLocaleDateString('fr-FR');
                }
            } else if (typeof info === 'string') {
                inviterId = info;
            }

            const validBadge = isValid
                ? '<span class="badge badge-green">✅ Valide</span>'
                : '<span class="badge badge-red">⚠️ Faux compte</span>';

            row.innerHTML = `
                <td><code style="font-size:11px">${memberId}</code></td>
                <td><code style="font-size:11px">${inviterId}</code>${joinDate ? `<br><small style="color:var(--text-muted)">${joinDate}</small>` : ''}</td>
                <td>${validBadge}</td>
            `;
            tbody.appendChild(row);
        }
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--red);padding:16px">❌ Erreur de chargement</td></tr>`;
        console.error('loadJoinedMembers:', e);
    }
}

async function loadWarns() {
  try {
    const res = await fetch(`${API}/warns/${currentGuild}`);
    const data = await res.json();
    const sorted = Object.entries(data).filter(([,w]) => w.length > 0);
    document.getElementById('warnsTable').innerHTML = !sorted.length
      ? `<p style="color:var(--text-muted);padding:20px;text-align:center">Aucun warn actif.</p>`
      : `<table><thead><tr><th>User ID</th><th>Warns</th><th>Dernière raison</th><th>Action</th></tr></thead><tbody>`
        + sorted.map(([u,w]) => `<tr>
            <td>${u}</td>
            <td><span class="badge badge-red">${w.length}</span></td>
            <td>${w[w.length-1].raison}</td>
            <td><button class="btn btn-danger" style="padding:4px 10px;font-size:11px" onclick="popWarn('${u}')">−1 Warn</button></td>
          </tr>`).join('')
        + `</tbody></table>`;
  } catch(e) {
    document.getElementById('warnsTable').innerHTML = `<p style="color:var(--red)">❌ Erreur de chargement</p>`;
  }
}
async function popWarn(uid) { await fetch(`${API}/warns/${currentGuild}/${uid}/pop`, {method:'POST'}); loadWarns(); toast('Warn retiré !'); }

async function loadEconomy() {
  try {
    const res = await fetch(`${API}/economy/${currentGuild}`);
    const data = await res.json();
    const sorted = Object.entries(data)
      .map(([u,d]) => [u, (d.coins||0) + (d.bank||0)])
      .sort((a,b) => b[1]-a[1])
      .slice(0, 20);
    document.getElementById('ecoTable').innerHTML = !sorted.length
      ? `<p style="color:var(--text-muted);padding:20px;text-align:center">Aucune donnée d'économie.</p>`
      : `<table><thead><tr><th>User ID</th><th>Total (💎)</th></tr></thead><tbody>`
        + sorted.map(([u,t]) => `<tr><td>${u}</td><td><strong>${t.toLocaleString()}</strong> 💎</td></tr>`).join('')
        + `</tbody></table>`;
  } catch(e) {
    document.getElementById('ecoTable').innerHTML = `<p style="color:var(--red)">❌ Erreur de chargement</p>`;
  }
}

async function saveConfig(d) {
  try {
    const res = await fetch(`${API}/config/${currentGuild}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(d)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      toast(`Erreur API ${res.status}: ${err.error || 'inconnue'}`, 'error');
      return;
    }
    const json = await res.json();
    if (json.config) currentConfig = json.config;
    else currentConfig = { ...currentConfig, ...d };
  } catch(e) {
    toast('Erreur réseau – vérifie que le bot Render est en ligne', 'error');
    console.error('saveConfig error:', e);
  }
}

// ✅ Diagnostic rapide : ouvre /api/debug dans un onglet pour vérifier Supabase
function checkApi() {
  window.open(`${API}/debug`, '_blank');
}

// --- 👥 SYSTÈME GESTIONNAIRE DE MEMBRES ---
let allMembersData = [];
let selectedMemberId = null;

async function loadMembersList() {
  const container = document.getElementById('membersListContainer');
  try {
    const res = await fetch(`${API}/guild/${currentGuild}/members`);
    allMembersData = await res.json();
    renderMembersList(allMembersData);
  } catch (e) {
    container.innerHTML = "Erreur de chargement.";
  }
}

function renderMembersList(list) {
  const c = document.getElementById('membersListContainer');
  c.innerHTML = list.map(m => `
    <div style="display: flex; align-items: center; gap: 10px; padding: 10px; background: #111; border-radius: 6px; margin-bottom: 8px; cursor: pointer; border: 1px solid transparent; transition: 0.2s;"
         onmouseover="this.style.borderColor='#5865F2'" onmouseout="this.style.borderColor='transparent'"
         onclick="selectMember('${m.id}')">
      <img src="${m.avatar}" style="width: 32px; height: 32px; border-radius: 50%;">
      <div style="font-size: 14px; font-weight: 500;">${m.name}</div>
    </div>
  `).join('');
}

function filterMembers() {
  const q = document.getElementById('memberSearch').value.toLowerCase();
  const filtered = allMembersData.filter(m => m.name.toLowerCase().includes(q) || m.id.includes(q));
  renderMembersList(filtered);
}

function selectMember(id) {
  selectedMemberId = id;
  const m = allMembersData.find(x => x.id === id);
  if (!m) return;
  document.getElementById('memberDetailsPanel').style.display = 'block';
  document.getElementById('m_avatar').src = m.avatar;
  document.getElementById('m_name').textContent = m.name;
  document.getElementById('m_id').textContent = m.id;
  document.getElementById('m_coins').textContent = m.coins + " 🪙";
  document.getElementById('m_xp').textContent = m.xp + " XP";
  document.getElementById('m_warns').textContent = m.warns;
}

async function adminAction(action) {
  if (!selectedMemberId) return toast('Aucun membre sélectionné', 'error');
  const amount = parseInt(document.getElementById('m_amount').value) || 0;
  
  if (action !== 'clear_warns' && amount <= 0) return toast('Montant invalide', 'error');

  try {
    const res = await fetch(`${API}/admin/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ guild_id: currentGuild, user_id: selectedMemberId, action, amount })
    });
    const data = await res.json();
    if (data.success) {
      toast('✅ Action effectuée avec succès !');
      document.getElementById('m_amount').value = '';
      
      // On rafraîchit tout en fond pour mettre à jour l'affichage !
      await loadMembersList(); 
      selectMember(selectedMemberId); 
      loadEconomy();
      loadWarns();
    } else {
      toast(data.error || 'Erreur API', 'error');
    }
  } catch (e) {
    toast('Erreur de connexion', 'error');
  }
}



// ── DROPDOWN CHECKBOXES — EXCLUSION SALONS XP ──
// Variable centrale : source de vérité pour les exclusions
let excludedChannelIds = [];

function renderExcludedDropdown(channels, excludedIds) {
    excludedChannelIds = excludedIds.map(String); // sync avec la variable centrale
    const list = document.getElementById('excludedCheckboxList');
    if (!list) return;
    list.innerHTML = channels.map(c => {
        const isChecked = excludedChannelIds.includes(String(c.id));
        return `<label style="display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;transition:background 0.1s"
                    onmouseover="this.style.background='var(--surface3)'"
                    onmouseout="this.style.background='transparent'">
            <input type="checkbox" value="${c.id}" ${isChecked ? 'checked' : ''}
                onchange="onExcludedChange(this)"
                style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer;flex-shrink:0">
            <span style="font-size:13px">#${c.name}</span>
        </label>`;
    }).join('');
    updateExcludedDropdownLabel(excludedChannelIds);
}

function filterExcludedDropdown() {
    const q = document.getElementById('excludedSearch').value.toLowerCase();
    document.querySelectorAll('#excludedCheckboxList label').forEach(label => {
        const name = label.querySelector('span').textContent.toLowerCase();
        label.style.display = name.includes(q) ? 'flex' : 'none';
    });
}

function toggleExcludedDropdown() {
    const menu = document.getElementById('excludedDropdownMenu');
    const isOpen = menu.style.display !== 'none';
    menu.style.display = isOpen ? 'none' : 'block';
    if (!isOpen) document.getElementById('excludedSearch').focus();
}

function updateExcludedDropdownLabel(excludedIds) {
    const btn = document.getElementById('excludedDropdownLabel');
    if (!btn) return;
    const count = Array.isArray(excludedIds)
        ? excludedIds.length
        : document.querySelectorAll('#excludedCheckboxList input:checked').length;
    btn.textContent = count === 0
        ? 'Aucun salon exclu'
        : `${count} salon${count > 1 ? 's' : ''} exclu${count > 1 ? 's' : ''}`;
    btn.style.color = count > 0 ? 'var(--text)' : 'var(--text-muted)';
}

function onExcludedChange(cb) {
    if (!cb) return;
    const id = String(cb.value);
    if (cb.checked) {
        if (!excludedChannelIds.includes(id)) excludedChannelIds.push(id);
    } else {
        excludedChannelIds = excludedChannelIds.filter(x => x !== id);
    }
    updateExcludedDropdownLabel(excludedChannelIds);
}

function clearAllExcluded() {
    excludedChannelIds = [];
    document.querySelectorAll('#excludedCheckboxList input[type="checkbox"]').forEach(cb => cb.checked = false);
    updateExcludedDropdownLabel([]);
}

// Fermer le dropdown si on clique ailleurs
document.addEventListener('click', function(e) {
    const btn = document.getElementById('excludedDropdownBtn');
    const menu = document.getElementById('excludedDropdownMenu');
    if (menu && btn && !btn.contains(e.target) && !menu.contains(e.target)) {
        menu.style.display = 'none';
    }
});

document.addEventListener('DOMContentLoaded', async () => {
  ['welcomeTitle', 'welcomeMessage', 'welcomeColor', 'welcomeShowInviter'].forEach(id => { document.getElementById(id)?.addEventListener('input', updatePreview); });
  rrPairs = []; renderRRPairs();
  
  // Vérifie si un token Discord est présent
  if (localStorage.getItem('discord_token')) {
      const res = await fetch(`${API}/login`, {method: 'POST'});
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
          document.getElementById('loginOverlay').style.display = 'none';
          init();
      } else {
          localStorage.removeItem('discord_token');
          document.getElementById('loginOverlay').style.display = 'flex';
      }
  } else {
      document.getElementById('loginOverlay').style.display = 'flex';
  }
});


// ==========================================
// GESTION DU CLASSEMENT JEU 
// ==========================================

async function loadGamePlayers() {
    const tbody = document.getElementById('gamePlayersListBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:15px;">Chargement...</td></tr>';
    try {
        const res = await fetch(`${API}/game_players`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `Erreur ${res.status}`);
        }
        const players = await res.json();
        if (!players.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:15px;color:#888;">Aucun joueur trouvé.</td></tr>';
            return;
        }
        tbody.innerHTML = '';
        players.forEach((player, idx) => {
            const isExcluded = player.is_excluded === true;
            const isBanned   = player.is_banned   === true;
            let state = player.game_state || {};
            if (typeof state === 'string') { try { state = JSON.parse(state); } catch { state = {}; } }
            const money = (state.money || 0).toLocaleString('fr-FR');
            const level = state.level || 1;
            const safeUser = player.username.replace(/'/g, "\\'");

            const exclBadge    = isExcluded ? '<span class="badge badge-red">🔴 Exclu</span>' : '<span class="badge badge-green">🟢 Visible</span>';
            const exclBtnClass = isExcluded ? 'btn-success' : 'btn-danger';
            const exclBtnText  = isExcluded ? 'Réintégrer' : 'Exclure';
            const banBadge     = isBanned ? '<span class="badge badge-red">🔨 Banni</span>' : '<span class="badge" style="background:rgba(88,101,242,.15);color:var(--accent)">✅ Actif</span>';
            const banBtnClass  = isBanned ? 'btn-success' : 'btn-danger';
            const banBtnText   = isBanned ? '🔓 Débannir' : '🔨 Bannir';

            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #333';
            tr.innerHTML = `
                <td style="padding:10px;font-weight:bold;color:var(--accent)">${player.username}</td>
                <td style="padding:10px;">Niv ${level} — ${money} €</td>
                <td style="padding:10px;">${exclBadge}</td>
                <td style="padding:10px;">
                    <button class="btn ${exclBtnClass} btn-excl" data-username="${safeUser}" data-excluded="${isExcluded}"
                        style="padding:5px 10px;font-size:12px">${exclBtnText}</button>
                </td>
                <td style="padding:10px;">
                    ${banBadge}<br>
                    <button class="btn ${banBtnClass} btn-ban" data-username="${safeUser}" data-banned="${isBanned}"
                        style="padding:5px 10px;font-size:12px;margin-top:4px">${banBtnText}</button>
                </td>`;
            tbody.appendChild(tr);
        });

        // Attacher les events après injection pour éviter les conflits de guillemets
        tbody.querySelectorAll('.btn-excl').forEach(btn => {
            btn.addEventListener('click', () => toggleGameExclusion(btn.dataset.username, btn.dataset.excluded === 'true'));
        });
        tbody.querySelectorAll('.btn-ban').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.banned === 'true') unbanGamePlayer(btn.dataset.username);
                else banGamePlayer(btn.dataset.username);
            });
        });
    } catch (err) {
        console.error('loadGamePlayers:', err);
        toast(err.message || 'Erreur de connexion.', 'error');
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:#ff4757;padding:15px;">❌ ${err.message}</td></tr>`;
    }
}

async function toggleGameExclusion(username, currentState) {
    const newState = !currentState;
    if (!confirm(`Voulez-vous ${newState ? 'exclure' : 'réintégrer'} ${username} du classement ?`)) return;
    try {
        const res = await fetch(`${API}/game_players/exclude`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, is_excluded: newState })
        });
        if (!res.ok) throw new Error("Erreur API");
        toast(`${username} ${newState ? 'exclu du classement' : 'réintégré au classement'} !`);
        loadGamePlayers();
    } catch (err) {
        toast('Erreur lors de la modification.', 'error');
    }
}

async function banGamePlayer(username) {
    const raison = prompt(`Raison du ban pour "${username}" :`, "Non-respect des règles");
    if (raison === null) return;

    const dureeStr = prompt(`Durée du ban en heures (0 = permanent) :`, "0");
    if (dureeStr === null) return;
    const duree = Math.max(0, parseInt(dureeStr) || 0);
    const dureeLabel = duree > 0 ? `${duree}h` : 'permanent';

    if (!confirm(`Bannir "${username}" — ${dureeLabel} — Raison : "${raison}" ?`)) return;

    try {
        const res = await fetch(`${API}/game_players/ban`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, raison, duree_heures: duree })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Erreur API");
        toast(`🔨 ${username} banni (${dureeLabel}) !`);
        loadGamePlayers();
    } catch (err) {
        toast(err.message || 'Erreur lors du ban.', 'error');
    }
}

async function unbanGamePlayer(username) {
    if (!confirm(`Débannir "${username}" du jeu ?`)) return;
    try {
        const res = await fetch(`${API}/game_players/unban`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Erreur API");
        toast(`✅ ${username} débanni !`);
        loadGamePlayers();
    } catch (err) {
        toast(err.message || 'Erreur lors du déban.', 'error');
    }
}