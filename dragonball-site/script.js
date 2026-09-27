(function () {
  'use strict';

  /* ============================== Helpers ============================== */
  const $ = function (sel, root) { return (root || document).querySelector(sel); };
  const $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  const clamp = function (v, a, b) { return Math.min(b, Math.max(a, v)); };
  const fmt = function (n) { return Math.round(n).toLocaleString('en-US'); };
  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const KI_TARGET = 10000;

  const store = {
    get: function (key, fallback) {
      try {
        const raw = localStorage.getItem('db.' + key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) { return fallback; }
    },
    set: function (key, value) {
      try { localStorage.setItem('db.' + key, JSON.stringify(value)); } catch (e) { /* ignore */ }
    }
  };

  /* ============================== Dragon Ball state ============================== */
  let collection = store.get('balls', [false, false, false, false, false, false, false]);
  if (!Array.isArray(collection) || collection.length !== 7) {
    collection = [false, false, false, false, false, false, false];
  }

  /* ============================== Toasts ============================== */
  const toastWrap = $('#toasts');
  function toast(message, kind) {
    if (!toastWrap) return;
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = message;
    toastWrap.appendChild(el);
    window.setTimeout(function () {
      el.classList.add('out');
      window.setTimeout(function () { el.remove(); }, 400);
    }, 2600);
  }

  /* ============================== Sound ============================== */
  const Sound = {
    enabled: store.get('sound', true),
    ctx: null,
    init: function () {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      if (!this.ctx) this.ctx = new AC();
      if (this.ctx.state === 'suspended') this.ctx.resume();
    },
    beep: function (freq, dur, type, gain) {
      if (!this.enabled) return;
      this.init();
      if (!this.ctx) return;
      const d = dur || 0.12;
      const osc = this.ctx.createOscillator();
      const g = this.ctx.createGain();
      osc.type = type || 'sine';
      osc.frequency.setValueAtTime(freq || 440, this.ctx.currentTime);
      g.gain.setValueAtTime(gain || 0.05, this.ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, this.ctx.currentTime + d);
      osc.connect(g);
      g.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + d);
    },
    sweep: function (from, to, dur) {
      if (!this.enabled) return;
      this.init();
      if (!this.ctx) return;
      const d = dur || 0.4;
      const osc = this.ctx.createOscillator();
      const g = this.ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(from, this.ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(to, this.ctx.currentTime + d);
      g.gain.setValueAtTime(0.045, this.ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, this.ctx.currentTime + d);
      osc.connect(g);
      g.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + d);
    }
  };

  const soundToggle = $('#soundToggle');
  function paintSound() {
    if (!soundToggle) return;
    soundToggle.textContent = Sound.enabled ? '\uD83D\uDD0A' : '\uD83D\uDD07';
    soundToggle.setAttribute('aria-pressed', String(Sound.enabled));
  }
  if (soundToggle) {
    paintSound();
    soundToggle.addEventListener('click', function () {
      Sound.enabled = !Sound.enabled;
      store.set('sound', Sound.enabled);
      paintSound();
      if (Sound.enabled) Sound.beep(660, 0.1, 'triangle', 0.05);
    });
  }

  /* ============================== Theme ============================== */
  const themeSelect = $('#themeSelect');
  const savedTheme = store.get('theme', 'ki');
  document.documentElement.dataset.theme = savedTheme;
  if (themeSelect) {
    themeSelect.value = savedTheme;
    themeSelect.addEventListener('change', function () {
      document.documentElement.dataset.theme = themeSelect.value;
      store.set('theme', themeSelect.value);
      drawChart();
      paintRadar();
    });
  }

  /* ============================== Navigation ============================== */
  const navToggle = $('#navToggle');
  const navLinks = $('#navLinks');
  if (navToggle && navLinks) {
    navToggle.addEventListener('click', function () {
      const open = navLinks.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(open));
    });
    navLinks.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') {
        navLinks.classList.remove('open');
        navToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  const sections = $$('main section[id]');
  const navAnchors = $$('.nav-links a');
  function syncNav() {
    const y = window.scrollY + 140;
    let current = sections[0] ? sections[0].id : '';
    sections.forEach(function (s) { if (s.offsetTop <= y) current = s.id; });
    navAnchors.forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('href') === '#' + current);
    });
  }

  /* ============================== Scroll reveal ============================== */
  (function () {
    const revealables = $$('.reveal, .card');
    if ('IntersectionObserver' in window && !REDUCED) {
      const io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('visible');
          const fill = entry.target.querySelector('.bar-fill[data-width]');
          if (fill) fill.style.width = fill.dataset.width;
          io.unobserve(entry.target);
        });
      }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
      revealables.forEach(function (el) { io.observe(el); });
    } else {
      revealables.forEach(function (el) { el.classList.add('visible'); });
    }
  })();

  /* ============================== Preloader ============================== */
  const preloader = $('#preloader');
  function hidePreloader() {
    if (preloader) preloader.classList.add('hidden');
  }
  window.addEventListener('load', function () { window.setTimeout(hidePreloader, 350); });
  window.setTimeout(hidePreloader, 2500);

  /* ============================== FX canvas ============================== */
  const fx = $('#fx');
  const fxState = { stars: [], particles: [], raf: 0, w: 0, h: 0 };

  function fxResize() {
    if (!fx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    fxState.w = window.innerWidth;
    fxState.h = window.innerHeight;
    fx.width = Math.floor(fxState.w * dpr);
    fx.height = Math.floor(fxState.h * dpr);
    fx.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.round((fxState.w * fxState.h) / 16000);
    fxState.stars = [];
    for (let i = 0; i < count; i++) {
      fxState.stars.push({
        x: Math.random() * fxState.w,
        y: Math.random() * fxState.h,
        r: Math.random() * 1.5 + 0.35,
        a: Math.random() * 0.55 + 0.2,
        s: Math.random() * 0.16 + 0.03
      });
    }
  }

  function fxLoop() {
    if (!fx) return;
    const ctx = fx.getContext('2d');
    ctx.clearRect(0, 0, fxState.w, fxState.h);
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#ff7a18';
    fxState.stars.forEach(function (s) {
      s.y += s.s;
      if (s.y > fxState.h) { s.y = -2; s.x = Math.random() * fxState.w; }
      ctx.globalAlpha = s.a;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
    if (!REDUCED && Math.random() < 0.28) {
      fxState.particles.push({
        x: Math.random() * fxState.w,
        y: fxState.h + 12,
        r: Math.random() * 2.2 + 0.8,
        v: Math.random() * 1.1 + 0.5,
        a: 0.65
      });
    }
    fxState.particles = fxState.particles.filter(function (p) { return p.y > -20 && p.a > 0.02; });
    fxState.particles.forEach(function (p) {
      p.y -= p.v;
      p.a -= 0.004;
      ctx.globalAlpha = Math.max(p.a, 0);
      ctx.fillStyle = accent;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
    fxState.raf = window.requestAnimationFrame(fxLoop);
  }

  if (fx) {
    fxResize();
    fxLoop();
    window.addEventListener('resize', fxResize);
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        window.cancelAnimationFrame(fxState.raf);
      } else {
        fxState.raf = window.requestAnimationFrame(fxLoop);
      }
    });
  }

  /* ============================== Fighter data ============================== */
  const FIGHTERS = [
    { id: 'goku', name: 'Goku', race: 'Saiyan', base: 9000, color: '#ff7a18', forms: [['Base', 1], ['Super Saiyan', 1.6], ['Super Saiyan Blue', 3.1], ['Ultra Instinct', 5]] },
    { id: 'vegeta', name: 'Vegeta', race: 'Saiyan', base: 8500, color: '#4f8cff', forms: [['Base', 1], ['Super Saiyan', 1.6], ['Super Saiyan Blue', 3.1], ['Ultra Ego', 4.8]] },
    { id: 'gohan', name: 'Gohan', race: 'Half-Saiyan', base: 7200, color: '#b06bff', forms: [['Base', 1], ['Super Saiyan 2', 1.8], ['Ultimate', 2.6], ['Beast', 4.2]] },
    { id: 'piccolo', name: 'Piccolo', race: 'Namekian', base: 5000, color: '#2ee66b', forms: [['Base', 1], ['Fused', 1.6], ['Orange Piccolo', 2.9]] },
    { id: 'frieza', name: 'Frieza', race: 'Frieza Race', base: 7800, color: '#ff5bd0', forms: [['Final Form', 1], ['Golden', 2.4], ['Black Frieza', 4.5]] },
    { id: 'trunks', name: 'Trunks', race: 'Half-Saiyan', base: 4600, color: '#00d6c8', forms: [['Base', 1], ['Super Saiyan', 1.5], ['Super Saiyan Rage', 2.6]] },
    { id: 'broly', name: 'Broly', race: 'Saiyan', base: 9600, color: '#9dff3a', forms: [['Base', 1], ['Wrathful', 1.9], ['Legendary Super Saiyan', 4.4]] },
    { id: 'beerus', name: 'Beerus', race: 'God of Destruction', base: 12000, color: '#c084fc', forms: [['Base', 1], ['Hakai', 1.4]] },
    { id: 'jiren', name: 'Jiren', race: 'Alien', base: 11000, color: '#ff4d4d', forms: [['Base', 1], ['Full Power', 1.7]] },
    { id: 'android17', name: 'Android 17', race: 'Android', base: 6400, color: '#ffc857', forms: [['Base', 1], ['Super 17', 1.8]] }
  ];

  const formIndex = {};
  FIGHTERS.forEach(function (f) { formIndex[f.id] = 0; });

  function fighterById(id) {
    return FIGHTERS.filter(function (f) { return f.id === id; })[0] || FIGHTERS[0];
  }
  function formOf(f) { return f.forms[formIndex[f.id]]; }
  function powerOf(f) { return f.base * formOf(f)[1]; }
  function initials(name) {
    return name.split(' ').map(function (p) { return p.charAt(0); }).join('').slice(0, 2).toUpperCase();
  }
  function maxPowerOf(f) { return f.base * f.forms[f.forms.length - 1][1]; }

  /* ============================== Roster ============================== */
  const grid = document.getElementById('fighterGrid');
  const searchInput = document.getElementById('fighter');
  const raceFilter = $('#raceFilter');
  const sortSelect = $('#sortSelect');
  const maxFormBtn = $('#maxFormBtn');
  const rosterMeta = $('#rosterMeta');

  if (raceFilter) {
    const races = FIGHTERS.map(function (f) { return f.race; })
      .filter(function (r, i, arr) { return arr.indexOf(r) === i; })
      .sort();
    races.forEach(function (r) {
      const opt = document.createElement('option');
      opt.value = r;
      opt.textContent = r;
      raceFilter.appendChild(opt);
    });
  }

  function tiltBind(card) {
    if (REDUCED || window.matchMedia('(hover: none)').matches) return;
    card.addEventListener('mousemove', function (e) {
      const r = card.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      card.style.transform = 'perspective(900px) rotateY(' + (px * 8).toFixed(2) + 'deg) rotateX(' + (-py * 8).toFixed(2) + 'deg) translateY(-4px)';
    });
    card.addEventListener('mouseleave', function () { card.style.transform = ''; });
  }

  function visibleFighters() {
    const q = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const race = raceFilter ? raceFilter.value : 'all';
    const sort = sortSelect ? sortSelect.value : 'power-desc';
    const list = FIGHTERS.filter(function (f) {
      if (race !== 'all' && f.race !== race) return false;
      if (!q) return true;
      const hay = (f.name + ' ' + f.race + ' ' + f.forms.map(function (x) { return x[0]; }).join(' ')).toLowerCase();
      return hay.indexOf(q) !== -1;
    });
    list.sort(function (a, b) {
      if (sort === 'power-asc') return powerOf(a) - powerOf(b);
      if (sort === 'name-asc') return a.name.localeCompare(b.name);
      return powerOf(b) - powerOf(a);
    });
    return list;
  }

  function renderRoster() {
    if (!grid) return;
    const list = visibleFighters();
    const max = list.reduce(function (m, f) { return Math.max(m, powerOf(f)); }, 1);
    grid.innerHTML = '';

    list.forEach(function (f, i) {
      const form = formOf(f);
      const power = powerOf(f);
      const card = document.createElement('article');
      card.className = 'card visible';
      card.style.transitionDelay = (i * 40) + 'ms';

      const top = document.createElement('div');
      top.className = 'card-top';

      const h3 = document.createElement('h3');
      h3.textContent = f.name;

      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.style.background = f.color;
      avatar.style.color = f.color;
      avatar.textContent = initials(f.name);

      top.appendChild(h3);
      top.appendChild(avatar);

      const race = document.createElement('p');
      race.className = 'race';
      race.textContent = f.race;

      const tag = document.createElement('span');
      tag.className = 'form-tag';
      tag.textContent = form[0];

      const powerEl = document.createElement('p');
      powerEl.className = 'power';
      powerEl.textContent = 'Power level: ' + fmt(power);

      const bar = document.createElement('div');
      bar.className = 'bar';
      const fill = document.createElement('div');
      fill.className = 'bar-fill';
      const pct = Math.round((power / max) * 100) + '%';
      fill.dataset.width = pct;
      fill.style.width = pct;
      bar.appendChild(fill);

      const actions = document.createElement('div');
      actions.className = 'card-actions';

      const transformBtn = document.createElement('button');
      transformBtn.type = 'button';
      transformBtn.className = 'btn ghost';
      transformBtn.textContent = 'Transform';
      transformBtn.addEventListener('click', function () {
        formIndex[f.id] = (formIndex[f.id] + 1) % f.forms.length;
        Sound.beep(520 + formIndex[f.id] * 120, 0.14, 'square', 0.05);
        renderRoster();
        renderBattleCards();
        drawChart();
      });

      const pickBtn = document.createElement('button');
      pickBtn.type = 'button';
      pickBtn.className = 'btn btn-primary';
      pickBtn.textContent = 'Pick';
      pickBtn.title = 'Send to battle simulator';
      pickBtn.addEventListener('click', function () { assignToBattle(f.id); });

      actions.appendChild(transformBtn);
      actions.appendChild(pickBtn);

      card.appendChild(top);
      card.appendChild(race);
      card.appendChild(tag);
      card.appendChild(powerEl);
      card.appendChild(bar);
      card.appendChild(actions);
      tiltBind(card);
      grid.appendChild(card);
    });

    if (rosterMeta) {
      rosterMeta.textContent = list.length + ' of ' + FIGHTERS.length + ' fighters shown \u00b7 peak ' + fmt(max);
    }
    if (!list.length) {
      const empty = document.createElement('p');
      empty.className = 'meta';
      empty.textContent = 'No fighters match your search.';
      grid.appendChild(empty);
    }
  }

  [Input, raceFilter, sortSelect].forEach(function (el) {
    if (!el) return;
    el.addEventListener('input', renderRoster);
    el.addEventListener('change', renderRoster);
  });

  if (maxFormBtn) {
    maxFormBtn.addEventListener('click', function () {
      FIGHTERS.forEach(function (f) { formIndex[f.id] = f.forms.length - 1; });
      Sound.sweep(320, 1100, 0.5);
      toast('All fighters transformed to max power', 'good');
      renderRoster();
      renderBattleCards();
      drawChart();
    });
  }

  /* ============================== Battle simulator ============================== */
  const p1Select = $('#p1Select');
  const p2Select = $('#p2Select');
  const p1Card = $('#p1Card');
  const p2Card = $('#p2Card');
  const fightBtn = $('#fightBtn');
  const bestOfBtn = $('#bestOfBtn');
  const clashFill = $('#clashFill');
  const battleResult = $('#battleResult');
  const battleLog = $('#battleLog');

  function fillFighterSelect(select, defaultId) {
    if (!select) return;
    FIGHTERS.forEach(function (f) {
      const opt = document.createElement('option');
      opt.value = f.id;
      opt.textContent = f.name;
      select.appendChild(opt);
    });
    select.value = defaultId;
  }
  fillFighterSelect(p1Select, 'goku');
  fillFighterSelect(p2Select, 'vegeta');

  function miniCard(el, f) {
    if (!el || !f) return;
    const form = formOf(f);
    el.innerHTML = '';

    const h4 = document.createElement('h4');
    h4.textContent = f.name;

    const race = document.createElement('p');
    race.className = 'race';
    race.textContent = f.race + ' \u00b7 ' + form[0];

    const power = document.createElement('p');
    power.className = 'power';
    power.textContent = 'Power level: ' + fmt(powerOf(f));

    const bar = document.createElement('div');
    bar.className = 'bar';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    const pct = clamp(Math.round((powerOf(f) / 60000) * 100), 3, 100) + '%';
    fill.dataset.width = pct;
    fill.style.width = pct;
    bar.appendChild(fill);

    el.appendChild(h4);
    el.appendChild(race);
    el.appendChild(power);
    el.appendChild(bar);
  }

  function renderBattleCards() {
    if (!p1Select || !p2Select) return;
    miniCard(p1Card, fighterById(p1Select.value));
    miniCard(p2Card, fighterById(p2Select.value));
  }
  if (p1Select) p1Select.addEventListener('change', renderBattleCards);
  if (p2Select) p2Select.addEventListener('change', renderBattleCards);

  function assignToBattle(id) {
    if (!p1Select || !p2Select) return;
    if (p2Select.value === id) {
      p1Select.value = id;
    } else {
      p2Select.value = id;
    }
    if (p1Select.value === p2Select.value) {
      p2Select.value = id === 'goku' ? 'vegeta' : 'goku';
    }
    renderBattleCards();
    Sound.beep(700, 0.1, 'triangle', 0.05);
    toast(fighterById(id).name + ' placed in the arena', 'good');
    const battleSection = document.getElementById('battle');
    if (battleSection) battleSection.scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'start' });
  }

  function logLine(text, win) {
    if (!battleLog) return;
    const li = document.createElement('li');
    if (win) li.className = 'win';
    li.textContent = text;
    battleLog.insertBefore(li, battleLog.firstChild);
    while (battleLog.children.length > 24) battleLog.removeChild(battleLog.lastChild);
  }

  function simulate(a, b) {
    const pa = powerOf(a);
    const pb = powerOf(b);
    let hpA = 100;
    let hpB = 100;
    let round = 0;
    const rounds = [];
    while (hpA > 0 && hpB > 0 && round < 20) {
      round++;
      const rollA = pa * (0.85 + Math.random() * 0.3);
      const rollB = pb * (0.85 + Math.random() * 0.3);
      const share = rollA / (rollA + rollB);
      const dmgToB = 46 * share;
      const dmgToA = 46 * (1 - share);
      hpB = Math.max(0, hpB - dmgToB);
      hpA = Math.max(0, hpA - dmgToA);
      rounds.push('Round ' + round + ': ' + a.name + ' hits for ' + Math.round(dmgToB) +
        ' \u00b7 ' + b.name + ' hits for ' + Math.round(dmgToA) +
        ' (HP ' + Math.round(hpA) + ' / ' + Math.round(hpB) + ')');
    }
    const winner = (hpA <= 0 && hpB <= 0) ? null : (hpA > hpB ? a : b);
    return { winner: winner, rounds: rounds, share: pa / (pa + pb) };
  }

  function runFight(quiet) {
    if (!p1Select || !p2Select) return null;
    const a = fighterById(p1Select.value);
    const b = fighterById(p2Select.value);
    if (a.id === b.id) {
      toast('Pick two different fighters', 'warn');
      return null;
    }
    const result = simulate(a, b);
    if (clashFill) clashFill.style.width = clamp(Math.round(result.share * 100), 4, 96) + '%';
    if (!quiet) {
      if (battleLog) battleLog.innerHTML = '';
      result.rounds.slice().reverse().forEach(function (line) { logLine(line, false); });
      if (battleResult) {
        battleResult.textContent = result.winner
          ? result.winner.name + ' wins! (' + fmt(powerOf(result.winner)) + ' power)'
          : 'Double knockout \u2014 no winner.';
      }
      logLine(result.winner ? result.winner.name + ' stands victorious!' : 'Both fighters fall.', true);
      Sound.sweep(180, 900, 0.45);
    }
    return result;
  }

  if (fightBtn) fightBtn.addEventListener('click', function () { runFight(false); });

  if (bestOfBtn) {
    bestOfBtn.addEventListener('click', function () {
      if (!p1Select || !p2Select) return;
      const a = fighterById(p1Select.value);
      const b = fighterById(p2Select.value);
      if (a.id === b.id) { toast('Pick two different fighters', 'warn'); return; }

      let winsA = 0;
      let winsB = 0;
      if (battleLog) battleLog.innerHTML = '';

      for (let i = 1; i <= 5; i++) {
        const r = simulate(a, b);
        if (r.winner && r.winner.id === a.id) winsA++;
        else if (r.winner && r.winner.id === b.id) winsB++;
        logLine('Bout ' + i + ': ' + (r.winner ? r.winner.name + ' wins' : 'draw'), false);
      }

      const champ = winsA === winsB ? null : (winsA > winsB ? a : b);
      if (battleResult) {
        battleResult.textContent = champ
          ? 'Best of 5: ' + champ.name + ' takes it ' + Math.max(winsA, winsB) + '\u2013' + Math.min(winsA, winsB)
          : 'Best of 5: series drawn ' + winsA + '\u2013' + winsB;
      }
      logLine(champ ? champ.name + ' wins the series!' : 'Series drawn.', true);
      Sound.sweep(200, 1000, 0.6);
    });
  }

  /* ============================== Dragon radar ============================== */
  const radarCanvas = $('#radarCanvas');
  const scanBtn = $('#scanBtn');
  const autoScanBtn = $('#autoScanBtn');
  const radarStatus = $('#radarStatus');
  const radarList = $('#radarList');
  const rctx = radarCanvas ? radarCanvas.getContext('2d') : null;
  const RADAR_SIZE = 420;
  const radar = { targets: [], angle: 0, scanning: false, raf: 0, revealed: 0 };

  function newTargets() {
    radar.targets = [];
    radar.revealed = 0;
    const pool = [];
    for (let i = 0; i < 7; i++) if (!collection[i]) pool.push(i);
    pool.forEach(function (idx) {
      radar.targets.push({
        ball: idx,
        angle: Math.random() * Math.PI * 2,
        dist: 40 + Math.random() * 150,
        found: false
      });
    });
  }

  function paintRadar() {
    if (!rctx) return;
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue('--accent').trim() || '#ff7a18';
    const accent3 = styles.getPropertyValue('--accent-3').trim() || '#2b7fff';
    const cx = RADAR_SIZE / 2;
    const cy = RADAR_SIZE / 2;
    const maxR = RADAR_SIZE / 2 - 12;

    rctx.clearRect(0, 0, RADAR_SIZE, RADAR_SIZE);
    rctx.strokeStyle = 'rgba(255,255,255,0.14)';
    rctx.lineWidth = 1;

    [0.33, 0.66, 1].forEach(function (k) {
      rctx.beginPath();
      rctx.arc(cx, cy, maxR * k, 0, Math.PI * 2);
      rctx.stroke();
    });

    rctx.beginPath();
    rctx.moveTo(cx, cy - maxR);
    rctx.lineTo(cx, cy + maxR);
    rctx.moveTo(cx - maxR, cy);
    rctx.lineTo(cx + maxR, cy);
    rctx.stroke();

    if (radar.scanning) {
      rctx.save();
      rctx.translate(cx, cy);
      rctx.rotate(radar.angle);
      const sweep = rctx.createLinearGradient(0, 0, maxR, 0);
      sweep.addColorStop(0, accent3);
      sweep.addColorStop(1, 'rgba(0,0,0,0)');
      rctx.strokeStyle = sweep;
      rctx.lineWidth = 3;
      rctx.beginPath();
      rctx.moveTo(0, 0);
      rctx.lineTo(maxR, 0);
      rctx.stroke();
      rctx.restore();
    }

    radar.targets.forEach(function (t) {
      if (!t.found) return;
      const x = cx + Math.cos(t.angle) * t.dist;
      const y = cy + Math.sin(t.angle) * t.dist;
      const taken = !!collection[t.ball];
      rctx.beginPath();
      rctx.arc(x, y, 8, 0, Math.PI * 2);
      rctx.fillStyle = taken ? 'rgba(120,130,150,0.45)' : accent;
      rctx.fill();
      rctx.beginPath();
      rctx.arc(x, y, 14, 0, Math.PI * 2);
      rctx.strokeStyle = taken ? 'rgba(120,130,150,0.35)' : accent;
      rctx.lineWidth = 1.5;
      rctx.stroke();
    });

    rctx.beginPath();
    rctx.arc(cx, cy, 6, 0, Math.PI * 2);
    rctx.fillStyle = accent;
    rctx.fill();
  }

  function radarLoop() {
    radar.angle += 0.045;
    if (radar.angle > Math.PI * 2) radar.angle -= Math.PI * 2;

    radar.targets.forEach(function (t) {
      if (t.found) return;
      let delta = t.angle - radar.angle;
      while (delta < -Math.PI) delta += Math.PI * 2;
      while (delta > Math.PI) delta -= Math.PI * 2;
      if (Math.abs(delta) < 0.06) {
        t.found = true;
        radar.revealed++;
        Sound.beep(900, 0.08, 'square', 0.04);
        if (radarList) {
          const li = document.createElement('li');
          li.textContent = 'Signal ' + radar.revealed + ': Dragon Ball with ' + (t.ball + 1) +
            ' star(s) \u2014 click the blip to collect.';
          radarList.insertBefore(li, radarList.firstChild);
        }
        if (radarStatus) radarStatus.textContent = 'Scanning\u2026 ' + radar.revealed + ' signal(s) detected.';
      }
    });

    paintRadar();

    if (radar.revealed >= radar.targets.length) {
      radar.scanning = false;
      if (radarStatus) radarStatus.textContent = 'Scan complete \u2014 ' + radar.revealed + ' signal(s) detected.';
      return;
    }
    radar.raf = window.requestAnimationFrame(radarLoop);
  }

  function startScan() {
    if (!rctx || radar.scanning) return;
    newTargets();
    if (radarList) radarList.innerHTML = '';
    if (!radar.targets.length) {
      if (radarStatus) radarStatus.textContent = 'No signals left \u2014 every Dragon Ball is already collected.';
      paintRadar();
      return;
    }
    radar.angle = 0;
    radar.scanning = true;
    if (radarStatus) radarStatus.textContent = 'Scanning\u2026';
    Sound.sweep(300, 800, 0.35);
    window.cancelAnimationFrame(radar.raf);
    radar.raf = window.requestAnimationFrame(radarLoop);
  }

  if (scanBtn) scanBtn.addEventListener('click', startScan);

  if (autoScanBtn) {
    autoScanBtn.addEventListener('click', function () {
      const pending = [];
      for (let i = 0; i < 7; i++) if (!collection[i]) pending.push(i);
      if (!pending.length) { toast('Every Dragon Ball is already collected', 'warn'); return; }
      pending.forEach(function (idx, n) {
        window.setTimeout(function () { collectBall(idx, true); }, 260 * n + 200);
      });
      toast('Auto scan recovering ' + pending.length + ' ball(s)\u2026');
    });
  }

  if (radarCanvas) {
    radarCanvas.addEventListener('click', function (e) {
      const rect = radarCanvas.getBoundingClientRect();
      const scale = RADAR_SIZE / rect.width;
      const x = (e.clientX - rect.left) * scale;
      const y = (e.clientY - rect.top) * scale;
      const cx = RADAR_SIZE / 2;
      const cy = RADAR_SIZE / 2;
      let hit = null;
      radar.targets.forEach(function (t) {
        if (!t.found || collection[t.ball]) return;
        const tx = cx + Math.cos(t.angle) * t.dist;
        const ty = cy + Math.sin(t.angle) * t.dist;
        if (Math.hypot(tx - x, ty - y) < 20) hit = t.ball;
      });
      if (hit === null) return;
      collectBall(hit, true);
      paintRadar();
    });
  }

  /* ============================== Dragon balls ============================== */
  const ballRow = $('#ballRow');
  const ballCountEl = $('#ballCount');
  const summonBtn = $('#summonBtn');
  const resetBallsBtn = $('#resetBallsBtn');
  const wishLogEl = $('#wishLog');
  const wishModal = $('#wishModal');
  const wishResult = $('#wishResult');
  const closeModalBtn = $('#closeModal');

  function renderBalls() {
    if (!ballRow) return;
    ballRow.innerHTML = '';
    let count = 0;

    for (let i = 0; i < 7; i++) {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'ball' + (collection[i] ? ' collected' : '');
      el.setAttribute('aria-pressed', String(!!collection[i]));
      el.setAttribute('aria-label', 'Dragon Ball with ' + (i + 1) + ' star(s), ' + (collection[i] ? 'collected' : 'not collected'));

      const stars = document.createElement('span');
      stars.className = 'stars';
      stars.textContent = new Array(i + 2).join('\u2605');
      el.appendChild(stars);

      (function (index) {
        el.addEventListener('click', function () { collectBall(index, !collection[index]); });
      })(i);

      ballRow.appendChild(el);
      if (collection[i]) count++;
    }

    if (ballCountEl) ballCountEl.textContent = String(count);
    if (summonBtn) {
      summonBtn.disabled = count < 7;
      summonBtn.textContent = count < 7 ? 'Summon Shenron (' + count + '/7)' : 'Summon Shenron!';
    }
    updateHeroCounters(count);
  }

  function collectBall(index, state) {
    collection[index] = !!state;
    store.set('balls', collection);
    renderBalls();
    paintRadar();
    if (state) {
      Sound.beep(880 + index * 40, 0.12, 'triangle', 0.05);
      const total = collection.filter(Boolean).length;
      toast('Dragon Ball ' + (index + 1) + ' collected (' + total + '/7)', 'good');
      if (total === 7) toast('All seven gathered \u2014 Shenron awaits!', 'good');
    }
  }

  if (resetBallsBtn) {
    resetBallsBtn.addEventListener('click', function () {
      collection = [false, false, false, false, false, false, false];
      store.set('balls', collection);
      renderBalls();
      paintRadar();
      toast('Collection reset');
    });
  }

  function openModal() {
    if (!wishModal) return;
    wishModal.classList.add('open');
    wishModal.setAttribute('aria-hidden', 'false');
    if (wishResult) wishResult.textContent = '';
    const first = wishModal.querySelector('.wish');
    if (first) first.focus();
    Sound.sweep(180, 700, 0.7);
  }

  function closeModal() {
    if (!wishModal) return;
    wishModal.classList.remove('open');
    wishModal.setAttribute('aria-hidden', 'true');
  }

  if (summonBtn) {
    summonBtn.addEventListener('click', function () {
      if (collection.filter(Boolean).length < 7) return;
      openModal();
    });
  }
  if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);

  if (wishModal) {
    wishModal.addEventListener('click', function (e) { if (e.target === wishModal) closeModal(); });
    $$('.wish', wishModal).forEach(function (btn) {
      btn.addEventListener('click', function () {
        const wish = btn.dataset.wish;
        if (wishResult) wishResult.textContent = 'Shenron grants your wish: ' + wish;
        const wishes = store.get('wishes', []);
        wishes.unshift({ wish: wish, at: new Date().toISOString() });
        store.set('wishes', wishes.slice(0, 12));
        renderWishLog();
        Sound.beep(1040, 0.25, 'sine', 0.06);
        toast('Wish granted: ' + wish, 'good');
        window.setTimeout(closeModal, 1400);
      });
    });
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && wishModal && wishModal.classList.contains('open')) closeModal();
  });

  function renderWishLog() {
    if (!wishLogEl) return;
    const wishes = store.get('wishes', []);
    wishLogEl.innerHTML = '';
    if (!wishes.length) {
      const li = document.createElement('li');
      li.textContent = 'No wishes made yet.';
      wishLogEl.appendChild(li);
      return;
    }
    wishes.forEach(function (w) {
      const li = document.createElement('li');
      const when = new Date(w.at);
      li.textContent = w.wish + ' \u2014 ' + when.toLocaleDateString() + ' ' + when.toLocaleTimeString();
      wishLogEl.appendChild(li);
    });
  }

  /* ============================== Ki arena ============================== */
  const kiArena = $('#kiArena');
  const startKiBtn = $('#startKiBtn');
  const resetKiBtn = $('#resetKiBtn');
  const kiTimerEl = $('#kiTimer');
  const kiScoreEl = $('#kiScore');
  const kiComboEl = $('#kiCombo');
  const kiBestEl = $('#kiBest');
  const kiBar = $('#kiBar');
  const kiHint = $('#kiHint');
  const ki = {
    running: false,
    score: 0,
    combo: 0,
    lastTap: 0,
    endAt: 0,
    raf: 0,
    best: store.get('kiBest', 0)
  };

  function kiPaint() {
    if (kiScoreEl) kiScoreEl.textContent = fmt(ki.score);
    if (kiComboEl) kiComboEl.textContent = 'x' + Math.max(ki.combo, 1);
    if (kiBestEl) kiBestEl.textContent = fmt(ki.best);
    if (kiBar) kiBar.style.width = clamp((ki.score / KI_TARGET) * 100, 0, 100) + '%';
  }

  function kiFinish() {
    ki.running = false;
    if (kiArena) kiArena.classList.remove('charging');
    if (ki.score > ki.best) {
      ki.best = ki.score;
      store.set('kiBest', ki.best);
      toast('New ki record: ' + fmt(ki.best), 'good');
    }
    if (kiHint) {
      kiHint.textContent = ki.score >= KI_TARGET
        ? 'Super Saiyan achieved \u2014 ' + fmt(ki.score) + ' ki!'
        : 'Final ki: ' + fmt(ki.score) + '. Tap to try again.';
    }
    Sound.sweep(900, 200, 0.5);
    kiPaint();
  }

  function kiLoop() {
    const left = ki.endAt - performance.now();
    if (left <= 0) {
      if (kiTimerEl) kiTimerEl.textContent = '0.0s';
      kiFinish();
      return;
    }
    if (kiTimerEl) kiTimerEl.textContent = (left / 1000).toFixed(1) + 's';
    if (performance.now() - ki.lastTap > 700) {
      ki.combo = 0;
      kiPaint();
    }
    ki.raf = window.requestAnimationFrame(kiLoop);
  }

  function kiStart() {
    if (ki.running) return;
    Sound.init();
    ki.running = true;
    ki.score = 0;
    ki.combo = 0;
    ki.lastTap = performance.now();
    ki.endAt = performance.now() + 10000;
    if (kiHint) kiHint.textContent = 'Tap as fast as you can!';
    if (kiArena) kiArena.classList.add('charging');
    kiPaint();
    window.cancelAnimationFrame(ki.raf);
    ki.raf = window.requestAnimationFrame(kiLoop);
  }

  function kiTap() {
    if (!ki.running) { kiStart(); return; }
    const now = performance.now();
    ki.combo = (now - ki.lastTap < 700) ? ki.combo + 1 : 1;
    ki.lastTap = now;
    ki.score += 110 * ki.combo;
    Sound.beep(clamp(420 + ki.combo * 45, 420, 1400), 0.05, 'square', 0.035);
    if (kiArena) {
      const core = kiArena.querySelector('.ki-core');
      if (core) {
        const s = clamp(1 + ki.combo * 0.045, 1, 2.1);
        core.style.transform = 'scale(' + s.toFixed(2) + ')';
      }
    }
    kiPaint();
  }

  if (kiArena) {
    kiArena.addEventListener('pointerdown', function (e) { e.preventDefault(); kiTap(); });
  }
  if (startKiBtn) startKiBtn.addEventListener('click', kiStart);

  if (resetKiBtn) {
    resetKiBtn.addEventListener('click', function () {
      ki.running = false;
      window.cancelAnimationFrame(ki.raf);
      ki.score = 0;
      ki.combo = 0;
      if (kiTimerEl) kiTimerEl.textContent = '10.0s';
      if (kiHint) kiHint.textContent = 'Press Start, then tap fast!';
      if (kiArena) {
        kiArena.classList.remove('charging');
        const core = kiArena.querySelector('.ki-core');
        if (core) core.style.transform = '';
      }
      kiPaint();
    });
  }

  /* ============================== Stats + chart ============================== */
  const statsCanvas = $('#statsCanvas');
  const sctx = statsCanvas ? statsCanvas.getContext('2d') : null;
  const statTotal = $('#statTotal');
  const statStrongest = $('#statStrongest');
  const statAverage = $('#statAverage');

  function drawChart() {
    if (!sctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const W = 900;
    const H = 440;
    statsCanvas.width = W * dpr;
    statsCanvas.height = H * dpr;
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue('--accent').trim() || '#ff7a18';
    const accent2 = styles.getPropertyValue('--accent-2').trim() || '#ffd700';
    const muted = styles.getPropertyValue('--muted').trim() || '#a9b7d6';

    const data = FIGHTERS.map(function (f) {
      return { name: f.name, power: powerOf(f) };
    }).sort(function (a, b) { return b.power - a.power; });

    const total = data.reduce(function (s, d) { return s + d.power; }, 0);
    const avg = data.length ? total / data.length : 0;
    if (statTotal) statTotal.textContent = fmt(total);
    if (statAverage) statAverage.textContent = fmt(avg);
    if (statStrongest && data.length) statStrongest.textContent = data[0].name + ' \u00b7 ' + fmt(data[0].power);

    sctx.clearRect(0, 0, W, H);

    const padL = 130;
    const padR = 80;
    const padT = 26;
    const padB = 26;
    const max = data.reduce(function (m, d) { return Math.max(m, d.power); }, 1);
    const rowH = (H - padT - padB) / data.length;
    const barH = Math.min(rowH * 0.6, 24);

    data.forEach(function (d, i) {
      const y = padT + i * rowH + (rowH - barH) / 2;
      const w = ((W - padL - padR) * d.power) / max;

      sctx.fillStyle = muted;
      sctx.font = '600 15px Segoe UI, system-ui, sans-serif';
      sctx.textAlign = 'right';
      sctx.textBaseline = 'middle';
      sctx.fillText(d.name, padL - 14, y + barH / 2);

      sctx.fillStyle = 'rgba(255,255,255,0.06)';
      sctx.fillRect(padL, y, W - padL - padR, barH);

      const grad = sctx.createLinearGradient(padL, 0, padL + w, 0);
      grad.addColorStop(0, accent);
      grad.addColorStop(1, accent2);
      sctx.fillStyle = grad;
      sctx.beginPath();
      if (sctx.roundRect) sctx.roundRect(padL, y, w, barH, barH / 2);
      else sctx.rect(padL, y, w, barH);
      sctx.fill();

      sctx.fillStyle = muted;
      sctx.textAlign = 'left';
      sctx.fillText(fmt(d.power), padL + w + 10, y + barH / 2);
    });
  }

  const refreshStatsBtn = $('#refreshStatsBtn');
  if (refreshStatsBtn) {
    refreshStatsBtn.addEventListener('click', function () {
      drawChart();
      toast('Analytics recalculated', 'good');
    });
  }

  /* ============================== Hero counters + typed ============================== */
  const statFightersEl = $('#statFighters');
  const statPowerEl = $('#statPower');
  const statBallsEl = $('#statBalls');
  let heroCounted = false;

  function countUp(el, target) {
    if (!el) return;
    if (REDUCED) { el.textContent = fmt(target); return; }
    const start = performance.now();
    const dur = 1100;
    function step(now) {
      const t = clamp((now - start) / dur, 0, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = fmt(target * eased);
      if (t < 1) window.requestAnimationFrame(step);
      else el.textContent = fmt(target);
    }
    window.requestAnimationFrame(step);
  }

  function updateHeroCounters(ballCount) {
    if (!heroCounted) {
      heroCounted = true;
      const peak = FIGHTERS.reduce(function (m, f) { return Math.max(m, maxPowerOf(f)); }, 0);
      countUp(statFightersEl, FIGHTERS.length);
      countUp(statPowerEl, peak);
    }
    if (statBallsEl) {
      const n = typeof ballCount === 'number' ? ballCount : collection.filter(Boolean).length;
      statBallsEl.textContent = n + '/7';
    }
  }

  const typedEl = $('#typed');
  const phrases = [
    'Ten fighters. Infinite transformations. One wish.',
    'Simulate battles, scan for Dragon Balls, charge your ki.',
    'Power levels recalculate the moment you transform.'
  ];
  if (typedEl) {
    if (REDUCED) {
      typedEl.textContent = phrases[0];
    } else {
      let pi = 0;
      let ci = 0;
      let deleting = false;
      (function type() {
        const p = phrases[pi];
        typedEl.textContent = p.slice(0, ci);
        if (!deleting && ci < p.length) { ci++; window.setTimeout(type, 42); }
        else if (!deleting) { deleting = true; window.setTimeout(type, 1700); }
        else if (ci > 0) { ci--; window.setTimeout(type, 20); }
        else { deleting = false; pi = (pi + 1) % phrases.length; window.setTimeout(type, 320); }
      })();
    }
  }

  /* ============================== Boot ============================== */
  window.addEventListener('scroll', syncNav, { passive: true });
  window.addEventListener('resize', function () {
    drawChart();
    paintRadar();
  });

  renderRoster();
  renderBattleCards();
  renderBalls();
  renderWishLog();
  drawChart();
  paintRadar();
  syncNav();
  kiPaint();
  updateHeroCounters();
})();
