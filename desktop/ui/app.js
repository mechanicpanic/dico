// Dico — the panel's brain. Every lookup is `dico --json …` through Tauri.
'use strict';
// Diagnostics: a release build has no console, so milestones and errors go to ~/.dico/desktop.log.
const dlog = m => { try { window.__TAURI__.core.invoke('log', { msg: String(m) }); } catch (e) {} };
window.addEventListener('error', e => dlog(`error: ${e.message} @${e.filename || ''}:${e.lineno || 0}:${e.colno || 0}`));
window.addEventListener('unhandledrejection', e => dlog(`rejection: ${e.reason && (e.reason.stack || e.reason.message) || e.reason}`));
dlog(`boot: tauri=${!!window.__TAURI__} dark=${matchMedia('(prefers-color-scheme: dark)').matches} ls=${(() => { try { return typeof localStorage.getItem('x'); } catch (e) { return 'THROWS ' + e.message; } })()}`);
const T = window.__TAURI__;
const invoke = T.core.invoke;
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const MODES = ['mot', 'conjuguer', 'grammaire', 'rayonsX', 'demander', 'cartes'];
const PLACEHOLDER = { mot: 'a word, a sentence, a question…', conjuguer: 'a verb to conjugate…', grammaire: 'a sentence to correct…', rayonsX: 'a sentence to dissect…', demander: 'a question for the tutor…' };
const CYR = /[Ѐ-ӿ]/;
const stars = b => ({ 'très courant': '★★★', 'courant': '★★', 'moyen': '★' }[b] || '');
const gender = g => g ? `<span class="g ${g}">${g}</span>` : '';
const cefr = c => c ? `<span class="cefr ${c[0]}">${esc(c)}</span>` : '';

const state = {
  mode: 'mot', query: '', outcome: { kind: 'vide' }, busy: false, gen: 0,
  card: null, term: '', isVerb: false, pane: null, panes: {}, askContext: null,
  review: { cards: [], i: 0, revealed: false, counts: null, graded: 0, loading: false, error: null },
  home: null, recent: JSON.parse(localStorage.getItem('dico.recent') || '[]'),
  zoom: parseFloat(localStorage.getItem('dico.zoom') || '1'), theme: localStorage.getItem('dico.theme') || 'system',
  sheet: null,
};

// ---------- CLI ----------
async function cli(args) {
  const out = await invoke('dico', { args });
  const end = out.lastIndexOf('}');
  const text = end >= 0 ? out.slice(out.indexOf('{'), end + 1) : out;
  try { return JSON.parse(text); } catch { throw new Error(out.trim().split('\n').pop() || 'dico answered nothing'); }
}
const lookup = q => cli(['--json', q]);

