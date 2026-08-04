import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../../config/env';
import {
  ensureEditorialFonts,
  EDITORIAL_TOKENS,
  PAPER_GROUND,
} from './editorialTheme_aaron';

/**
 * The signed-in home: one box, and nothing else.
 *
 * WHAT IT REPLACED. First a marketing-shaped page — headline, buttons, four round numbers — aimed
 * at someone who had already signed in. Then a version of this that led with a gene search but
 * still carried a statistics rule and four destination cards under it. Both were answering a
 * question nobody arriving here is asking. A researcher reaching this screen holds exactly one of
 * three things: a gene symbol, a screen they remember, or a ranked list from their own bench. So
 * the page is the box that takes all three, and the destinations are reached by using it.
 *
 *   the mode chip     gene | screen — which index the box searches
 *   the + button      the third case: bring a ranked gene list of your own
 *   the type-ahead    what makes the box worth having, see below
 *
 * THE TYPE-AHEAD IS THE POINT. Typing "PO" answers POLR2A, POLR2B, POLR2E, POLD1 — not POC1A and
 * POC1B-DUSP6, which is what alphabetical order gives and what makes most gene boxes useless.
 * That ranking took two signals and a build step; script/build_gene_search.py carries the
 * reasoning and the measurements. Screens are matched on what people remember them by — cell line,
 * drug, phenotype, first author — with the punctuation BioGRID writes and nobody types ("K562"
 * against a stored "K-562") normalised away.
 */

type Mode = 'gene' | 'screen';
type Organism = 'human' | 'mouse';

interface GeneHit { symbol: string; name: string; matched: string | null; n_hits: number }
interface ScreenHit {
  screen_id: string; cell_line: string; condition: string;
  phenotype: string; author: string; n_hits: number;
}
type Hit = GeneHit | ScreenHit;

const isGene = (h: Hit): h is GeneHit => 'symbol' in h;

