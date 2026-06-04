const API = 'https://admin-tycoon-bot-2spd.onrender.com/api'; // CHANGER ICI PAR L'URL DISCLOUD QUAND LE BOT SERA HÉBERGÉ
let currentGuild = null;
let guildChannels = [];
let guildRoles = [];
let currentConfig = {};
let rrPairs = [];

const originalFetch = window.fetch;

// 1. On intercepte TOUTES les requêtes API pour y glisser le mot de passe
window.fetch = async function() {
    let [resource, config] = arguments;
    if(config === undefined) config = {};
    if(config.headers === undefined) config.headers = {};
    config.headers['Authorization'] = localStorage.getItem('dash_pass') || '';
    return await originalFetch(resource, config);
};

// 2. La fonction de connexion
async function tryLogin() {
    const pass = document.getElementById('loginPass').value;
    localStorage.setItem('dash_pass', pass);
    const res = await fetch(`${API}/login`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: pass})});
    
    if(res.ok) {
        document.getElementById('loginOverlay').style.display = 'none';
        init(); // Lance le dashboard
    } else {
        alert("❌ Mot de passe incorrect !");
        localStorage.removeItem('dash_pass');
    }
}

function toast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.textContent = (type === 'success' ? '✅ ' : '❌ ') + msg;
  t.className = `show ${type}`;
  setTimeout(() => { t.className = ''; }, 3000);
}

function showPage(name, el = null) {
  localStorage.setItem('activeTab', name);
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  
  document.getElementById('page-' + name).classList.add('active');
  
  if(el) {
      el.classList.add('active');
  } else {
      let items = document.querySelectorAll('.nav-item');
      items.forEach(i => { if(i.getAttribute('onclick').includes(name)) i.classList.add('active'); });
  }

  if (currentGuild) {
    if (name === 'overview') loadStats();
    if (name === 'warns') loadWarns();
    if (name === 'economy') loadEconomy();
    if (name === 'invites') { 
        loadInvites(); 
        loadJoinedMembers(); 
    }
    if (name === 'reactionroles') { populateSelects(); loadReactionRoles(); }
    if (name === 'channels' || name === 'roles' || name === 'automod' || name === 'messages' || name === 'create') populateSelects();
    if (name === 'welcome' || name === 'rules') loadCurrentConfig();
  }
}

async function init() {
  try {
    const res = await fetch(`${API}/guilds`);
    const guilds = await res.json();
    const sel = document.getElementById('guildSelect');
    sel.innerHTML = guilds.map(g => `<option value="${g.id}">${g.name} (${g.member_count} membres)</option>`).join('');

    if (guilds.length > 0) {
      currentGuild = guilds[0].id;
      document.getElementById('botName').textContent = 'Bot connecté ✓';
      document.getElementById('statusDot').classList.remove('offline');
      document.getElementById('apiUrlDisplay').textContent = API.replace('/api', '');
      await loadGuild();
      
      const active = localStorage.getItem('activeTab') || 'overview';
      showPage(active, null);
    }
  } catch (e) {
    document.getElementById('botName').textContent = 'Hors ligne';
    document.getElementById('statusDot').classList.add('offline');
    document.getElementById('apiUrlDisplay').textContent = 'API injoignable';
    toast('Impossible de se connecter à l\'API.', 'error');
  }
}

async function loadGuild() {
  currentGuild = document.getElementById('guildSelect').value;
  if (!currentGuild) return;

  // 1. IL FAUT CHARGER LA CONFIGURATION EN PREMIER
  // Comme ça, le bot sait quels salons étaient déjà sauvegardés.
  await loadCurrentConfig(); 
  
  // 2. ENSUITE ON REMPLIT LES MENUS
  // Le script va utiliser la config chargée juste au-dessus pour mettre "selected" au bon endroit.
  await populateSelects();
  
  // 3. Et enfin on charge les stats
  await loadStats();
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

    document.getElementById('msg_channel').innerHTML = chOpt('');
    document.getElementById('poll_channel').innerHTML = chOpt('');
    document.getElementById('rrChannel').innerHTML = chOpt('');
    
    if (document.getElementById('create_ch_cat')) {
        document.getElementById('create_ch_cat').innerHTML = catOpt;
    }

    document.getElementById('autoRole').innerHTML = rOpt('auto_role');
    document.getElementById('levelRole').innerHTML = rOpt('');
    // Injecte dans TOUS les menus
    document.getElementById('ch_welcome').innerHTML = chOpt('welcome_channel');
    document.getElementById('ch_leave').innerHTML = chOpt('leave_channel');
    document.getElementById('ch_suggestions').innerHTML = chOpt('suggestion_channel');

    // 🟢 On convertit tout en String pour que le menu puisse comparer proprement
    const exSelect = document.getElementById('excludedLevelChannels');
    const excluded = (currentConfig.excluded_level_channels || []).map(String); 

    exSelect.innerHTML = guildChannels.map(c => 
        `<option value="${c.id}" ${excluded.includes(String(c.id)) ? 'selected' : ''}>#${c.name}</option>`
    ).join('');

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
    const select = document.getElementById('excludedLevelChannels');
    // On récupère tous les IDs sélectionnés sous forme de tableau de nombres
    const selected = Array.from(select.selectedOptions).map(option => parseInt(option.value));
    
    await saveConfig({ excluded_level_channels: selected });
    toast('Exclusions mises à jour !');
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

async function saveExcludedChannels() {
    const select = document.getElementById('excludedLevelChannels');
    // 🟢 Plus de parseInt ici non plus !
    const selected = Array.from(select.selectedOptions).map(option => option.value);
    
    await saveConfig({ excluded_level_channels: selected });
    toast('Exclusions sauvegardées !');
}

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
  document.getElementById('rrPairsList').innerHTML = rrPairs.map((p, i) =>
    `<div style="display:flex;gap:10px;margin-bottom:10px;align-items:center">
      <input type="text" placeholder="🎮 emoji" value="${p.emoji}" oninput="rrPairs[${i}].emoji=this.value" style="width:100px;flex-shrink:0">
      <select onchange="rrPairs[${i}].role_id=this.value" style="flex:1">
        <option value="">Choisir un rôle</option>
        ${guildRoles.map(r=>`<option value="${r.id}" ${p.role_id==r.id?'selected':''}>${r.name}</option>`).join('')}
      </select>
      <button class="btn btn-danger" style="padding:6px 10px;font-size:12px" onclick="removeRRPair(${i})">✕</button>
    </div>`
  ).join('');
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
  const rr = currentConfig.reaction_roles || {};
  const c = document.getElementById('rrList');
  if (!Object.keys(rr).length) return c.innerHTML = `<p style="color:var(--text-muted)">Aucun reaction role</p>`;
  c.innerHTML = Object.entries(rr).map(([k, rId]) => {
    const parts = k.split('_'); const emoji = parts.slice(1).join('_'); const role = guildRoles.find(r => r.id == rId);
    return `<div class="rr-item"><div class="rr-emoji">${emoji}</div><div class="rr-info"><strong>${role?role.name:rId}</strong><small>Msg: ${parts[0]}</small></div><button class="btn btn-danger" onclick="removeRR('${k}')">✕</button></div>`;
  }).join('');
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
  const data = await (await fetch(`${API}/invites/${currentGuild}`)).json();
  const sorted = Object.entries(data).sort((a,b) => (b[1].count||0) - (a[1].count||0)).slice(0,20);
  document.getElementById('invitesTable').innerHTML = !sorted.length ? `<p>Aucune donnée</p>` : `<table><thead><tr><th>User ID</th><th>Invitations</th></tr></thead><tbody>`+sorted.map(([u,d])=>`<tr><td>${u}</td><td><span class="badge badge-green">${d.count} invites</span></td></tr>`).join('')+`</tbody></table>`;
}