// ---------- Appearance / zoom ----------
function applyTheme() {
  const dark = state.theme === 'dark' || (state.theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
function applyZoom(z, save = true) {
  state.zoom = Math.min(1.6, Math.max(0.8, Math.round(z * 100) / 100));
  document.documentElement.style.setProperty('--z', state.zoom);
  if (save) localStorage.setItem('dico.zoom', state.zoom);
  invoke('resize', { width: Math.round(600 * state.zoom) + 64, height: Math.round(460 * state.zoom) + 64 });
}

// ---------- Toast ----------
let toastTimer;
function flash(msg) {
  const t = $('#toast'); const ok = msg.startsWith('✓ ');
  t.innerHTML = `<span>${ok ? '<b>✓</b>' : ''}${esc(ok ? msg.slice(2) : msg)}</span>`; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2000);
}

// ---------- Recent + home ----------
function remember(q) {
  const t = q.trim(); if (!t) return;
  state.recent = [t, ...state.recent.filter(r => r.toLowerCase() !== t.toLowerCase())].slice(0, 8);
  localStorage.setItem('dico.recent', JSON.stringify(state.recent));
}
let homeAt = 0;
async function refreshHome(force) {
  if (!force && Date.now() - homeAt < 20000) return;
  homeAt = Date.now();
  try { state.home = await cli(['--json', '--due']); if (state.outcome.kind === 'vide' && state.mode !== 'cartes') render(); } catch {}
}

// ---------- Mode ----------
function setMode(m, resubmit = true) {
  if (state.mode === m) return;
  state.mode = m; $('#panel').dataset.mode = m;
  document.querySelectorAll('.rail-item').forEach(b => b.classList.toggle('active', b.dataset.mode === m));
  $('#q').placeholder = PLACEHOLDER[m] || '';
  if (m === 'cartes') { startReview(); render(); return; }
  if (resubmit && state.query.trim()) submit(); else render();
  setTimeout(() => $('#q').focus(), 30);
}
const cycleMode = d => setMode(MODES[(MODES.indexOf(state.mode) + d + 6) % 6]);

// ---------- Submit ----------
function clearResults() { state.gen++; state.busy = false; state.outcome = { kind: 'vide' }; state.card = null; state.pane = null; state.panes = {}; render(); }
function clearAll() { state.query = ''; $('#q').value = ''; state.askContext = null; clearResults(); }
async function submit() {
  const q = state.query.trim(); if (!q || state.mode === 'cartes') { if (!q) clearResults(); return; }
  const gen = ++state.gen; const mode = state.mode; const ctx = state.askContext;
  if (mode !== 'demander') state.askContext = null;
  state.busy = true; state.outcome = { kind: 'chargement' }; state.card = null; state.pane = null; state.panes = {}; render();
  try {
    let o;
    if (mode === 'mot') {
      const l = await lookup(q);
      if (l.error && !(l.senses || []).length && !l.translation) throw new Error(l.error);
      o = { kind: 'mot', l };
    } else if (mode === 'conjuguer') {
      const r = await cli(['--json', '-c', q]); const c = r.conjugation || {};
      if (c.error) throw new Error(c.error); if (!c.infinitive || !c.tenses) throw new Error(`« ${q} » is not a verb I know how to conjugate.`);
      o = { kind: 'conjugaison', c };
    } else if (mode === 'grammaire') {
      const r = await cli(['--json', '-g', q]); if (!r.grammar) throw new Error('No grammar analysis'); o = { kind: 'grammaire', g: r.grammar, r };
    } else if (mode === 'rayonsX') {
      const r = await cli(['--json', '-x', q]); if (!(r.xray || []).length) throw new Error('Nothing to dissect'); o = { kind: 'rayonsX', r, sel: null };
    } else {
      const args = ['--json', '-a', q]; if (ctx) args.push('--context', ctx);
      const r = await cli(args); if (r.error) throw new Error(r.error); o = { kind: 'reponse', a: r };
    }
    if (gen !== state.gen) return;
    state.busy = false; state.outcome = o; remember(q);
    if (o.kind === 'mot') adopt(o.l, q);
  } catch (e) {
    if (gen !== state.gen) return;
    state.busy = false; state.outcome = { kind: 'erreur', msg: e.message || String(e) };
  }
  render();
}
function adopt(l, q) {
  state.card = l; state.source = q;
  if (l.direction === 'fr') { state.term = l.lexique?.lemma || l.query || q; state.isVerb = (l.lexique?.pos || '').includes('verbe') || (l.senses?.[0]?.pos || '').includes('verbe'); }
  else { const f = l.senses?.[0]; state.term = f?.term || l.translation || q; state.isVerb = (f?.pos || '').includes('verbe'); }
  openPane('definitions');
}
function offered() { const s = ['definitions', 'russe', 'exemples']; if (state.isVerb) s.push('conjugaison'); return s; }
async function openPane(p) {
  if (!state.card || !offered().includes(p)) return false;
  state.pane = p; render();
  if (state.panes[p]) return true;
  state.panes[p] = { loading: true }; render();
  const gen = state.gen; const term = state.term;
  try {
    let data;
    if (p === 'definitions') { const r = await cli(['--json', '-f', term]); if (!r.definition || !(r.definition.defs || []).length) throw new Error(r.definition_error ? `Wiktionary: ${r.definition_error}` : `No Wiktionary entry for « ${term} » (needs the internet).`); data = r.definition; }
    else if (p === 'russe') { const r = await cli(['--json', '-m', term]); data = r.multitran || {}; if (data.error && !(data.groups || []).length && !(data.lines || []).length && !(data.wiktionary_ru || []).length) throw new Error(data.error); }
    else if (p === 'exemples') { const r = await cli(['--json', '--examples', term]); data = r.examples || { en: [], ru: [] }; }
    else { const r = await cli(['--json', '-c', term]); data = r.conjugation; if (!data || data.error) throw new Error(data?.error || 'no conjugation'); }
    if (gen !== state.gen) return; state.panes[p] = { data };
  } catch (e) { if (gen !== state.gen) return; state.panes[p] = { error: e.message }; }
  render(); return true;
}

// ---------- Saving ----------
async function saveTerm(term, sens, shown, extra = []) {
  try {
    const r = await cli(['--json', '--save-term', term, '--sens', sens, ...extra]);
    flash(`✓ « ${r.saved || shown} » ${r.status || 'added'}`); refreshHome(true);
  } catch (e) { flash(`⚠︎ not saved — ${e.message}`); }
}
function saveSense(n) {
  const o = state.outcome;
  if (o.kind === 'mot') { const s = (o.l.senses || [])[n - 1]; if (!s) return; const term = s.term || o.l.head || o.l.query; const sens = o.l.direction === 'fr' ? (s.front || s.term || (s.terms || [])[0] || '') : state.source; const ex = (o.l.examples || [])[0] || []; const extra = ex[0] ? ['--example', ex[0], '--example-en', ex[1] || ''] : []; saveTerm(term, sens, s.front || term, extra); }
  else if (o.kind === 'conjugaison' && n === 1) saveTerm(o.c.infinitive, o.c.infinitive, o.c.infinitive);
}
function saveCurrent() {
  const o = state.outcome;
  if (o.kind === 'mot' || o.kind === 'conjugaison') return saveSense(1), true;
  if (o.kind === 'grammaire') return saveCorrection(o.g);
  if (o.kind === 'reponse') return saveAnswer(o.a);
  const q = state.query.trim(); if (!q || state.mode === 'cartes') return false;
  const w = q.split(/\s+/).length; saveTerm(q, '', q, ['--tier', w > 5 ? 'sentence' : (w > 1 ? 'phrase' : 'word')]); return true;
}
function saveCorrection(g) { if (!g.corrected) return false; saveTerm(g.corrected, '', g.corrected, ['--tier', 'sentence']); return true; }
function saveAnswer(a) { const text = (a.answer || '').trim(); const front = state.askContext || state.query.trim(); if (!text || !front) return false; saveTerm(front, text, front, ['--tier', 'tutor']); return true; }

// ---------- Review ----------
async function startReview() {
  const r = state.review; r.loading = true; r.error = null; render();
  try { const d = await cli(['--json', '--due']); r.cards = d.cards || []; r.counts = d.counts || {}; r.i = 0; r.revealed = false; r.total = d.total; fillCurrent(); }
  catch (e) { r.error = e.message; }
  r.loading = false; render();
}
async function fillCurrent() {
  const r = state.review; const c = r.cards[r.i]; if (!c || (c.back || []).length) return;
  const i = r.i; try { const d = await cli(['--json', '--card', c.key]); if (d.card && r.i === i) { r.cards[i] = d.card; render(); } } catch {}
}
async function grade(ease) {
  const r = state.review; const c = r.cards[r.i]; if (!r.revealed || !c) return;
  try { await cli(['--json', '--grade', c.key, '--ease', String(ease)]); } catch (e) { r.error = e.message; render(); return; }
  r.graded++; if (ease === 1) r.cards.push(c); r.i++; r.revealed = false;
  if (!r.cards[r.i]) startReview(); else { fillCurrent(); render(); }
}
function reviewKey(e) {
  if (state.mode !== 'cartes') return false; const r = state.review;
  if (e.key === ' ' || e.key === 'Enter') { if (r.revealed) grade(3); else if (r.cards[r.i]) { r.revealed = true; render(); } return true; }
  if (r.revealed && /^[1-4]$/.test(e.key)) { grade(+e.key); return true; }
  return false;
}

// ---------- Render ----------
function render() {
  const p = $('#panel'); const body = $('#body'); const bar = $('#querybar'); const foot = $('#footer');
  $('#flag').textContent = CYR.test(state.query) ? '🇷🇺' : '🇫🇷';
  $('#busy').hidden = !state.busy; $('#clear').hidden = state.busy || !state.query; bar.classList.toggle('busy', state.busy);
  const ctx = $('#ctx'); ctx.hidden = !(state.mode === 'demander' && state.askContext); if (!ctx.hidden) ctx.innerHTML = `about « ${esc(state.askContext)} » <span style="font-size:9px;opacity:.7">✕</span>`;
  const cards = state.mode === 'cartes'; bar.hidden = cards; foot.hidden = cards || state.outcome.kind === 'mot';
  body.className = 'body'; body.innerHTML = '';
  if (cards) return renderReview(body);
  const o = state.outcome;
  if (o.kind === 'vide') return renderEmpty(body);
  if (o.kind === 'chargement') { body.innerHTML = `<div class="loading">${state.mode === 'demander' ? 'thinking…' : 'searching…'}</div>`; return; }
  if (o.kind === 'mot') return renderCard(body, o.l);
  body.classList.add('pad');
  if (o.kind === 'conjugaison') return renderConj(body, o.c, false);
  if (o.kind === 'grammaire') return renderGrammar(body, o);
  if (o.kind === 'rayonsX') return renderXray(body, o);
  if (o.kind === 'reponse') return renderAnswer(body, o.a);
  body.innerHTML = `<div class="issue"><div class="eyebrow rouge">problem<span class="line"></span></div><div class="msg">${esc(o.msg)}</div><div class="k">Esc clears · Ctrl+/ lists every shortcut</div></div>`;
}
function eyebrow(text, cls = '', trailing = '') { return `<div class="eyebrow ${cls}">${esc(text)}<span class="line"></span>${trailing}</div>`; }

function renderEmpty(body) {
  const seasoned = state.recent.length || (state.home?.total > 0);
  const w = el('div', 'empty');
  if (seasoned) {
    const h = state.home; const c = h?.counts || {}; const waiting = (c.due || 0) + (c.learning || 0) + Math.min(c.new || 0, 20);
    let s = eyebrow('today', '', `<span class="tr">${h ? `${h.total} words in the deck` : ''}</span>`);
    s += `<div style="display:flex;gap:12px;align-items:baseline;margin-top:9px;font-size:calc(12.5px*var(--z))">`;
    if (waiting > 0) s += `<span>${waiting} card${waiting === 1 ? '' : 's'} to review <span class="ink-45">— ${c.due || 0} due · ${c.learning || 0} learning · ${c.new || 0} new</span></span><button class="tint jaune" data-act="review">Review <span class="k">Ctrl+6</span></button>`;
    else s += `<span class="ink-55">${h ? 'Nothing to review. Every word you look up becomes a card.' : '…'}</span>`;
    s += `</div>`;
    if (h?.recent?.length) s += `<div style="margin-top:8px">${eyebrow('saved lately')}<div class="chips" style="margin-top:6px">${h.recent.map(r => `<button data-run="${esc(r.front)}">${esc(r.front)}<span class="g">${esc(r.gloss || '')}</span></button>`).join('')}</div></div>`;
    w.appendChild(el('div', '', s));
  } else {
    w.appendChild(el('div', '', eyebrow('try one') + `<div class="try" style="margin-top:9px">${[['cook', 'a word', 'mot'], ['maison', 'a French word', 'mot'], ['aller', 'a verb to conjugate', 'conjuguer'], ['elle est parti', 'to correct', 'grammaire']].map(([q, what, m]) => `<button data-run="${q}" data-m="${m}"><span class="serif">${q}</span><span class="what">${what}</span></button>`).join('')}</div>`));
  }
  if (state.recent.length) w.appendChild(el('div', '', eyebrow('recent', '', '<button class="link dim tr" data-act="forget">Clear</button>') + `<div class="chips" style="margin-top:6px">${state.recent.map(r => `<button data-run="${esc(r)}">${esc(r)}</button>`).join('')}</div>`));
  else if (!seasoned) w.appendChild(el('div', 'ink-30', 'Alt+D opens this from any app · Ctrl+/ shows every shortcut'));
  body.appendChild(w);
}

function renderCard(body, l) {
  const fr = l.direction === 'fr'; const lx = l.lexique || {};
  const head = fr ? (l.head || l.query) : (l.translation || l.senses?.[0]?.term || '');
  const g = fr ? lx.genre : l.senses?.[0]?.gender;
  const flag = CYR.test(l.query || '') ? '🇷🇺' : (l.src_lang === 'fr' ? '🇫🇷' : '🇬🇧');
  let left = `<div><div class="head">${esc(head)}${gender(g)}</div><div class="badges">${lx.ipa ? `<span>/${esc(lx.ipa)}/</span>` : ''}${cefr(lx.cefr)}${stars(lx.band) ? `<span class="star">${stars(lx.band)}</span>` : ''}</div>${fr ? '' : `<div class="src">${flag} ${esc(l.query)}</div>`}</div>`;
  const groups = []; (l.senses || []).forEach((s, i) => { const k = s.pos || '—'; let gr = groups.find(x => x.k === k); if (!gr) groups.push(gr = { k, items: [] }); gr.items.push([i + 1, s]); });
  left += `<div>` + groups.map(gr => `<div class="pos">${esc(gr.k)}</div>` + gr.items.map(([n, s]) => `<button class="sense ${n === 1 ? 'first' : ''}" data-save="${n}"><span class="n">${n}</span><span class="t">${esc(s.front || s.term || (s.terms || [])[0] || '?')}</span>${gender(s.gender)}${cefr(s.cefr)}<span class="k">Ctrl+${n}</span></button>`).join('')).join('') + `</div>`;
  const ex = (l.examples || [])[0]; if (ex && ex.length >= 2) left += exLine(ex[0], ex[1]);
  const tabs = offered().map(p => `<button class="tab ${state.pane === p ? 'active' : ''} ${p === 'russe' ? 'rose' : ''}" data-pane="${p}">${{ definitions: 'Definitions', russe: 'Russian', exemples: 'Examples', conjugaison: 'Conj.' }[p]}</button>`).join('');
  body.innerHTML = `<div class="card"><div class="left">${left}</div><div class="right"><div class="tabs">${tabs}</div><div class="pane" id="pane"></div><div class="actions"><button class="emoji" data-act="say" title="Hear it (Ctrl+P)">🔈</button><button class="emoji" data-act="ask" title="Ask the tutor (Ctrl+L)">💬</button><span class="keyhint">${offered().map(p => ({ definitions: 'Ctrl+D', russe: 'Ctrl+R', exemples: 'Ctrl+E', conjugaison: 'Ctrl+J' }[p])).join(' ')}</span></div></div></div>`;
  renderPane($('#pane'));
}
function exLine(fr, en, ru = false, save = true) { return `<div class="ex ${ru ? 'ru' : ''}"><span class="fr">${esc(fr)}${save ? `<button class="save" data-savex="${esc(fr)}" data-savet="${esc(en)}">save</button>` : ''}</span>${en ? `<span class="en">${ru ? '🇷🇺 ' : ''}${esc(en)}</span>` : ''}</div>`; }
function renderPane(pane) {
  const p = state.pane; const st = state.panes[p];
  if (!p) { pane.innerHTML = `<span class="ink-35">Pick a pane above.</span>`; return; }
  if (!st || st.loading) { pane.innerHTML = `<div class="loading ink-45" style="justify-content:flex-start;height:auto">loading…</div>`; return; }
  if (st.error) { pane.innerHTML = `<div class="issue"><div class="eyebrow rouge">problem<span class="line"></span></div><div class="msg">${esc(st.error)}</div></div><button class="link" data-act="retry">Try again</button>`; return; }
  const d = st.data;
  if (p === 'definitions') {
    let s = `<div class="def-head"><span class="w">${esc(d.word)}</span>${d.ipa ? `<span class="ipa">[${esc(d.ipa)}]</span>` : ''}${d.pos ? `<span class="p">${esc(d.pos)}</span>` : ''}${gender(d.gender)}${cefr(d.cefr)}</div>`;
    s += (d.defs || []).map((x, i) => `<div class="def"><span class="n">${i + 1}</span><span>${esc(x)}</span></div>`).join('');
    if (d.etym) s += `<div class="etym">${esc(d.etym)}</div>`;
    const words = a => a.map(w => `${esc(w.word)}${w.note ? ` <i>${esc(w.note)}</i>` : ''}`).join(' · ');
    if ((d.syn || []).length) s += `<div class="note"><span class="l">≈ syn.</span><span class="b">${words(d.syn)}</span></div>`;
    if ((d.homo || []).length) s += `<div class="note"><span class="l">♪ homo.</span><span class="b">${words(d.homo)}</span></div>`;
    if ((d.ru || []).length) s += `<div class="note"><span class="l">🇷🇺 ru</span><span class="b">${d.ru.map(t => `${esc(t.word)}${t.tr ? ` <span class="tr">${esc(t.tr)}</span>` : ''}${gender(t.gender)}`).join(' · ')}</span></div>`;
    pane.innerHTML = s;
  } else if (p === 'russe') {
    let s = `<div class="mono ink-30" style="font-size:calc(9px*var(--z))">${d.direction === 'rufr' ? 'ru → fr' : 'fr → ru'}</div>`;
    const groups = (d.groups || []).filter(g => (g.senses || []).length);
    if (groups.length) s += groups.map(g => (g.pos ? eyebrow(g.pos, 'rose') : '') + (g.senses || []).map(se => `<div class="mt-row"><span class="l">${esc([se.n, se.domain].filter(Boolean).join(' '))}</span><span class="b">${(se.items || []).filter(it => (it.tr || '').trim()).map(it => `${esc(it.tr)}${it.note ? ` <i>${esc(it.note)}</i>` : ''}`).join('<span class="sep"> · </span>')}</span></div>`).join('')).join('');
    else if ((d.wiktionary_ru || []).length) s += eyebrow('Wiktionnaire', 'rose') + d.wiktionary_ru.map(t => `<div style="display:flex;gap:7px;align-items:baseline"><span class="serif" style="font-size:calc(15.5px*var(--z))">${esc(t.word)}</span>${t.tr ? `<span class="mono ink-35" style="font-size:calc(10px*var(--z))">[${esc(t.tr)}]</span>` : ''}${gender(t.gender)}</div>`).join('');
    else s += (d.lines || []).map(line => { const h = !line.includes(')') && line.length <= 12; if (h) return eyebrow(line, 'rose'); const m = line.match(/^(\d+)\)\s+(\S+\.)?\s*(.*)$/); return `<div class="mt-row"><span class="l">${m ? esc([m[1], m[2]].filter(Boolean).join(' ')) : ''}</span><span class="b">${esc(m ? m[3] : line)}</span></div>`; }).join('') || `<span class="ink-45">${esc(d.error || 'nothing')}</span>`;
    pane.innerHTML = s;
  } else if (p === 'exemples') {
    const own = (state.card?.examples || []).filter(e => e.length >= 2); const seen = new Set((d.en || []).map(e => (e.fr || '').toLowerCase().replace(/\s/g, '')));
    const en = own.filter(e => !seen.has(e[0].toLowerCase().replace(/\s/g, ''))).map(e => ({ fr: e[0], en: e[1] })).concat(d.en || []);
    pane.innerHTML = (en.length || (d.ru || []).length) ? en.map(e => exLine(e.fr, e.en)).join('') + (d.ru || []).map(e => exLine(e.fr, e.ru, true)).join('') : `<span class="ink-45">No examples found</span>`;
  } else renderConj(pane, d, true);
}