const CSS = `
.rxhome{
  ${EDITORIAL_TOKENS}
  min-height:100vh; background:${PAPER_GROUND};
  color:var(--ink); font-family:var(--sans); line-height:1.5;
  display:flex; flex-direction:column;
}
.rxhome *{box-sizing:border-box}
.rxhome .stage{
  flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center;
  padding:24px clamp(20px,5vw,48px) 96px; gap:26px;
}
.rxhome .mark{
  font-family:var(--serif); font-weight:500; font-size:clamp(34px,5vw,46px); letter-spacing:-.02em;
  margin:0; color:var(--ink);
}
.rxhome .mark b{color:var(--know); font-weight:600}
.rxhome .mark span{
  font-family:var(--mono); font-size:10px; letter-spacing:.18em; text-transform:uppercase;
  color:var(--faint); margin-left:11px; vertical-align:9px;
}

/* ── the box ─────────────────────────────────────────────────────────── */
.rxhome .boxwrap{position:relative; width:100%; max-width:660px}
.rxhome .box{
  display:flex; align-items:center; gap:8px; padding:7px 7px 7px 8px;
  border:1px solid var(--line); border-radius:16px; background:var(--card);
  box-shadow:0 1px 2px #14161A08, 0 10px 34px -20px #14161A29;
  transition:border-color .18s, box-shadow .18s;
}
.rxhome .boxwrap.open .box{border-radius:16px 16px 0 0}
.rxhome .box:focus-within{border-color:var(--know); box-shadow:0 0 0 4px var(--know-soft)}
.rxhome .plus{
  flex:0 0 auto; width:34px; height:34px; border-radius:10px; border:1px solid transparent;
  background:transparent; color:var(--muted); font-size:19px; line-height:1; cursor:pointer;
  transition:.15s;
}
.rxhome .plus:hover{background:var(--line2); color:var(--ink); border-color:var(--line)}
.rxhome .box input{
  flex:1; min-width:0; border:0; outline:0; background:transparent; color:var(--ink);
  font-family:var(--mono); font-size:15.5px; letter-spacing:.015em; padding:10px 4px;
}
.rxhome .box input::placeholder{font-family:var(--sans); letter-spacing:0; color:var(--faint)}
.rxhome .chip{
  flex:0 0 auto; display:flex; align-items:center; gap:6px; cursor:pointer;
  border:1px solid var(--line); border-radius:11px; background:var(--paper);
  font-family:var(--sans); font-size:12.5px; color:var(--ink2); padding:7px 11px; transition:.15s;
}
.rxhome .chip:hover{border-color:var(--know); color:var(--know)}
.rxhome .chip i{font-style:normal; font-size:9px; color:var(--faint)}
.rxhome .send{
  flex:0 0 auto; width:36px; height:36px; border:0; border-radius:11px; cursor:pointer;
  background:var(--ink); color:#fff; font-size:15px; transition:background .16s;
}
.rxhome .send:hover{background:var(--know)}
.rxhome .send:disabled{background:var(--line); color:var(--faint); cursor:default}

/* ── the mode menu ───────────────────────────────────────────────────── */
.rxhome .menu{
  position:absolute; right:52px; top:calc(100% + 6px); z-index:20; min-width:210px;
  background:var(--card); border:1px solid var(--line); border-radius:13px; padding:5px;
  box-shadow:0 16px 42px -18px #14161A3d;
}
.rxhome .menu button{
  display:block; width:100%; text-align:left; border:0; background:none; cursor:pointer;
  border-radius:9px; padding:9px 11px; font-family:var(--sans); font-size:13px; color:var(--ink);
}
.rxhome .menu button:hover{background:var(--line2)}
.rxhome .menu button.on{background:var(--know-soft); color:var(--know); font-weight:500}
.rxhome .menu button small{display:block; color:var(--muted); font-size:11.5px; font-weight:400; margin-top:2px}
.rxhome .menu button.on small{color:var(--know); opacity:.75}

/* ── suggestions ─────────────────────────────────────────────────────── */
.rxhome .drop{
  position:absolute; left:0; right:0; top:100%; z-index:15;
  background:var(--card); border:1px solid var(--know); border-top:0;
  border-radius:0 0 16px 16px; overflow:hidden;
  box-shadow:0 18px 44px -22px #14161A3d;
}
.rxhome .drop .row{
  display:flex; align-items:baseline; gap:10px; width:100%; text-align:left;
  border:0; background:none; cursor:pointer; padding:10px 15px; font-family:inherit;
  border-top:1px solid var(--line2);
}
.rxhome .drop .row:first-child{border-top:0}
.rxhome .drop .row.sel{background:var(--know-soft)}
.rxhome .drop .row b{
  font-family:var(--mono); font-size:13.5px; font-weight:500; color:var(--ink); flex:0 0 auto;
}
.rxhome .drop .row .why{font-family:var(--mono); font-size:10px; color:var(--eviq); flex:0 0 auto}
.rxhome .drop .row span{
  font-size:12px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.rxhome .drop .row em{
  font-style:normal; font-family:var(--mono); font-size:10.5px; color:var(--faint);
  margin-left:auto; flex:0 0 auto; padding-left:10px;
}
.rxhome .hint{
  font-size:12.5px; color:var(--muted); text-align:center; margin:0;
}
.rxhome .hint button{
  border:0; background:none; padding:0; cursor:pointer; color:var(--know); font:inherit;
  text-decoration:underline; text-underline-offset:3px;
}
.rxhome .hint button:hover{color:var(--ink)}
.rxhome .orgs{display:flex; gap:7px; justify-content:center}
.rxhome .orgs button{
  font-family:var(--sans); font-size:12px; padding:4px 12px; border-radius:16px;
  border:1px solid var(--line); background:var(--card); color:var(--muted); cursor:pointer; transition:.15s;
}
.rxhome .orgs button.on{background:var(--ink); border-color:var(--ink); color:#fff; font-weight:500}
.rxhome .foot{
  flex:0 0 auto; padding:14px clamp(20px,5vw,48px); text-align:center;
  font-family:var(--mono); font-size:10px; letter-spacing:.05em; color:var(--faint);
}
.rxhome .foot button{
  border:0; background:none; padding:0; cursor:pointer; font:inherit; color:var(--faint);
  text-decoration:underline; text-underline-offset:3px;
}
.rxhome .foot button:hover{color:var(--know)}
@media(max-width:560px){
  .rxhome .chip span{display:none}
  .rxhome .menu{right:8px; left:8px}
}
@media(prefers-reduced-motion:reduce){.rxhome *{transition:none!important}}
`;

const MODES: { key: Mode; label: string; blurb: string; placeholder: string }[] = [
  { key: 'gene', label: 'Gene', blurb: 'Everything on record, plus what the screens say',
    placeholder: 'Search a gene — try PO' },
  { key: 'screen', label: 'Screen', blurb: 'Find a screen by cell line, drug or author',
    placeholder: 'Search a screen — cell line, drug, author or id' },
];

