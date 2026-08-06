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
  --ease:cubic-bezier(.22,.68,.28,1);
  position:relative;
  min-height:100vh; background:${PAPER_GROUND};
  color:var(--ink); font-family:var(--sans); line-height:1.5;
  display:flex; flex-direction:column;
}
.rxhome *{box-sizing:border-box}

/* ── the corpus ──────────────────────────────────────────────────────────
   The paper ground is a 22px lattice of grey dots. These two layers light a
   sparse few of those same nodes -- every offset is 1+22k, so a lit dot lands
   exactly on an existing one and reads as "some of these are on", not as a
   second pattern laid over the first.

   It is the only ambient element on the page and it is not decoration: teal is
   essential and ochre is KO-advantageous, the same two readings these accents
   carry everywhere else in the product, so what sits under the search box is
   the corpus it searches. They breathe on 19s and 23s -- coprime, so the pair
   never settles into a loop you can catch -- and they do not translate. Drift
   would read as wallpaper; a slow swell reads as phosphor, which is the right
   register for an instrument sitting idle.

   Sparsity is the whole point and was tuned by eye: a denser first pass read as
   polka dots, which is decoration, which is the one thing this page must not
   grow. Two dots per tile on tiles of 22x23 and 22x29 puts roughly a dozen lit
   nodes on a laptop screen and keeps the tile repeat below noticing. The lit
   dots are 1.3px against the ground's 1px so they read as the same dot turned
   up, not as a second, larger dot laid over it. */
.rxhome::before,
.rxhome::after{
  content:''; position:absolute; inset:0; pointer-events:none; z-index:0;
}
.rxhome::before{
  background:
    radial-gradient(circle at 89px 331px,  var(--know) 1.3px, transparent 1.8px),
    radial-gradient(circle at 375px 133px, var(--know) 1.3px, transparent 1.8px);
  background-size:506px 506px;            /* 22 × 23 */
  animation:corpus-ess 19s ease-in-out infinite;
}
.rxhome::after{
  background:
    radial-gradient(circle at 199px 67px,  var(--eviq) 1.3px, transparent 1.8px),
    radial-gradient(circle at 463px 441px, var(--eviq) 1.3px, transparent 1.8px);
  background-size:638px 638px;            /* 22 × 29 — coprime with the layer above */
  animation:corpus-adv 23s ease-in-out infinite;
}
@keyframes corpus-ess{0%,100%{opacity:.14}50%{opacity:.40}}
@keyframes corpus-adv{0%,100%{opacity:.12}50%{opacity:.34}}

/* Arrival, in reading order. Same rise/--ease the public page uses, on purpose:
   editorialTheme exists so the login boundary is not a change of identity, and
   that has to include how a page comes in, not only what it is made of. */
.rxhome .rise{opacity:0; transform:translateY(10px)}
.rxhome.anim .rise{animation:rise .8s var(--ease) forwards}
@keyframes rise{to{opacity:1; transform:none}}
.rxhome.anim .r1{animation-delay:.04s}
.rxhome.anim .r2{animation-delay:.13s}
.rxhome.anim .r3{animation-delay:.22s}
.rxhome.anim .r4{animation-delay:.30s}

@media (prefers-reduced-motion:reduce){
  .rxhome::before{animation:none; opacity:.28}
  .rxhome::after{animation:none; opacity:.22}
  .rxhome .rise,
  .rxhome.anim .rise{opacity:1; transform:none; animation:none}
}
/* The gap is the SUBORDINATE step, not the only one. Everything here used to sit 26px apart, which
   made five equal items out of a page that has two: a search (its scope pill and its box are one
   thing) and, under a real break, the other half of the product. Spacing is the only thing telling
   a reader which of those they are looking at, so the group break is set on the elements that start
   a group rather than shared out evenly down the column. */