const HEADS = { 'présent': 'PRÉSENT', 'imparfait': 'IMPARF.', 'futur simple': 'FUTUR', 'passé composé': 'P.COMP.', 'conditionnel': 'CONDIT.', 'subjonctif': 'SUBJ.', 'impératif': 'IMPÉR.' };
const ORDER = ['présent', 'passé composé', 'imparfait', 'futur simple', 'conditionnel', 'subjonctif', 'impératif'];
const AUX = new Set(['ai', 'as', 'a', 'avons', 'avez', 'ont', 'suis', 'es', 'est', 'sommes', 'êtes', 'sont']);
const PRON = ['je', 'tu', 'il', 'nous', 'vous', 'ils'];
function strip(f) { let s = f; for (const p of ['que ', "qu'"]) if (s.startsWith(p)) s = s.slice(p.length); if (s.startsWith("j'")) return s.slice(2); for (const w of ['je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles']) if (s.startsWith(w + ' ')) return s.slice(w.length + 1); return s; }
function split(f) { const s = strip(f); const i = s.indexOf(' '); if (i > 0 && AUX.has(s.slice(0, i).toLowerCase())) return [s.slice(0, i), s.slice(i + 1)]; return [null, s]; }
function stem(forms) { const pairs = forms.map(split); if (pairs.some(p => p[0])) return ''; const rests = pairs.map(p => p[1]).filter(Boolean); if (!rests.length) return ''; let p = rests[0]; for (const r of rests.slice(1)) { let k = 0; while (k < p.length && k < r.length && p[k] === r[k]) k++; p = p.slice(0, k); } if (rests.some(r => r.length <= p.length)) p = p.slice(0, -1); return p; }
function form(name, forms, i) { const idx = name === 'impératif' ? [null, 0, null, 1, 2, null][i] : i; return idx == null || idx >= forms.length ? null : forms[idx]; }
function cell(raw, st) { if (raw == null) return `<span class="none">—</span>`; const [aux, rest] = split(raw); if (aux) return `<span class="aux">${esc(aux)} </span>${esc(rest)}`; if (st && rest.startsWith(st) && rest.length > st.length) return `${esc(st)}<span class="e">${esc(rest.slice(st.length))}</span>`; return esc(rest); }
function renderConj(root, c, compact) {
  const tenses = ORDER.filter(k => c.tenses[k]).map(k => [k, c.tenses[k]]).concat(Object.entries(c.tenses).filter(([k]) => !ORDER.includes(k)));
  if (compact) { root.innerHTML = `<div class="stack">${tenses.map(([name, forms]) => { const st = stem(forms); return `${eyebrow(name, name === 'présent' ? 'bleu' : '')}<div class="rows">${[0, 3].map(s => [0, 1, 2].map(j => `<span><span class="pr mono ink-30" style="font-size:calc(9.5px*var(--z))">${PRON[s + j]}</span><span>${cell(form(name, forms, s + j), st)}</span></span>`).join('')).join('')}</div>`; }).join('')}</div>`; return; }
  const inf = c.infinitive || ''; const pc = c.tenses['passé composé']?.[0]; const aux = pc && split(pc)[0]; const auxV = aux ? (['ai', 'as', 'a', 'avons', 'avez', 'ont'].includes(aux) ? 'avoir' : 'être') : null;
  const group = inf === 'aller' ? '3ᵉ groupe' : inf.endsWith('er') ? '1ᵉʳ groupe' : (inf.endsWith('ir') && strip(c.tenses['présent']?.[3] || '').endsWith('issons')) ? '2ᵉ groupe' : '3ᵉ groupe';
  let g = `<div class="conj-head"><span class="inf">${esc(inf)}</span><span class="meta">${group}${auxV ? ` · aux. <b>${auxV}</b>` : ''}</span><span class="end">endings in <span class="m">blue</span></span></div>`;
  g += `<div class="grid"><div></div>${tenses.map(([n]) => `<div class="h ${n === 'présent' ? 'p' : ''}" title="${esc(n)}">${HEADS[n] || n.slice(0, 7).toUpperCase()}</div>`).join('')}`;
  for (let i = 0; i < 6; i++) { g += `<div class="c pr ${i === 5 ? 'last' : ''}">${PRON[i]}</div>` + tenses.map(([n, forms]) => `<div class="c ${n === 'présent' ? 'p' : ''} ${i === 5 ? 'last' : ''}" title="${esc(form(n, forms, i) || '')}">${cell(form(n, forms, i), stem(forms))}</div>`).join(''); }
  g += `</div><div class="conj-foot">Hover a heading for the tense · <span class="ink-55">Ctrl+1</span> saves the infinitive.</div>`;
  root.innerHTML = g;
}

