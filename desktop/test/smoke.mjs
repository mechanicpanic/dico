// Off-screen smoke test: the real CLI behind a fake Tauri bridge, every mode rendered.
import { JSDOM } from 'jsdom';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
const html = readFileSync(path.join(here, '../ui/index.html'), 'utf8').replace('<script src="app.js"></script>', '');
const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://localhost/' });
const { window } = dom;
const calls = [];
window.__TAURI__ = {
  core: {
    invoke: async (cmd, args) => {
      calls.push(cmd);
      if (cmd !== 'dico') return '';
      return execFileSync('python3', [path.join(repo, 'dico.py'), ...args.args], { encoding: 'utf8', env: { ...process.env, DICO_STORE: process.env.DICO_STORE } });
    },
    convertFileSrc: p => 'asset://' + p,
  },
  event: { listen: () => {} },
};
window.matchMedia = () => ({ matches: true, addEventListener() {} });
window.localStorage.clear();
window.Audio = class { play() {} };
window.eval(readFileSync(path.join(here, '../ui/app.js'), 'utf8'));
const $ = s => window.document.querySelector(s);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const until = async (f, ms = 30000) => { const t = Date.now(); while (!f()) { if (Date.now() - t > ms) throw new Error('timeout'); await sleep(50); } };
const text = () => $('#body').textContent.replace(/\s+/g, ' ');
let fails = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? '✓' : '✗'} ${name}${detail ? ' — ' + detail : ''}`); if (!ok) fails++; };
const run = (q, mode) => { window.dico.run(q, mode); };

// Empty state, first run.
check('first run: try one', text().includes('try one') && text().includes('cook'));

run('cook', 'mot'); await until(() => $('.card'));
check('word card: two panes', !!$('.left') && !!$('.right'), $('.head')?.textContent);
check('word card: senses numbered', $('.sense.first')?.textContent.includes('1'));
await until(() => $('#pane .def-head') || $('#pane .issue'), 40000);
check('definitions pane', !!$('#pane .def-head'), $('#pane .def-head')?.textContent.slice(0, 40));
window.dico.openPane('exemples'); await until(() => $('#pane .ex') || $('#pane .issue'), 40000);
check('examples pane', !!$('#pane .ex'));

run('dire', 'conjuguer'); await until(() => $('.grid'));
check('conjugation grid: 7 tenses', $('.grid') && $('.grid').querySelectorAll('.h').length === 7);
check('endings in blue', !!$('.grid .e'));

run('elle est parti hier', 'grammaire'); await until(() => $('.sent'));
check('grammar: span + correction', !!$('.sent .g') && $('.fixbox')?.textContent.includes('partie'));

run('i have to go', 'rayonsX'); await until(() => $('.tiles'), 40000);
check('x-ray: translated first', !!$('.translated') && $('.tiles').querySelectorAll('.tile').length >= 3, $('.translated .to')?.textContent);
$('.tile').click(); await sleep(50);
check('x-ray: detail on click', !!$('.detail'));

window.dico.setMode('cartes'); await until(() => $('.rev .front') || $('.rev .big'));
check('cards: a card or nothing due', !!($('.rev .front') || $('.rev .big')), $('.rev .front')?.textContent);
if ($('.rev .front')) { (window.dico.state.review.revealed = true, window.dico.render()); check('cards: grades', $('.rev .grades').querySelectorAll('[data-grade]').length === 4); }

window.dico.showSheet('keys'); check('shortcuts sheet', $('#sheet .sheet')?.textContent.includes('Alt+D'));
window.dico.showSheet('settings'); check('settings sheet', $('#sheet .settings')?.textContent.includes('Appearance'));
console.log(fails ? `✗ ${fails} failure(s)` : '✓ all good');
process.exit(fails ? 1 : 0);
