/*
 * Plateau en direct : relie la page à l'API du moteur de jeu.
 *
 * - Interroge GET /api/partie/etat?since=<id> toutes les 1,5 s (polling).
 * - Affiche l'état reçu : bannière, chat, sièges, vote, panneaux de nuit.
 * - Envoie les actions du joueur (message, vote, action de nuit) en POST JSON.
 *
 * Tout l'état vient du serveur, qui ne renvoie que la vue autorisée du joueur :
 * ce script ne connaît jamais un rôle que le joueur n'a pas le droit de voir.
 * Les textes sont toujours insérés avec textContent (pas d'injection HTML).
 */
(function () {
  'use strict';

  var configEl = document.getElementById('live-config');
  if (!configEl) return;
  var CFG = JSON.parse(configEl.textContent);

  var NIGHT_PHASES = ['NIGHT_SEER', 'NIGHT_WOLVES', 'NIGHT_WITCH'];
  var CHAT_PHASES = ['DAWN', 'DAY_DEBATE', 'DAY_VOTE', 'VOTE_RESULT'];
  var ROLE_KEYS = { WEREWOLF: 'loup', SEER: 'voyante', WITCH: 'sorciere', VILLAGER: 'villageois' };
  var ROLE_INFO = {
    WEREWOLF: { icon: '🐺', quote: 'Un prédateur rôde parmi les habitants.' },
    SEER: { icon: '🔮', quote: 'Chaque nuit, un secret lui est révélé.' },
    WITCH: { icon: '🧪', quote: 'Ses fioles décident de la vie et de la mort.' },
    VILLAGER: { icon: '🌾', quote: 'Le cœur du village, sans pouvoir particulier.' },
  };
  var WHISPERS = [
    'La lune s\'étire sur les toits de Thiercelieux…',
    'Quelque part, un hurlement se perd entre les collines.',
    'Fermez les yeux : les loups ne voient que vos rêves.',
    'Demain, il vous faudra voter. Ce que la nuit fait, le vote défera.',
    'Les étoiles gardent les secrets que le village ignore.',
  ];

  var state = null;          // dernière vue reçue du serveur
  var lastMessageId = 0;     // curseur du polling
  var clockSkew = 0;         // heure serveur - heure locale (ms)
  var polling = false;
  var lastPhaseKey = null;   // phase + version : reconstruit les panneaux à chaque nouvelle phase
  var lastAnnouncement = '';
  var gameOverShown = false;
  var witchDraft = { heal: false, killId: null, killName: '' };
  var seerSelectedId = null;
  var witchKillCandidate = null;

  function byId(id) { return document.getElementById(id); }
  function has(list, value) { return list.indexOf(value) !== -1; }

  // Avatars affichés sur les sièges (attribués par le serveur, neutres).
  var AVATARS = {};
  document.querySelectorAll('.seat[data-player-id]').forEach(function (seat) {
    var avatar = seat.querySelector('.avatar');
    AVATARS[seat.getAttribute('data-player-id')] = avatar ? avatar.textContent.trim() : '🧑';
  });
  function avatarOf(id) { return AVATARS[String(id)] || '🧑'; }

  // ------------------------------------------------------------------ //
  //  Réseau                                                            //
  // ------------------------------------------------------------------ //

  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CFG.csrf_token,
        Accept: 'application/json',
      },
      body: JSON.stringify(body || {}),
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) throw new Error(data.error || 'Action refusée (' + response.status + ').');
        poll();
        return data;
      });
    });
  }

  function poll() {
    if (polling) return;
    polling = true;
    fetch(CFG.urls.state + '?since=' + lastMessageId, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(function (response) {
        if (response.status === 404) {
          window.location.reload(); // plus de partie : retour à l'écran de départ
          return null;
        }
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(function (data) {
        if (data) {
          hideToast('offline');
          render(data);
        }
      })
      .catch(function () {
        toast('Connexion au village perdue… nouvelle tentative.', 'offline');
      })
      .then(function () { polling = false; });
  }

  // ------------------------------------------------------------------ //
  //  Notifications                                                     //
  // ------------------------------------------------------------------ //

  var toastEl = document.createElement('div');
  toastEl.id = 'live-toast';
  toastEl.setAttribute('role', 'status');
  document.body.appendChild(toastEl);
  var toastTimer = null;

  function toast(text, kind) {
    toastEl.textContent = text;
    toastEl.dataset.kind = kind || 'info';
    toastEl.classList.add('is-visible');
    clearTimeout(toastTimer);
    if (kind !== 'offline') {
      toastTimer = setTimeout(function () { toastEl.classList.remove('is-visible'); }, 4000);
    }
  }

  function hideToast(kind) {
    if (toastEl.dataset.kind === kind) toastEl.classList.remove('is-visible');
  }

  function fail(error) { toast(error.message || String(error), 'error'); }

  function setStatus(el, text, active) {
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('night-status-active', Boolean(text) && active !== false);
  }

  // ------------------------------------------------------------------ //
  //  Rendu                                                             //
  // ------------------------------------------------------------------ //

  function render(data) {
    state = data;
    clockSkew = Date.parse(data.game.server_time) - Date.now();
    data.messages.forEach(appendMessage);

    var phaseKey = data.game.phase + ':' + data.game.version;
    var newPhase = phaseKey !== lastPhaseKey;
    lastPhaseKey = phaseKey;

    renderBanner(data);
    renderSeats(data);
    renderChatForm(data);
    renderVote(data);
    renderNight(data, newPhase);
    renderGameOver(data);
    tickTimers();
  }

  function isNight(data) { return has(NIGHT_PHASES, data.game.phase); }

  function renderBanner(data) {
    var d = data.display;
    var banner = byId('status-banner');
    if (banner) banner.setAttribute('data-phase', d.key);
    if (byId('status-icon')) byId('status-icon').textContent = d.icon;
    if (byId('status-phase')) byId('status-phase').textContent = d.label;
    if (byId('status-desc')) byId('status-desc').textContent = d.desc;
    if (byId('mj-line') && lastAnnouncement) byId('mj-line').textContent = lastAnnouncement;
    if (byId('board-status')) byId('board-status').textContent = d.label;
  }

  // ----- Messages ---------------------------------------------------- //

  function appendMessage(m) {
    if (m.id <= lastMessageId) return;
    lastMessageId = m.id;
    if (m.kind === 'ANNOUNCEMENT') {
      lastAnnouncement = m.content;
      appendAnnouncement(m);
    } else if (m.channel === 'WOLVES') {
      appendWolfMessage(m);
    } else {
      appendChatMessage(m);
    }
  }

  function scrollToEnd(feed) { feed.scrollTop = feed.scrollHeight; }

  function appendAnnouncement(m) {
    var feed = byId('chat-feed');
    if (!feed) return;
    var p = document.createElement('p');
    p.className = 'chat-announcement';
    p.textContent = '✦ ' + m.content;
    feed.appendChild(p);
    scrollToEnd(feed);
  }

  function appendChatMessage(m) {
    var feed = byId('chat-feed');
    if (!feed) return;
    var mine = m.author_id === CFG.me_id;

    var article = document.createElement('article');
    article.className = mine ? 'flex flex-row-reverse gap-3' : 'flex gap-3';

    var avatar = document.createElement('span');
    avatar.className = mine
      ? 'w-9 h-9 flex-shrink-0 grid place-items-center rounded-full text-base text-parchment-light bg-wood-800 border-2 border-gold shadow'
      : 'w-9 h-9 flex-shrink-0 grid place-items-center rounded-full text-base text-parchment-light bg-wood-800 border border-gold/60 shadow-inner';
    avatar.textContent = avatarOf(m.author_id);

    var bubble = document.createElement('div');
    bubble.className = mine
      ? 'flex-1 min-w-0 rounded-sm border-2 border-gold-dark bg-gradient-to-b from-[#f8edd4] to-[#ecd7ab] px-3 py-2'
      : 'flex-1 min-w-0 rounded-sm border border-ink/15 bg-white/25 px-3 py-2';

    var author = document.createElement('p');
    author.className = mine
      ? 'font-display text-[12px] uppercase tracking-[0.14em] text-blood text-right'
      : 'font-display text-[12px] uppercase tracking-[0.14em] text-ink-soft';
    author.textContent = mine ? m.author_name + ' · vous' : m.author_name;

    var content = document.createElement('p');
    content.className = 'mt-0.5 text-[15px] leading-snug text-ink';
    content.textContent = m.content;

    bubble.appendChild(author);
    bubble.appendChild(content);
    article.appendChild(avatar);
    article.appendChild(bubble);
    feed.appendChild(article);
    scrollToEnd(feed);
  }

  function appendWolfMessage(m) {
    var feed = byId('wolf-feed');
    if (!feed) return;
    var mine = m.author_id === CFG.me_id;
    var row = document.createElement('div');
    row.className = 'wolf-msg' + (mine ? ' wolf-msg-self' : '');
    var avatar = document.createElement('span');
    avatar.className = 'night-chip-avatar';
    avatar.textContent = avatarOf(m.author_id);
    var bubble = document.createElement('div');
    bubble.className = 'wolf-msg-bubble';
    var author = document.createElement('p');
    author.className = 'wolf-msg-author';
    author.textContent = mine ? m.author_name + ' · vous' : m.author_name;
    var content = document.createElement('p');
    content.className = 'wolf-msg-text';
    content.textContent = m.content;
    bubble.appendChild(author);
    bubble.appendChild(content);
    row.appendChild(avatar);
    row.appendChild(bubble);
    feed.appendChild(row);
    scrollToEnd(feed);
  }

  // ----- Sièges ------------------------------------------------------ //

  function seatOf(id) { return document.querySelector('.seat[data-player-id="' + id + '"]'); }

  function renderSeats(data) {
    data.players.forEach(function (p) {
      var seat = seatOf(p.id);
      if (!seat) return;
      seat.classList.toggle('seat-dead', !p.is_alive);
      var roleEl = seat.querySelector('.seat-role');
      if (roleEl && !p.is_me) {
        roleEl.textContent = p.role_label ? p.role_label : 'Rôle inconnu';
        roleEl.classList.toggle('seat-role-known', Boolean(p.role_label));
      }
      var seal = seat.querySelector('.role-seal');
      if (seal) {
        seal.textContent = p.role ? ROLE_INFO[p.role].icon : '?';
        seal.title = p.role_label || 'Rôle inconnu';
      }
    });
  }

  // ----- Chat public ------------------------------------------------- //

  function renderChatForm(data) {
    var input = byId('chat-input');
    var form = byId('chat-form');
    if (!input || !form) return;
    var open = data.me.is_alive && data.game.status !== 'FINISHED' && has(CHAT_PHASES, data.game.phase);
    input.disabled = !open;
    form.querySelector('button').disabled = !open;
    input.placeholder = !data.me.is_alive
      ? 'Les morts ne parlent plus…'
      : open ? 'Prenez la parole devant le village...' : 'Le village dort : la place est fermée.';
  }

  var chatForm = byId('chat-form');
  if (chatForm) {
    chatForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var input = byId('chat-input');
      var text = input.value.trim();
      if (!text) return;
      input.disabled = true;
      post(CFG.urls.message, { text: text, channel: 'PUBLIC' })
        .then(function () { input.value = ''; })
        .catch(fail)
        .then(function () {
          input.disabled = false;
          input.focus();
        });
    });
  }

  // ----- Vote de jour ------------------------------------------------ //

  function myTurn(data, action) {
    return data.turn.action === action && data.turn.expected && !data.turn.done;
  }

  function renderVote(data) {
    var voting = data.game.phase === 'DAY_VOTE';
    document.body.classList.toggle('vote-phase', voting);
    var canVote = voting && myTurn(data, 'vote');
    var alive = {};
    data.players.forEach(function (p) { alive[p.id] = p.is_alive; });

    document.querySelectorAll('.seat-vote-btn').forEach(function (btn) {
      var id = Number(btn.getAttribute('data-vote-target-id'));
      btn.disabled = !canVote || id === CFG.me_id || !alive[id];
    });
    var white = byId('vote-white-btn');
    if (white) white.disabled = !canVote;

    var status = byId('vote-status');
    if (!status) return;
    if (!voting) status.textContent = '';
    else if (!data.me.is_alive) status.textContent = 'Vous êtes mort : le village vote sans vous.';
    else if (data.turn.done) status.textContent = 'Votre vote est déposé. Le verdict tombera à la fin du vote.';
    else status.textContent = 'À vous de voter : choisissez un habitant ou votez blanc.';
  }

  function sendVote(targetId, label) {
    post(CFG.urls.vote, { target_id: targetId })
      .then(function () { toast(label); })
      .catch(fail);
  }

  document.querySelectorAll('.seat-vote-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      sendVote(Number(btn.getAttribute('data-vote-target-id')),
        'Vote contre ' + btn.getAttribute('data-vote-target-name') + ' enregistré.');
    });
  });
  var whiteBtn = byId('vote-white-btn');
  if (whiteBtn) whiteBtn.addEventListener('click', function () { sendVote(null, 'Vote blanc enregistré.'); });

  // ----- Nuit -------------------------------------------------------- //

  function others(data, filter) {
    return data.players.filter(function (p) {
      return p.is_alive && !p.is_me && (!filter || filter(p));
    });
  }

  function buildTargetGrid(container, players, selectedId, onSelect, disabled) {
    if (!container) return;
    container.textContent = '';
    players.forEach(function (p) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'night-target-chip' + (p.id === selectedId ? ' is-selected' : '');
      chip.disabled = Boolean(disabled);
      var avatar = document.createElement('span');
      avatar.className = 'night-chip-avatar';
      avatar.textContent = avatarOf(p.id);
      var label = document.createElement('span');
      label.textContent = p.name;
      chip.appendChild(avatar);
      chip.appendChild(label);
      chip.addEventListener('click', function () {
        if (chip.disabled) return;
        container.querySelectorAll('.night-target-chip').forEach(function (el) {
          el.classList.remove('is-selected');
        });
        chip.classList.add('is-selected');
        onSelect(p);
      });
      container.appendChild(chip);
    });
  }

  function openModal(id) { var m = byId(id); if (m) m.classList.add('night-modal-open'); }
  function closeModal(id) { var m = byId(id); if (m) m.classList.remove('night-modal-open'); }
  function closeNightModals() { ['seer-modal', 'witch-life-modal', 'witch-death-modal'].forEach(closeModal); }

  ['seer-modal', 'witch-life-modal', 'witch-death-modal', 'game-over-modal', 'new-game-modal'].forEach(function (id) {
    var modal = byId(id);
    if (!modal) return;
    modal.addEventListener('click', function (event) { if (event.target === modal) closeModal(id); });
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      closeNightModals();
      closeModal('game-over-modal');
      closeModal('new-game-modal');
    }
  });

  function renderNight(data, newPhase) {
    var night = isNight(data);
    document.body.classList.toggle('night-phase', night);
    var roleKey = data.me.is_alive ? ROLE_KEYS[data.me.role] : 'villageois';
    document.body.setAttribute('data-night-role', night ? roleKey : '');
    if (!night) closeNightModals();
    if (newPhase) {
      seerSelectedId = null;
      witchKillCandidate = null;
      witchDraft = { heal: false, killId: null, killName: '' };
    }
    if (data.me.role === 'SEER') renderSeer(data, newPhase);
    if (data.me.role === 'WEREWOLF') renderWolf(data, newPhase);
    if (data.me.role === 'WITCH') renderWitch(data, newPhase);
  }

  // Voyante
  function renderSeer(data, newPhase) {
    var openBtn = byId('seer-open-btn');
    var status = byId('seer-status');
    var turn = myTurn(data, 'seer');
    if (openBtn) openBtn.disabled = !turn;
    var visions = (data.private.inspections || []).map(function (i) {
      return i.target_name + ' : ' + i.role_label;
    });
    var history = visions.length ? ' Visions passées — ' + visions.join(' · ') + '.' : '';
    if (turn) setStatus(status, 'Votre œil peut s\'ouvrir : choisissez qui sonder.' + history);
    else if (data.game.phase === 'NIGHT_SEER' && !data.me.is_alive) setStatus(status, '', false);
    else setStatus(status, (data.turn.done ? 'Votre vision est accomplie pour cette nuit.' : 'Patientez jusqu\'à votre tour.') + history, false);

    if (newPhase && turn) {
      var scrutinize = byId('seer-scrutinize-btn');
      if (scrutinize) scrutinize.disabled = true;
      var zone = byId('seer-reveal-zone');
      if (zone) zone.hidden = true;
      var card = byId('seer-reveal-card');
      if (card) card.classList.remove('flipped');
      buildTargetGrid(byId('seer-targets'), others(data), null, function (p) {
        seerSelectedId = p.id;
        if (scrutinize) scrutinize.disabled = false;
      });
    }
  }

  var seerOpen = byId('seer-open-btn');
  if (seerOpen) seerOpen.addEventListener('click', function () { openModal('seer-modal'); });
  var seerClose = byId('seer-close-btn');
  if (seerClose) seerClose.addEventListener('click', function () { closeModal('seer-modal'); });
  var seerScrutinize = byId('seer-scrutinize-btn');
  if (seerScrutinize) {
    seerScrutinize.addEventListener('click', function () {
      if (!seerSelectedId) return;
      seerScrutinize.disabled = true;
      post(CFG.urls.night, { action: 'seer', target_id: seerSelectedId })
        .then(function (result) {
          var info = ROLE_INFO[result.role] || { icon: '❓', quote: '' };
          byId('seer-reveal-icon').textContent = info.icon;
          byId('seer-reveal-name').textContent = result.target_name;
          byId('seer-reveal-role').textContent = result.role_label;
          byId('seer-reveal-quote').textContent = info.quote;
          byId('seer-reveal-zone').hidden = false;
          byId('seer-targets').querySelectorAll('button').forEach(function (b) { b.disabled = true; });
          setTimeout(function () { byId('seer-reveal-card').classList.add('flipped'); }, 150);
        })
        .catch(function (error) { seerScrutinize.disabled = false; fail(error); });
    });
  }

  // Loup-Garou
  function renderWolf(data, newPhase) {
    var partner = (data.private.wolf_partners || [])[0];
    if (partner) {
      byId('wolf-ally-avatar').textContent = avatarOf(partner.id);
      byId('wolf-ally-name').textContent = partner.name + (partner.is_alive ? '' : ' (mort)');
    }
    var hunting = data.game.phase === 'NIGHT_WOLVES' && data.me.is_alive;
    var form = byId('wolf-form');
    if (form) {
      byId('wolf-input').disabled = !hunting;
      form.querySelector('button').disabled = !hunting;
    }
    var turn = myTurn(data, 'wolf');
    var status = byId('wolf-status');
    if (turn) setStatus(status, 'La meute attend votre choix : désignez la proie.');
    else if (data.game.phase === 'NIGHT_WOLVES') setStatus(status, 'Proie désignée : la meute passe à l\'action.', false);
    else setStatus(status, 'La chasse a lieu après la vision de la voyante.', false);

    if (newPhase) {
      var prey = others(data, function (p) { return p.role !== 'WEREWOLF'; });
      buildTargetGrid(byId('wolf-targets'), prey, null, function (p) {
        post(CFG.urls.night, { action: 'wolf', target_id: p.id })
          .then(function () { toast(p.name + ' est désigné comme proie.'); })
          .catch(fail);
      }, !turn);
    }
  }

  var wolfForm = byId('wolf-form');
  if (wolfForm) {
    wolfForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var input = byId('wolf-input');
      var text = input.value.trim();
      if (!text) return;
      post(CFG.urls.message, { text: text, channel: 'WOLVES' })
        .then(function () { input.value = ''; })
        .catch(fail);
    });
  }

  // Sorcière
  function renderPotions(potions) {
    [['fiole-life', potions.life], ['fiole-death', potions.death]].forEach(function (pair) {
      var row = byId(pair[0]);
      if (!row) return;
      row.querySelector('span:last-child').textContent = pair[1] ? '1 fiole' : 'Fiole vide';
      row.style.opacity = pair[1] ? '1' : '0.5';
    });
  }

  function renderWitch(data, newPhase) {
    var potions = data.private.potions || { life: false, death: false };
    var victim = data.private.wolf_victim;
    var turn = myTurn(data, 'witch');
    renderPotions(potions);

    var note = byId('witch-notification-text');
    if (note) {
      note.textContent = data.game.phase !== 'NIGHT_WITCH'
        ? 'Les loups n\'ont pas encore choisi leur victime.'
        : victim ? victim.name + ' a été désigné par les loups cette nuit.' : 'Les loups n\'ont tué personne cette nuit.';
    }
    var lifeBtn = byId('witch-life-btn');
    var deathBtn = byId('witch-death-btn');
    var doneBtn = byId('witch-done-btn');
    if (lifeBtn) lifeBtn.disabled = !turn || !potions.life || !victim || witchDraft.heal;
    if (deathBtn) deathBtn.disabled = !turn || !potions.death || Boolean(witchDraft.killId);
    if (doneBtn) {
      doneBtn.disabled = !turn;
      doneBtn.textContent = witchDraft.heal || witchDraft.killId
        ? 'Valider ma décision'
        : 'Se rendormir sans rien faire';
    }

    var parts = [];
    if (witchDraft.heal && victim) parts.push('sauver ' + victim.name);
    if (witchDraft.killId) parts.push('empoisonner ' + witchDraft.killName);
    var status = byId('witch-status');
    if (turn) setStatus(status, parts.length ? 'Vous allez ' + parts.join(' et ') + '.' : 'Votre tour : utilisez vos fioles, ou rendormez-vous.');
    else setStatus(status, data.turn.done ? 'Votre décision est prise pour cette nuit.' : 'Patientez jusqu\'à votre tour.', false);

    if (newPhase && turn && victim) {
      byId('witch-life-target-avatar').textContent = avatarOf(victim.id);
      byId('witch-life-target-text').textContent = victim.name + ' a été désigné par les loups.';
    }
    if (newPhase && turn) {
      var confirmDeath = byId('witch-death-confirm-btn');
      if (confirmDeath) confirmDeath.disabled = true;
      buildTargetGrid(byId('witch-death-targets'), others(data), null, function (p) {
        witchKillCandidate = p;
        if (confirmDeath) confirmDeath.disabled = false;
      });
    }
  }

  function bindClick(id, handler) { var el = byId(id); if (el) el.addEventListener('click', handler); }

  bindClick('witch-life-btn', function () { openModal('witch-life-modal'); });
  bindClick('witch-life-close-btn', function () { closeModal('witch-life-modal'); });
  bindClick('witch-life-confirm-btn', function () {
    var victim = state && state.private.wolf_victim;
    if (victim && witchDraft.killId === victim.id) {
      toast('Impossible de soigner et d\'empoisonner la même personne.', 'error');
      return;
    }
    witchDraft.heal = true;
    closeModal('witch-life-modal');
    render(state);
  });
  bindClick('witch-death-btn', function () { openModal('witch-death-modal'); });
  bindClick('witch-death-close-btn', function () { closeModal('witch-death-modal'); });
  bindClick('witch-death-confirm-btn', function () {
    var target = witchKillCandidate;
    var victim = state && state.private.wolf_victim;
    if (!target) return;
    if (witchDraft.heal && victim && target.id === victim.id) {
      toast('Impossible de soigner et d\'empoisonner la même personne.', 'error');
      return;
    }
    witchDraft.killId = target.id;
    witchDraft.killName = target.name;
    closeModal('witch-death-modal');
    render(state);
  });
  bindClick('witch-done-btn', function () {
    var btn = byId('witch-done-btn');
    btn.disabled = true;
    post(CFG.urls.night, { action: 'witch', heal: witchDraft.heal, kill_target_id: witchDraft.killId })
      .then(function () { toast('La sorcière a pris sa décision.'); })
      .catch(function (error) { btn.disabled = false; fail(error); });
  });

  // Villageois : murmures pendant l'attente
  var whisperIndex = 0;
  setInterval(function () {
    var el = byId('night-whisper');
    if (!el || !document.body.classList.contains('night-phase')) return;
    whisperIndex = (whisperIndex + 1) % WHISPERS.length;
    el.textContent = WHISPERS[whisperIndex];
  }, 5000);
  if (byId('night-whisper')) byId('night-whisper').textContent = WHISPERS[0];

  // ----- Fin de partie ----------------------------------------------- //

  function renderGameOver(data) {
    if (data.game.status !== 'FINISHED' || gameOverShown) return;
    gameOverShown = true;
    var won = (data.game.winner === 'WOLVES') === (data.me.role === 'WEREWOLF');
    byId('game-over-text').textContent = data.display.label + (won ? ' — vous avez gagné !' : ' — vous avez perdu.');
    var list = byId('game-over-roles');
    list.textContent = '';
    data.players.forEach(function (p) {
      var li = document.createElement('li');
      li.textContent = (ROLE_INFO[p.role] ? ROLE_INFO[p.role].icon + ' ' : '') + p.name + ' — ' +
        (p.role_label || '?') + (p.is_alive ? '' : ' (mort)') + (p.is_me ? ' · vous' : '');
      list.appendChild(li);
    });
    openModal('game-over-modal');
  }
  bindClick('game-over-close-btn', function () { closeModal('game-over-modal'); });

  // ----- Nouvelle partie --------------------------------------------- //
  // Partie terminée : on repart directement. Partie en cours (ou état pas
  // encore reçu) : avertissement avant d'abandonner.
  var newGameForm = byId('new-game-form');
  if (newGameForm) {
    newGameForm.addEventListener('submit', function (event) {
      if (state && state.game.status === 'FINISHED') return;
      event.preventDefault();
      if (state) {
        byId('new-game-text').textContent =
          'La partie est en cours (' + state.display.label + '). Si vous en commencez une ' +
          'nouvelle, celle-ci sera abandonnée et ne pourra pas être reprise.';
      }
      openModal('new-game-modal');
    });
  }
  bindClick('new-game-cancel-btn', function () { closeModal('new-game-modal'); });
  bindClick('new-game-confirm-btn', function () {
    byId('new-game-confirm-btn').disabled = true;
    newGameForm.submit(); // submit() natif : ne redéclenche pas l'avertissement
  });

  // ------------------------------------------------------------------ //
  //  Minuteurs (calculés depuis l'échéance serveur)                    //
  // ------------------------------------------------------------------ //

  function secondsLeft() {
    if (!state || !state.game.phase_deadline) return null;
    var ms = Date.parse(state.game.phase_deadline) - (Date.now() + clockSkew);
    return Math.max(0, Math.ceil(ms / 1000));
  }

  var PHASE_SHORT = {
    NIGHT_SEER: 'Voyante',
    NIGHT_WOLVES: 'Loups',
    NIGHT_WITCH: 'Sorcière',
    DAWN: 'Aube',
    DAY_DEBATE: 'Débat',
    DAY_VOTE: 'Vote',
    VOTE_RESULT: 'Verdict',
    GAME_OVER: 'Partie terminée',
  };

  function renderCountdown(phase, left, urgent) {
    var box = byId('board-countdown');
    if (!box) return;
    var finished = phase === 'GAME_OVER' || left === null;
    byId('board-countdown-value').textContent = finished ? '🏁' : String(left);
    byId('board-countdown-label').textContent = finished ? PHASE_SHORT.GAME_OVER : PHASE_SHORT[phase];
    box.classList.toggle('is-urgent', !finished && urgent);
    box.classList.toggle('is-night', has(NIGHT_PHASES, phase));
  }

  function tickTimers() {
    if (!state) return;
    var left = secondsLeft();
    var shown = left === null ? '—' : String(left);
    var urgent = left !== null && left <= 10;
    var phase = state.game.phase;
    renderCountdown(phase, left, urgent);

    if (phase === 'DAY_VOTE') {
      var started = Date.parse(state.game.phase_started_at);
      var total = (Date.parse(state.game.phase_deadline) - started) / 1000 || 45;
      ['vote-timer-value', 'vote-count-value', 'vote-timer-remaining'].forEach(function (id) {
        if (byId(id)) byId(id).textContent = shown;
      });
      if (byId('vote-bar-fill')) byId('vote-bar-fill').style.width = (left === null ? 0 : (left / total) * 100) + '%';
      if (byId('vote-timer')) byId('vote-timer').classList.toggle('vote-timer-urgent', urgent);
      if (byId('vote-count')) byId('vote-count').classList.toggle('vote-count-urgent', urgent);
      if (byId('vote-panel')) byId('vote-panel').classList.toggle('vote-panel-urgent', urgent);
    }
    if (has(NIGHT_PHASES, phase)) {
      if (byId('night-timer-value')) byId('night-timer-value').textContent = shown;
      if (byId('night-timer')) byId('night-timer').classList.toggle('night-timer-urgent', urgent);
      if (byId('night-wait-count')) byId('night-wait-count').textContent = 'La nuit dure encore · ' + shown + ' s';
    }
  }

  setInterval(tickTimers, 250);
  setInterval(poll, CFG.poll_ms || 1500);
  poll();
})();