const LABELS = [['participle', 'ACCORD'], ['agreement', 'ACCORD'], ['singular', 'NOMBRE'], ['conjugation', 'CONJ.'], ['verb', 'VERBE'], ['infinitive', 'INFIN.'], ['imperative', 'IMPÉR.'], ['question', 'QUEST.'], ['confusion', 'CONFUS'], ['typography', 'TYPO.'], ['spacing', 'ESPACE'], ['non-breaking', 'ESPACE'], ['capital', 'MAJ.'], ['apostrophe', 'APOS.'], ['phrasing', 'STYLE'], ['redundancy', 'STYLE'], ['pleonasm', 'STYLE'], ['number', 'NOMBRE'], ['punctuation', 'PONCT.'], ['comma', 'VIRG.'], ['compound', 'MOT']];
const label = t => { t = (t || '').toLowerCase(); for (const [n, l] of LABELS) if (t.includes(n)) return l; if (!t) return 'RÈGLE'; const w = t.split(' ')[0]; return w.length > 6 ? w.slice(0, 5).toUpperCase() + '.' : w.toUpperCase(); };
function translatedLine(r) { return r.translated && r.source ? `<div class="translated"><div class="from"><span>${CYR.test(r.source) ? '🇷🇺' : '🇬🇧'}</span><span>${esc(r.source)}</span><span class="ink-30">→</span><span>🇫🇷</span></div><div class="to">${esc(r.translated)}</div><div class="n">translated first — the analysis reads French</div></div>` : ''; }
function renderGrammar(body, o) {
  const g = o.g; const sentence = o.r.sentence || state.query.trim(); const cps = Array.from(sentence); const kind = new Array(cps.length).fill(0);
  (g.errors || []).forEach(e => { for (let i = Math.max(0, e.start); i < Math.min(cps.length, e.end); i++) kind[i] = 1; });
  (g.spelling || []).forEach(e => { for (let i = Math.max(0, e.start); i < Math.min(cps.length, e.end); i++) if (!kind[i]) kind[i] = 2; });
  let s = translatedLine(o.r) + `<div class="sent">`; let buf = '', cur = kind[0] || 0;
  const flush = () => { s += cur ? `<span class="${cur === 1 ? 'g' : 's'}">${esc(buf)}</span>` : esc(buf); };
  cps.forEach((ch, i) => { if (kind[i] !== cur) { flush(); buf = ''; cur = kind[i]; } buf += ch; }); flush(); s += `</div>`;
  const errs = g.errors || [], sp = g.spelling || [];
  if (!errs.length && !sp.length) s += `<div class="ok">✓ Nothing to correct</div>`;
  else s += `<div class="notes">${errs.map(e => note(label(e.type), 'g', e.message || e.type || '', e.suggestions || [])).join('')}${sp.map(e => note('ORTHO.', 's', `« ${e.text} » is not in the dictionary.`, e.suggestions || [])).join('')}</div>`;
  if (g.corrected) s += `<div class="fixbox"><span class="t">${esc(g.corrected)}</span><button class="link vert" data-act="savefix" style="color:var(--vert-ink);font-weight:600;font-size:calc(11px*var(--z))">Save <span class="mono" style="font-size:9px;opacity:.7">Ctrl+S</span></button><button class="tint vert" data-act="copyfix">Copy <span class="k">Ctrl+Shift+C</span></button></div>`;
  body.innerHTML = s;
}
const note = (l, cls, msg, sug) => `<div class="gnote"><span class="l ${cls}">${esc(l)}</span><div><div class="msg">${esc(msg)}</div>${sug.length ? `<div class="sug">${sug.slice(0, 6).map(x => `<span>${esc(x)}</span>`).join('')}</div>` : ''}</div></div>`;