.rxhome .stage{
  position:relative; z-index:1;
  flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center;
  padding:24px clamp(20px,5vw,48px) 96px; gap:12px;
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
/* z-index is explicit because the suggestion list has to cover the toggle, the hint and the
   handoff card below it. It used to get that for free -- boxwrap is positioned and they were not,
   so it painted later -- but the arrival animation gives them an opacity of their own, and an
   element with opacity paints in the same layer as a positioned one. Being later in the document,
   they started landing on top of the list. Stating the order stops that from depending on whether
   a sibling happens to be animated. */
.rxhome .boxwrap{position:relative; z-index:3; width:100%; max-width:660px; margin-top:18px}
.rxhome .box{
  display:flex; align-items:center; gap:8px; padding:7px 7px 7px 8px;
  border:1px solid var(--line); border-radius:16px; background:var(--card);
  box-shadow:0 1px 2px #14161A08, 0 10px 34px -20px #14161A29;
  transition:border-color .18s, box-shadow .18s;
}
.rxhome .boxwrap.open .box{border-radius:16px 16px 0 0}
.rxhome .drop.down{border-color:var(--eviq)}
.rxhome .drop .nolist{
  display:block; padding:11px 15px; font-size:12.5px; color:var(--eviq); line-height:1.55; cursor:default;
}
.rxhome .drop .nolist b{font-family:var(--mono); font-size:11.5px}
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
/* 660 to match the search box exactly. At 620 it sat 20px inside the box's edges — close enough to
   look like a mistake rather than a distinction, and these two are peers, not parent and child. */
.rxhome .handoff{
  width:100%; max-width:660px; margin:34px auto 0; display:flex; align-items:center; gap:20px;
  padding:16px 18px; border:1px solid var(--line); border-left:2px solid var(--eviq);
  border-radius:12px; background:var(--card); text-align:left;
}
.handoff-copy{flex:1 1 auto; min-width:0}
.handoff-k{
  font-family:var(--mono); font-size:9.5px; letter-spacing:.15em; text-transform:uppercase;
  color:var(--eviq); margin-bottom:4px;
}
.handoff-copy p{margin:0; font-size:13px; line-height:1.5; color:var(--ink2)}
.handoff-go{
  flex:0 0 auto; font-family:var(--sans); font-size:13px; font-weight:500;
  padding:9px 15px; border-radius:9px; border:1px solid var(--eviq);
  background:var(--card); color:var(--eviq); cursor:pointer; white-space:nowrap; transition:.15s;
}
.handoff-go b{font-weight:600; font-variant-numeric:tabular-nums}
.handoff-go:hover{background:var(--eviq); color:#fff}
.handoff-go:focus-visible{outline:2px solid var(--eviq); outline-offset:2px}
@media (max-width:620px){
  .handoff{flex-direction:column; align-items:stretch; gap:13px}
  .handoff-go{width:100%}
}
.rxhome .orgs{display:flex; gap:7px; justify-content:center}
.rxhome .orgs button{
  font-family:var(--sans); font-size:12px; padding:4px 12px; border-radius:16px;
  border:1px solid var(--line); background:var(--card); color:var(--muted); cursor:pointer; transition:.15s;
}
.rxhome .orgs button.on{background:var(--ink); border-color:var(--ink); color:#fff; font-weight:500}
.rxhome .scope-note{
  font-family:var(--mono); font-size:11px; color:var(--muted); padding:5px 12px;
  border:1px solid var(--line); border-radius:16px; background:var(--card);
}
.rxhome .foot{
  position:relative; z-index:1;
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
  { key: 'screen', label: 'Screen', blurb: 'Compare a supported human screen',
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
  /* The size of the comparison corpus, read from the endpoint the comparison page itself uses, so
     the button on this page and the counter on that one can never disagree. Stays null if the call
     fails and the button falls back to copy that needs no number — a home page must not depend on
     an API being awake. */
  const [corpus, setCorpus] = useState<number | null>(null);
  /* The arrival runs once, on the first frame after mount, so the page is painted in its start
     state before anything moves. Set in an effect rather than at render because a class applied in
     the same commit that creates the elements gives the browser no start state to animate from. */
  const [arrived, setArrived] = useState(false);

  ensureEditorialFonts();

  const meta = MODES.find((m) => m.key === mode)!;

  /* Every keystroke stamps its request. Suggestions come back out of order often enough on a slow
     link that without this the list can settle on the answer to a prefix the user has already
     typed past. */
  const reqRef = useRef(0);
  const [down, setDown] = useState(false);
  useEffect(() => {
    const term = q.trim();
    if (!term) { setHits([]); setDown(false); return; }
    const req = ++reqRef.current;
    const t = setTimeout(() => {
      const path = mode === 'gene' ? 'gene_suggest' : 'screen_suggest';
      fetch(`${API_BASE_URL}/api/${path}?q=${encodeURIComponent(term)}&organism=${organism}&limit=8`)
        .then((r) => r.json())
        .then((d) => {
          if (req !== reqRef.current) return;
          setHits(d.items || []);
          setSel(0);
          // `ok: false` means the index could not be read. Saying nothing there would tell the
          // user their gene does not exist, which is a different and much worse claim.
          setDown(d.ok === false);
        })
        .catch(() => { if (req === reqRef.current) { setHits([]); setDown(true); } });
    }, 120);
    return () => clearTimeout(t);
  }, [q, mode, organism]);

  useEffect(() => {
    const id = requestAnimationFrame(() => setArrived(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    let live = true;
    fetch(`${API_BASE_URL}/api/corpus/count`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (live && d && typeof d.count === 'number') setCorpus(d.count); })
      .catch(() => { /* leave it null; the button reads fine without a number */ });
    return () => { live = false; };
  }, []);

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
    <div className={`rxhome${arrived ? ' anim' : ''}`}>
      <style>{CSS}</style>

      <div className="stage">
        <h1 className="mark rise r1">RETI<b>C</b>LE<span>beta</span></h1>

        <div className={`boxwrap rise r2${hits.length || down ? ' open' : ''}`} ref={wrapRef}>
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
                  onClick={() => {
                    setMode(m.key);
                    if (m.key === 'screen') setOrganism('human');
                    setMenu(false);
                    setHits([]);
                    inputRef.current?.focus();
                  }}
                >
                  {m.label}
                  <small>{m.blurb}</small>
                </button>
              ))}
            </div>
          )}

          {down && !hits.length && (
            <div className="drop down" role="status">
              <div className="row nolist">
                Suggestions are unavailable right now — the search index could not be read.
                Press <b>Enter</b> to open the {mode === 'gene' ? 'gene' : 'screen'} anyway.
              </div>
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

        {/* Screen similarity is currently precomputed for a 962-screen human pool. Keep that
            limitation visible and do not offer a mouse switch that can only lead to a 404. */}
        <div className="orgs rise r3">
          {mode === 'gene' ? (
            (['human', 'mouse'] as const).map((o) => (
              <button
                key={o}
                className={o === organism ? 'on' : ''}
                onClick={() => setOrganism(o)}
                aria-pressed={o === organism}
              >{o === 'human' ? 'Human' : 'Mouse'}</button>
            ))
          ) : (
            <span className="scope-note">Human comparison pool · 962 supported screens</span>
          )}
        </div>

      {/* The product has two halves and this page used to present only one. Looking a gene up and
          comparing your own screen are peers, so the second one gets a real affordance rather than
          an underlined word in a caption.
          Ochre, not teal: in this palette teal is what is already established and ochre is what the
          screens measured — which is exactly what lies on the other side of this button.
          The count is fetched live from the same endpoint the comparison page uses, so the button
          states its own value and is never stale.

          A caption used to sit between the toggle and this card, reading "Type a symbol to look one
          up, or hand over a whole screen below." It is gone rather than shortened: the first half
          restated the placeholder, and the second narrated this card, which carries its own label
          and its own sentence. It also blurred the one distinction on this page worth keeping
          sharp — searching a PUBLISHED screen is the mode chip, handing over YOUR OWN is this card,
          and "a whole screen below" sat between the two meaning neither cleanly. */}
      <div className="handoff rise r4">
        <div className="handoff-copy">
          <div className="handoff-k">your own screen</div>
          <p>Already ran one? Land it against everything published and see which screens agree.</p>
        </div>
        <button className="handoff-go" onClick={onStart}>
          {corpus == null
            ? 'Compare my screen'
            : <>Compare against <b>{corpus.toLocaleString()}</b> screens</>} <span aria-hidden="true">→</span>
        </button>
      </div>

      </div>

      <div className="foot">
        2,157 harmonized CRISPR screens · pure BioGRID ORCS — no literature mining ·{' '}
        <button onClick={onExplore}>Explorer</button>
      </div>
    </div>
  );
}