export default function HomeLanding_aaron({
  onOpenGene,
  onOpenScreen,
  onStart,
  onExplore,
}: {
  onOpenGene: (gene: string, organism: Organism) => void;
  onOpenScreen: (screenId: string) => void;
  onStart: () => void;
  /** The Explorer has no card and no mode — stripping the page to one box left it with nowhere to
   *  be. It keeps a footer link rather than being dropped: it is a working page someone else owns,
   *  and quietly making it unreachable is not the same decision as retiring it. */
  onExplore: () => void;
}) {
  const [mode, setMode] = useState<Mode>('gene');
  const [organism, setOrganism] = useState<Organism>('human');
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [sel, setSel] = useState(0);
  const [menu, setMenu] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  ensureEditorialFonts();

  const meta = MODES.find((m) => m.key === mode)!;

  /* Every keystroke stamps its request. Suggestions come back out of order often enough on a slow
     link that without this the list can settle on the answer to a prefix the user has already
     typed past. */
  const reqRef = useRef(0);
  useEffect(() => {
    const term = q.trim();
    if (!term) { setHits([]); return; }
    const req = ++reqRef.current;
    const t = setTimeout(() => {
      const path = mode === 'gene' ? 'gene_suggest' : 'screen_suggest';
      fetch(`${API_BASE_URL}/api/${path}?q=${encodeURIComponent(term)}&organism=${organism}&limit=8`)
        .then((r) => r.json())
        .then((d) => { if (req === reqRef.current) { setHits(d.items || []); setSel(0); } })
        .catch(() => { if (req === reqRef.current) setHits([]); });
    }, 120);
    return () => clearTimeout(t);
  }, [q, mode, organism]);

  // Close the mode menu on an outside click. The suggestion list is left alone — it closes when
  // the query empties or something is chosen, which is what a person expects from a search box.
  useEffect(() => {
    if (!menu) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [menu]);

  const choose = useCallback((h: Hit) => {
    setHits([]);
    if (isGene(h)) { setQ(h.symbol); onOpenGene(h.symbol, organism); }
    else { setQ(h.screen_id); onOpenScreen(h.screen_id); }
  }, [organism, onOpenGene, onOpenScreen]);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    // Enter with the list open takes the highlighted row; otherwise it takes the box verbatim, so
    // someone who knows the exact symbol never has to wait for a suggestion to catch up.
    if (hits.length && hits[sel]) return choose(hits[sel]);
    const term = q.trim();
    if (!term) return;
    if (mode === 'gene') onOpenGene(term, organism);
    else onOpenScreen(term.replace(/\D/g, ''));
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!hits.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => (s + 1) % hits.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => (s - 1 + hits.length) % hits.length); }
    else if (e.key === 'Escape') { setHits([]); }
  };

  return (
    <div className="rxhome">
      <style>{CSS}</style>

      <div className="stage">
        <h1 className="mark">RETI<b>C</b>LE<span>beta</span></h1>

        <div className={`boxwrap${hits.length ? ' open' : ''}`} ref={wrapRef}>
          <form className="box" onSubmit={submit}>
            <button
              type="button"
              className="plus"
              onClick={onStart}
              title="Analyse a ranked gene list from your own screen"
              aria-label="Analyse a ranked gene list"
            >+</button>

            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={onKey}
              placeholder={meta.placeholder}
              aria-label={meta.placeholder}
              autoComplete="off"
              spellCheck={false}
              autoFocus
            />

            <button
              type="button"
              className="chip"
              onClick={() => setMenu((v) => !v)}
              aria-haspopup="menu"
              aria-expanded={menu}
            >
              <span>{meta.label}</span><i>▾</i>
            </button>

            <button className="send" type="submit" disabled={!q.trim()} aria-label="Search">→</button>
          </form>

          {menu && (
            <div className="menu" role="menu">
              {MODES.map((m) => (
                <button
                  key={m.key}
                  role="menuitem"
                  className={m.key === mode ? 'on' : ''}
                  onClick={() => { setMode(m.key); setMenu(false); setHits([]); inputRef.current?.focus(); }}
                >
                  {m.label}
                  <small>{m.blurb}</small>
                </button>
              ))}
            </div>
          )}

          {!!hits.length && (
            <div className="drop" role="listbox">
              {hits.map((h, i) => (
                <button
                  key={isGene(h) ? h.symbol : h.screen_id}
                  role="option"
                  aria-selected={i === sel}
                  className={`row${i === sel ? ' sel' : ''}`}
                  onMouseEnter={() => setSel(i)}
                  onClick={() => choose(h)}
                >
                  {isGene(h) ? (
                    <>
                      <b>{h.symbol}</b>
                      {/* Say WHY a row is here when the reason is not the text they typed. */}
                      {h.matched && <span className="why">via {h.matched}</span>}
                      <span>{h.name}</span>
                      {h.n_hits > 0 && <em>{h.n_hits.toLocaleString()} screens</em>}
                    </>
                  ) : (
                    <>
                      <b>{h.screen_id}</b>
                      <span>
                        {[h.cell_line, h.condition || h.phenotype, h.author]
                          .filter(Boolean).join(' · ')}
                      </span>
                      {h.n_hits > 0 && <em>{Number(h.n_hits).toLocaleString()} hits</em>}
                    </>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Shown in BOTH modes. Screens are species-specific too — 1,952 human against 205 mouse —
            and both suggesters filter on it, so hiding the control in screen mode meant someone who
            had picked Mouse kept searching mouse screens with nothing on screen saying so. */}
        <div className="orgs">
          {(['human', 'mouse'] as const).map((o) => (
            <button
              key={o}
              className={o === organism ? 'on' : ''}
              onClick={() => setOrganism(o)}
              aria-pressed={o === organism}
            >{o === 'human' ? 'Human' : 'Mouse'}</button>
          ))}
        </div>

        <p className="hint">
          or <button onClick={onStart}>bring a ranked gene list from your own screen →</button>
        </p>
      </div>

      <div className="foot">
        2,157 harmonized CRISPR screens · pure BioGRID ORCS — no literature mining ·{' '}
        <button onClick={onExplore}>Explorer</button>
      </div>
    </div>
  );
}