const tag = t => { const pos = (t.pos || '').toLowerCase(); let s = pos.startsWith('nom') ? 'nom' : pos.startsWith('verbe') ? 'verbe' : pos.startsWith('adjectif') ? 'adj.' : pos.startsWith('adverbe') ? 'adv.' : pos.startsWith('préposition') ? 'prép.' : pos.startsWith('article') ? 'art.' : pos.startsWith('déterminant') ? 'dét.' : pos.startsWith('pronom') ? 'pron.' : pos.startsWith('conjonction') ? 'conj.' : pos ? pos.slice(0, 6) : '?'; if (s === 'verbe' && t.tense) { const te = t.tense.split(';')[0].split('·')[0].trim(); if (te) s += ' · ' + te; } return s; };
function renderXray(body, o) {
  const toks = o.r.xray; let s = translatedLine(o.r) + `<div class="tiles">${toks.map((t, i) => `<button class="tile ${o.sel === i ? 'on' : ''}" data-tile="${i}"><span class="w ${t.gender || ''}">${esc(t.text)}</span><span class="t">${esc(tag(t))}${t.gender ? ` <b class="${t.gender}">${t.gender}</b>` : ''}</span>${t.gloss ? `<span class="gl">${esc(t.gloss)}</span>` : ''}</button>`).join('')}</div>`;
  if (o.sel != null) { const t = toks[o.sel]; const rows = [['lemma', t.lemma], ['pos', [t.pos, t.gender ? (t.gender === 'm' ? 'masculin' : 'féminin') : ''].filter(Boolean).join(' · ')], ['tense', (t.tense || '').replace(/;/g, ' · ')], ['role', t.role], ['meaning', t.gloss], ['frequency', t.band]].filter(r => r[1]);
    s += `<div class="detail">${eyebrow(t.text, t.gender === 'm' ? 'bleu' : t.gender === 'f' ? 'rose' : '', `<span class="tr"><button class="link" data-run="${esc(t.lemma || t.text)}">Look up</button> &nbsp; <button class="link dim" data-savetok="${o.sel}">save</button></span>`)}${rows.map(([k, v]) => `<div class="row"><span class="l">${k}</span><span class="${k === 'lemma' ? 'lemma' : ''}">${esc(v)}</span></div>`).join('')}</div>`; }
  else s += `<div class="hint">Click a word. Gender colours it: <span class="m">masculin</span> · <span class="f">féminin</span>. Roles come from spaCy when it is switched on.</div>`;
  body.innerHTML = s;
}