async function loadJoinedMembers() {
    try {
        const response = await fetch(`${API}/joined_members/${currentGuild}`);
        const data = await response.json(); 
        
        const tbody = document.getElementById('joinedMembersBody');
        if (!tbody) return;
        tbody.innerHTML = ''; 

        // S'il n'y a pas de données
        if (Object.keys(data).length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;">Aucun membre n\'a rejoint via invitation depuis l\'activation du log.</td></tr>';
            return;
        }

        for (const [memberId, info] of Object.entries(data)) {
            const row = document.createElement('tr');
            
            // On s'assure de bien extraire l'info, même si c'est un ancien format
            let inviterId = 'Aucun';
            let isValid = true;

            if (typeof info === 'object') {
                inviterId = info.inviter_id || 'Aucun';
                isValid = info.is_valid !== false; // Si non défini, on considère True par défaut
            } else if (typeof info === 'string') {
                inviterId = info;
            }
            
            row.innerHTML = `
                <td>${memberId}</td>
                <td>${inviterId}</td>
                <td>${isValid ? '✅ Oui' : '⚠️ Faux compte'}</td>
            `;
            tbody.appendChild(row);
        }
    } catch(e) { 
        console.error("Erreur chargement membres:", e); 
    }
}

async function loadWarns() {
  const data = await (await fetch(`${API}/warns/${currentGuild}`)).json();
  const sorted = Object.entries(data).filter(([,w])=>w.length>0);
  document.getElementById('warnsTable').innerHTML = !sorted.length ? `<p>Aucun warn</p>` : `<table><thead><tr><th>User ID</th><th>Warns</th><th>Dernière raison</th><th>Action</th></tr></thead><tbody>`+sorted.map(([u,w])=>`<tr><td>${u}</td><td><span class="badge badge-red">${w.length}</span></td><td>${w[w.length-1].raison}</td><td><button class="btn btn-danger" style="padding:4px 10px; font-size:11px" onclick="popWarn('${u}')">−1 Warn</button></td></tr>`).join('')+`</tbody></table>`;
}
async function popWarn(uid) { await fetch(`${API}/warns/${currentGuild}/${uid}/pop`, {method:'POST'}); loadWarns(); toast('Warn retiré !'); }

async function loadEconomy() {
  const data = await (await fetch(`${API}/economy/${currentGuild}`)).json();
  const sorted = Object.entries(data).map(([u,d])=>[u,(d.coins||0)+(d.bank||0)]).sort((a,b)=>b[1]-a[1]).slice(0,20);
  document.getElementById('ecoTable').innerHTML = !sorted.length ? `<p>Aucune donnée</p>` : `<table><thead><tr><th>User ID</th><th>Total (💎)</th></tr></thead><tbody>`+sorted.map(([u,t],i)=>`<tr><td>${u}</td><td><strong>${t.toLocaleString()}</strong> 💎</td></tr>`).join('')+`</tbody></table>`;
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

document.addEventListener('DOMContentLoaded', async () => {
  ['welcomeTitle', 'welcomeMessage', 'welcomeColor', 'welcomeShowInviter'].forEach(id => { document.getElementById(id)?.addEventListener('input', updatePreview); });
  rrPairs = []; renderRRPairs();
  
  // Vérifie si un mot de passe est déjà enregistré
  if(localStorage.getItem('dash_pass')) {
      const res = await fetch(`${API}/login`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: localStorage.getItem('dash_pass')})});
      if(res.ok) {
          const overlay = document.getElementById('loginOverlay');
          if(overlay) overlay.style.display = 'none';
          init();
      } else {
          localStorage.removeItem('dash_pass');
      }
  }
});