function md(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i class="serif" style="font-size:1.05em">$1</i>'); }
function renderAnswer(body, a) {
  const lines = (a.answer || '').split('\n').map(l => l.trim()).filter(Boolean);
  body.innerHTML = `<div class="answer">${lines.map(l => /^[-*—] /.test(l) ? `<div class="li"><span class="d">—</span><span>${md(l.slice(2))}</span></div>` : `<div>${md(l)}</div>`).join('')}<div class="row">${a.model ? `<span class="model">${esc(a.model)}</span>` : ''}<button class="tint rose" data-act="saveanswer">Save as card <span class="k">Ctrl+S</span></button></div></div>`;
}

function renderReview(body) {
  const r = state.review; const c = r.cards[r.i]; const cnt = r.counts || {};
  const counts = [cnt.due ? `${cnt.due} due` : '', cnt.learning ? `${cnt.learning} learning` : '', cnt.new ? `${cnt.new} new` : '', r.graded ? `${r.graded} done` : ''].filter(Boolean).join(' · ');
  let s = `<div class="rev"><div class="hd"><span>🎴</span><span class="t">Saved words</span><span class="c">${counts}</span></div><div class="bd">`;
  if (r.loading && !r.cards.length) s += `<div class="loading">asking dico…</div>`;
  else if (r.error) s += `<div class="issue"><div class="eyebrow rouge">problem<span class="line"></span></div><div class="msg">${esc(r.error)}</div></div><button class="link dim" data-act="startreview">Try again</button>`;
  else if (c) {
    s += eyebrow(c.state === 'new' ? 'new' : (c.state === 'review' ? `review · ${c.ivl} d` : 'learning'), c.state === 'new' ? 'bleu' : '', `<span class="tr mono ink-30">${r.i + 1} / ${r.cards.length}</span>`);
    s += `<div class="front">${esc(c.front)}${gender(c.gender)}</div>`;
    if (c.ipa || c.cefr || c.pos) s += `<div class="meta">${c.ipa ? `<span>/${esc(c.ipa)}/</span>` : ''}${cefr(c.cefr)}${c.pos ? `<span class="p">${esc(c.pos)}</span>` : ''}</div>`;
    if (r.revealed) { const b = c.back || []; s += `<div class="hair"></div><div class="back">${b[0] ? `<span class="m">${esc(b[0])}</span>` : ''}${b[1] ? `<span class="ex1">${esc(b[1])}</span>` : ''}${b[2] ? `<span class="ex2">${esc(b[2])}</span>` : ''}</div>`; }
    s += `<div class="grades">` + (r.revealed
      ? `<button class="tint rouge" data-grade="1">Again <span class="k">1</span></button><button class="tint jaune" data-grade="2">Hard <span class="k">2</span></button><button class="tint vert" data-grade="3">Good <span class="k">3</span></button><button class="tint" data-grade="4">Easy <span class="k">4</span></button><span class="keyhint">graded in dico's store</span>`
      : `<button class="tint" data-act="reveal">Show the answer <span class="k">Space</span></button><button class="link dim" data-run="${esc(c.front)}" style="margin-left:auto">Look it up</button>`) + `</div>`;
  } else s += `<div class="big">${r.graded ? 'Done for now.' : 'Nothing due.'}</div><div class="p">${r.graded ? `${r.graded} card${r.graded === 1 ? '' : 's'} graded. Come back tomorrow.` : 'No saved word is due. Look words up — each one becomes a card.'}</div><button class="link dim" data-act="startreview" style="align-self:flex-start">Check again</button>`;
  s += `</div></div>`; body.innerHTML = s;
}

// ---------- Sheets: shortcuts + settings ----------
const SHORTCUTS = [['Panel', 'bleu', [['Alt+D', 'Open / close, from any app'], ['Esc', 'Clear — again to close'], ['Ctrl+K', 'Clear the field'], ['Ctrl+S', 'Save as a card — the field, a correction, an answer'], ['Ctrl+= Ctrl+- Ctrl+0', 'Bigger · smaller · default size'], ['Ctrl+, Ctrl+/', 'Settings · this list']]],
  ['Modes', 'bleu', [['Tab · Shift+Tab', 'Next · previous mode'], ['Ctrl+1…Ctrl+6', '📖 Word · 🔁 Conjugate · ✅ Grammar · 🔬 X-ray · 💬 Ask · 🎴 Cards']]],
  ['Word card', 'rose', [['Ctrl+1…9', 'Save sense N'], ['Ctrl+D', 'Definitions — Wiktionary'], ['Ctrl+R', 'Russian — Multitran'], ['Ctrl+E', 'Examples — Tatoeba'], ['Ctrl+J', 'Conjugate — verbs'], ['Ctrl+L · Ctrl+P', 'Ask the tutor · hear it said']]],
  ['Grammar', 'vert', [['Ctrl+Shift+C', 'Copy the corrected sentence']]],
  ['Cards', 'jaune', [['Space · Enter', 'Show the answer — then Good'], ['1 · 2 · 3 · 4', 'Again · Hard · Good · Easy']]]];
function showSheet(kind) {
  state.sheet = kind; const s = $('#sheet'); s.hidden = false;
  if (kind === 'keys') { const col = g => g.map(([name, cls, items]) => `<div class="grp">${eyebrow(name, cls)}${items.map(([k, v]) => `<div class="kv"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`).join('')}</div>`).join('');
    s.innerHTML = `<div class="sheet"><div class="ttl"><span class="s">Shortcuts</span><span class="sub">every key the panel listens to</span><span class="k">Esc to close</span></div><div class="cols"><div class="col">${col(SHORTCUTS.slice(0, 2))}</div><div class="col">${col(SHORTCUTS.slice(2))}</div></div></div>`; }
  else { const chips = (vals, cur, key) => vals.map(([v, l]) => `<button class="chip ${String(cur) === String(v) ? 'on' : ''}" data-set="${key}" data-val="${v}">${l}</button>`).join('');
    s.innerHTML = `<div class="sheet settings"><div class="ttl"><span class="s">Settings</span><span class="k">Esc to close</span></div><div style="display:flex;flex-direction:column;gap:18px">
      <div><div class="row"><span class="l">Appearance</span>${chips([['system', 'System'], ['dark', 'Dark'], ['light', 'Light']], state.theme, 'theme')}</div></div>
      <div><div class="row"><span class="l">Size</span>${chips([[0.9, 'Small'], [1, 'Default'], [1.2, 'Large'], [1.4, 'Larger']], state.zoom, 'zoom')}</div><div class="cap" style="margin-top:6px">Ctrl+= and Ctrl+- in the panel do the same.</div></div>
      <div><div class="row"><span class="l">Hotkey</span><span class="mono">Alt+D</span></div><div class="cap" style="margin-top:6px">Opens and closes the panel from any app.</div></div>
      <div><div class="row"><span class="l">Tutor</span><span class="ink-55">edit ~/.dico_config.json — « llm »: local (LM Studio / Ollama), byok, anthropic</span></div></div>
      <div class="cap">Your words live in ~/.dico (the store, the cache, the audio). The dictionary data is unpacked there on first run.</div></div></div>`; }
}
function hideSheet() { state.sheet = null; $('#sheet').hidden = true; $('#sheet').innerHTML = ''; }

// ---------- Actions ----------
async function say(word) { if (!word) return; try { const r = await cli(['--json', '--say', word]); if (r.audio?.path) new Audio(T.core.convertFileSrc(r.audio.path)).play(); else flash(r.audio?.error || `no recording for « ${word} »`); } catch (e) { flash(e.message); } }
function askAbout(word) { state.askContext = word; setMode('demander', false); state.query = ''; $('#q').value = ''; clearResults(); }
function run(q, mode) { state.query = q; $('#q').value = q; if (mode && mode !== state.mode) setMode(mode, false); submit(); }

document.addEventListener('click', e => {
  const b = e.target.closest('button, .ex'); if (!b) { if (e.target.id === 'sheet') hideSheet(); return; }
  const d = b.dataset; const o = state.outcome;
  if (b.classList.contains('rail-item')) return setMode(d.mode);
  if (b.id === 'gear') return showSheet('settings');
  if (b.id === 'keys') return showSheet('keys');
  if (b.id === 'clear') { clearAll(); $('#q').focus(); return; }
  if (b.id === 'ctx') { state.askContext = null; render(); return; }
  if (d.run != null) return run(d.run, d.m || (state.mode === 'cartes' ? 'mot' : (b.closest('.detail') || b.closest('.rev') || b.closest('.chips') ? 'mot' : state.mode)));
  if (d.pane) return openPane(d.pane);
  if (d.save) return saveSense(+d.save);
  if (d.savex != null) { e.stopPropagation(); return saveTerm(d.savex, d.savet, d.savex, ['--tier', 'sentence']); }
  if (d.savetok != null) { const t = o.r.xray[+d.savetok]; return saveTerm(t.lemma || t.text, t.gloss || '', t.lemma || t.text); }
  if (d.tile != null) { o.sel = o.sel === +d.tile ? null : +d.tile; return render(); }
  if (d.grade) return grade(+d.grade);
  if (d.set) { if (d.set === 'theme') { state.theme = d.val; localStorage.setItem('dico.theme', d.val); applyTheme(); } else applyZoom(+d.val); return showSheet('settings'); }
  switch (d.act) {
    case 'review': return setMode('cartes');
    case 'forget': state.recent = []; localStorage.removeItem('dico.recent'); return render();
    case 'say': return say(state.term);
    case 'ask': return askAbout(state.term);
    case 'retry': { delete state.panes[state.pane]; return openPane(state.pane); }
    case 'savefix': return saveCorrection(o.g);
    case 'copyfix': navigator.clipboard.writeText(o.g.corrected); return flash('✓ corrected sentence copied');
    case 'saveanswer': return saveAnswer(o.a);
    case 'reveal': state.review.revealed = true; return render();
    case 'startreview': return startReview();
  }
});
$('#q').addEventListener('input', e => {
  state.query = e.target.value;
  const prefixes = [['-c ', 'conjuguer'], ['-g ', 'grammaire'], ['-x ', 'rayonsX'], ['? ', 'demander']];
  for (const [p, m] of prefixes) if (state.query.startsWith(p)) { state.query = state.query.slice(p.length); e.target.value = state.query; setMode(m, false); break; }
  if (!state.query.trim()) clearResults(); else render();
});
document.addEventListener('keydown', e => {
  const k = e.key; const ctrl = e.ctrlKey || e.metaKey;
  if (k === 'Escape') { e.preventDefault(); if (state.sheet) return hideSheet(); if (state.query || state.outcome.kind !== 'vide') { clearAll(); $('#q').focus(); } else invoke('hide'); return; }
  if (k === 'Tab' && !ctrl && !e.altKey) { e.preventDefault(); return cycleMode(e.shiftKey ? -1 : 1); }
  if (!ctrl && !e.altKey && reviewKey(e)) { e.preventDefault(); return; }
  if (!ctrl) return;
  const key = k.toLowerCase(); const o = state.outcome;
  if (key === '/') { e.preventDefault(); return state.sheet === 'keys' ? hideSheet() : showSheet('keys'); }
  if (key === ',') { e.preventDefault(); return state.sheet === 'settings' ? hideSheet() : showSheet('settings'); }
  if (key === '=' || key === '+') { e.preventDefault(); return applyZoom(state.zoom + 0.1); }
  if (key === '-') { e.preventDefault(); return applyZoom(state.zoom - 0.1); }
  if (key === '0') { e.preventDefault(); return applyZoom(1); }
  if (/^[1-9]$/.test(key)) { e.preventDefault(); const n = +key; if (e.altKey || (state.outcome.kind === 'vide' && n <= 6)) return setMode(MODES[n - 1]); return saveSense(n); }
  if (e.shiftKey && key === 'c' && o.kind === 'grammaire' && o.g.corrected) { e.preventDefault(); navigator.clipboard.writeText(o.g.corrected); return flash('✓ corrected sentence copied'); }
  const panes = { d: 'definitions', r: 'russe', e: 'exemples', j: 'conjugaison' };
  if (panes[key] && state.card) { e.preventDefault(); return openPane(panes[key]); }
  if (key === 'k') { e.preventDefault(); clearAll(); return $('#q').focus(); }
  if (key === 's') { e.preventDefault(); return saveCurrent(); }
  if (key === 'l' && state.term) { e.preventDefault(); return askAbout(state.term); }
  if (key === 'p' && state.term) { e.preventDefault(); return say(state.term); }
});
$('#q').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
T.event.listen('dico:shown', () => { refreshHome(); if (state.mode !== 'cartes') setTimeout(() => $('#q').focus(), 30); });

// ---------- Boot ----------
applyTheme(); applyZoom(state.zoom, false);
document.querySelector('.rail-item[data-mode="mot"]').classList.add('active');
render(); refreshHome(true); $('#q').focus();
dlog(`booted: theme=${document.documentElement.dataset.theme} body=${$('#body').innerHTML.length} zoom=${state.zoom}`);

// For the off-screen smoke test (test/smoke.mjs).
window.dico = { run, setMode, openPane, showSheet, render, state };
