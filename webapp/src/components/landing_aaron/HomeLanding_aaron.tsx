import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../../config/env';
import {
  ensureEditorialFonts,
  EDITORIAL_TOKENS,
  PAPER_GROUND,
} from './editorialTheme_aaron';

/**
 * The signed-in home: two doors, split down the middle.
 *
 * WHAT IT REPLACED. First a marketing-shaped page — headline, buttons, four round numbers — aimed
 * at someone who had already signed in. Then a version with a statistics rule and four destination
 * cards. Then one search box with a mode chip, which was right about the important thing (the page
 * is the box) and wrong about one: it made the user tell the box what kind of thing they were
 * holding, when the box could just as easily be two boxes and read that from where they typed.
 *
 * THE SPLIT IS THE PRODUCT, NOT A LAYOUT. This tool has exactly two halves, and the palette has
 * said so since editorialTheme was written: teal is what is already established, ochre is what the
 * screens measured. So the left side is a gene — what ten sources already know about it — and the
 * right side is a screen, published or your own. A seam down the centre is the honest picture of a
 * product with two entrances, and it fills a page that was two thirds empty without inventing
 * anything to put there.
 *
 * The mode chip is gone as a consequence. It existed to disambiguate one box; two boxes each know
 * what they are. The organism toggle stays on the gene side only, because the screen comparison
 * pool is human-only and a mouse switch over it would offer something that cannot be delivered.
 *
 * THE TYPE-AHEAD IS STILL THE POINT. Typing "PO" answers POLR2A, POLR2B, POLR2E, POLD1 — not
 * POC1A and POC1B-DUSP6, which is what alphabetical order gives and what makes most gene boxes
 * useless. script/build_gene_search.py carries the reasoning and the measurements. Screens are
 * matched on what people remember them by — cell line, drug, phenotype, first author — with the
 * punctuation BioGRID writes and nobody types ("K562" against a stored "K-562") normalised away.
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
  position:relative; min-height:100vh; background:${PAPER_GROUND};
  color:var(--ink); font-family:var(--sans); line-height:1.5;
  display:flex; flex-direction:column;
}
.rxhome *{box-sizing:border-box}

/* ── the mark, sitting on the seam ───────────────────────────────────── */
.rxhome .cap{
  position:relative; z-index:2; flex:0 0 auto;
  padding:clamp(26px,4.4vh,52px) 0 clamp(18px,3vh,34px); text-align:center;
}
.rxhome .mark{
  font-family:var(--serif); font-weight:500; font-size:clamp(30px,4.2vw,44px); letter-spacing:-.02em;
  margin:0; color:var(--ink);
}
.rxhome .mark b{color:var(--know); font-weight:600}
.rxhome .mark span{
  font-family:var(--mono); font-size:9.5px; letter-spacing:.18em; text-transform:uppercase;
  color:var(--faint); margin-left:10px; vertical-align:9px;
}

/* ── the split ───────────────────────────────────────────────────────────
   One rule down the centre and a quarter-degree of temperature either side —
   the halves have to read as two territories without either of them turning
   into a coloured panel, because everything that matters on this page is
   printed on them. */
.rxhome .split{
  position:relative; z-index:2; flex:1 1 auto;
  display:grid; grid-template-columns:1fr 1fr; align-items:stretch;
}
/* Centred, not top-aligned. The two sides carry different amounts — the screens
   side has a second door under it — so anchoring them to the top left a single
   dead band across the bottom of the page. Centring splits that space above and
   below, where it reads as margin instead of as something missing. */
.rxhome .half{
  position:relative; display:flex; flex-direction:column; justify-content:center;
  gap:15px; padding:clamp(20px,3.4vh,38px) clamp(26px,4.2vw,64px) clamp(26px,4vh,44px);
}
.rxhome .half.genes{border-right:1px solid var(--line)}
/* The tint is the paper warming and cooling, not a fill: at 3% the seam reads
   as a change of light rather than a change of surface. */
.rxhome .half.genes::before,
.rxhome .half.screens::before{content:''; position:absolute; inset:0; pointer-events:none; z-index:0}
.rxhome .half.genes::before{background:linear-gradient(90deg,#1F6F8B08,transparent 62%)}
.rxhome .half.screens::before{background:linear-gradient(270deg,#C77D3108,transparent 62%)}
.rxhome .half > *{position:relative; z-index:1}

/* A label, not a sentence, so it is set smaller than the headline it replaced and carries its
   side's accent as a rule beside it — the only thing left naming which half you are in. */
.rxhome .hh{
  font-family:var(--serif); font-weight:500; font-size:clamp(19px,2.1vw,26px); letter-spacing:-.01em;
  line-height:1.2; margin:0 0 4px; color:var(--ink);
  display:flex; align-items:center; gap:13px;
}
.rxhome .hh::before{content:''; flex:0 0 auto; width:26px; height:2px; border-radius:1px}
.rxhome .genes .hh::before{background:var(--know)}
.rxhome .screens .hh::before{background:var(--eviq)}

/* ── the box ─────────────────────────────────────────────────────────── */
.rxhome .boxwrap{position:relative; z-index:3; width:100%; max-width:none}
.rxhome .box{
  display:flex; align-items:center; gap:8px; padding:6px 6px 6px 14px;
  border:1px solid var(--line); border-radius:14px; background:var(--card);
  box-shadow:0 1px 2px #14161A08, 0 10px 34px -22px #14161A29;
  transition:border-color .18s, box-shadow .18s;
}
.rxhome .boxwrap.open .box{border-radius:14px 14px 0 0}
.rxhome .genes .box:focus-within{border-color:var(--know); box-shadow:0 0 0 4px var(--know-soft)}
.rxhome .screens .box:focus-within{border-color:var(--eviq); box-shadow:0 0 0 4px var(--eviq-soft)}
.rxhome .box input{
  flex:1; min-width:0; border:0; outline:0; background:transparent; color:var(--ink);
  font-family:var(--mono); font-size:15px; letter-spacing:.015em; padding:10px 0;
}
.rxhome .box input::placeholder{font-family:var(--sans); letter-spacing:0; color:var(--faint)}
.rxhome .send{
  flex:0 0 auto; width:34px; height:34px; border:0; border-radius:10px; cursor:pointer;
  background:var(--ink); color:#fff; font-size:14px; transition:background .16s;
}
.rxhome .genes .send:hover{background:var(--know)}
.rxhome .screens .send:hover{background:var(--eviq)}
.rxhome .send:disabled{background:var(--line); color:var(--faint); cursor:default}

/* ── suggestions ─────────────────────────────────────────────────────── */
.rxhome .drop{
  position:absolute; left:0; right:0; top:100%; z-index:15;
  background:var(--card); border:1px solid var(--know); border-top:0;
  border-radius:0 0 14px 14px; overflow:hidden;
  box-shadow:0 18px 44px -22px #14161A3d;
}
.rxhome .screens .drop{border-color:var(--eviq)}
.rxhome .drop.down{border-color:var(--eviq)}
.rxhome .drop .nolist{
  display:block; padding:11px 15px; font-size:12.5px; color:var(--eviq); line-height:1.55; cursor:default;
}
.rxhome .drop .nolist b{font-family:var(--mono); font-size:11.5px}
.rxhome .drop .row{
  display:flex; align-items:baseline; gap:10px; width:100%; text-align:left;
  border:0; background:none; cursor:pointer; padding:9px 14px; font-family:inherit;
  border-top:1px solid var(--line2);
}
.rxhome .drop .row:first-child{border-top:0}
.rxhome .genes .drop .row.sel{background:var(--know-soft)}
.rxhome .screens .drop .row.sel{background:var(--eviq-soft)}
.rxhome .drop .row b{
  font-family:var(--mono); font-size:13px; font-weight:500; color:var(--ink); flex:0 0 auto;
}
.rxhome .drop .row .why{font-family:var(--mono); font-size:10px; color:var(--eviq); flex:0 0 auto}
.rxhome .drop .row span{
  font-size:12px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.rxhome .drop .row em{
  font-style:normal; font-family:var(--mono); font-size:10.5px; color:var(--faint);
  margin-left:auto; flex:0 0 auto; padding-left:10px;
}

/* ── organism, gene side only ────────────────────────────────────────── */
/* The two sides each carry one control and one small line under it, so their titles land on the
   same baseline. On the right that line is not filler: it is what you need to know before you
   click, and not knowing it is the reason someone bounces off an upload screen. */
.rxhome .orgs{display:flex; gap:7px; min-height:28px; align-items:center}
.rxhome .brings{
  display:flex; align-items:center; min-height:28px;
  font-family:var(--mono); font-size:11.5px; color:var(--faint);
}
.rxhome .orgs button{
  font-family:var(--sans); font-size:12px; padding:4px 12px; border-radius:16px;
  border:1px solid var(--line); background:var(--card); color:var(--muted); cursor:pointer; transition:.15s;
}
.rxhome .orgs button.on{background:var(--ink); border-color:var(--ink); color:#fff; font-weight:500}

/* ── the second door on the screens side ─────────────────────────────── */
.rxhome .own{
  display:flex; align-items:center; justify-content:space-between; gap:16px; width:100%;
  padding:16px 18px; border-radius:14px; border:1px solid var(--eviq); background:var(--card);
  font-family:var(--sans); font-size:15px; font-weight:500; color:var(--eviq);
  cursor:pointer; text-align:left; transition:.15s;
  box-shadow:0 1px 2px #14161A08, 0 10px 34px -22px #14161A29;
}
.rxhome .own:hover{background:var(--eviq); color:#fff; border-color:var(--eviq)}
.rxhome .own:focus-visible{outline:2px solid var(--eviq); outline-offset:2px}
.rxhome .own b{font-variant-numeric:tabular-nums}

.rxhome .foot{
  position:relative; z-index:2; flex:0 0 auto; padding:12px clamp(20px,5vw,48px); text-align:center;
  font-family:var(--mono); font-size:10px; letter-spacing:.05em; color:var(--faint);
  border-top:1px solid var(--line2);
}
.rxhome .foot button{
  border:0; background:none; padding:0; cursor:pointer; font:inherit; color:var(--faint);
  text-decoration:underline; text-underline-offset:3px;
}
.rxhome .foot button:hover{color:var(--know)}

/* ── the corpus, now split by side ───────────────────────────────────────
   The lit nodes were always the two accents. Giving each half only its own
   colour turns an ambient texture into part of the argument: teal nodes lie
   under the gene, ochre under the screens. Offsets are 1+22k so every lit dot
   lands on an existing grey one, and the two breathe on coprime periods so the
   pair never settles into a loop you can catch. */
.rxhome .half::after{content:''; position:absolute; inset:0; pointer-events:none; z-index:0}
.rxhome .genes::after{
  background:
    radial-gradient(circle at 89px 331px,  var(--know) 1.3px, transparent 1.8px),
    radial-gradient(circle at 375px 133px, var(--know) 1.3px, transparent 1.8px);
  background-size:506px 506px;
  animation:corpus-ess 19s ease-in-out infinite;
}
.rxhome .screens::after{
  background:
    radial-gradient(circle at 199px 67px,  var(--eviq) 1.3px, transparent 1.8px),
    radial-gradient(circle at 463px 441px, var(--eviq) 1.3px, transparent 1.8px);
  background-size:638px 638px;
  animation:corpus-adv 23s ease-in-out infinite;
}
@keyframes corpus-ess{0%,100%{opacity:.14}50%{opacity:.40}}
@keyframes corpus-adv{0%,100%{opacity:.12}50%{opacity:.34}}

/* Arrival: the mark, then the two halves opening outward from the seam. */
.rxhome .rise{opacity:0; transform:translateY(10px)}
.rxhome .half.genes{opacity:0; transform:translateX(-14px)}
.rxhome .half.screens{opacity:0; transform:translateX(14px)}
.rxhome.anim .rise{animation:rise .8s var(--ease) forwards}
.rxhome.anim .half{animation:open .85s var(--ease) .12s forwards}
@keyframes rise{to{opacity:1; transform:none}}
@keyframes open{to{opacity:1; transform:none}}

@media (prefers-reduced-motion:reduce){
  .rxhome .genes::after{animation:none; opacity:.28}
  .rxhome .screens::after{animation:none; opacity:.22}
  .rxhome .rise,.rxhome.anim .rise,
  .rxhome .half,.rxhome.anim .half{opacity:1; transform:none; animation:none}
}

/* Below the fold for a split this narrow, so the seam becomes a horizontal one. */
@media (max-width:860px){
  .rxhome .split{grid-template-columns:1fr}
  .rxhome .half.genes{border-right:0; border-bottom:1px solid var(--line)}
  .rxhome .half.genes::before{background:linear-gradient(180deg,#1F6F8B08,transparent 62%)}
  .rxhome .half.screens::before{background:linear-gradient(0deg,#C77D3108,transparent 62%)}
}
@media (prefers-reduced-motion:reduce){.rxhome *{transition:none!important}}
`;

/** One side of the split. Each owns its query and its suggestions, which is the whole reason the
 *  mode chip could go: a box that only ever searches one index does not need to be told which. */
function Side({
  mode, organism, onPick, children,
}: {
  mode: Mode;
  organism: Organism;
  onPick: (term: string, hit: Hit | null) => void;
  children?: React.ReactNode;
}) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [sel, setSel] = useState(0);
  const [down, setDown] = useState(false);
  const reqRef = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

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

  const take = useCallback((h: Hit) => {
    setHits([]);
    setQ(isGene(h) ? h.symbol : h.screen_id);
    onPick(isGene(h) ? h.symbol : h.screen_id, h);
  }, [onPick]);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    // Enter with the list open takes the highlighted row; otherwise it takes the box verbatim, so
    // someone who knows the exact symbol never waits for a suggestion to catch up.
    if (hits.length && hits[sel]) return take(hits[sel]);
    const term = q.trim();
    if (term) onPick(term, null);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!hits.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => (s + 1) % hits.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => (s - 1 + hits.length) % hits.length); }
    else if (e.key === 'Escape') { setHits([]); }
  };

  return (
    <>
      <div className={`boxwrap${hits.length || down ? ' open' : ''}`}>
        <form className="box" onSubmit={submit}>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder={mode === 'gene' ? 'Search a gene — try PO' : 'Cell line, drug, phenotype, author'}
            aria-label={mode === 'gene' ? 'Search a gene' : 'Search a published screen'}
            autoComplete="off" spellCheck={false}
          />
          <button className="send" type="submit" disabled={!q.trim()} aria-label="Search">→</button>
        </form>

        {down && !hits.length && (
          <div className="drop down" role="status">
            <span className="nolist">
              Suggestions are unavailable right now — the search index could not be read.
              Press <b>Enter</b> to open the {mode === 'gene' ? 'gene' : 'screen'} anyway.
            </span>
          </div>
        )}

        {!!hits.length && (
          <div className="drop" role="listbox">
            {hits.map((h, i) => (
              <button
                key={isGene(h) ? h.symbol : h.screen_id}
                className={`row${i === sel ? ' sel' : ''}`}
                onMouseEnter={() => setSel(i)}
                onClick={() => take(h)}
                type="button"
              >
                {isGene(h) ? (
                  <>
                    <b>{h.symbol}</b>
                    {h.matched && <span className="why">via {h.matched}</span>}
                    <span>{h.name}</span>
                    {!!h.n_hits && <em>{h.n_hits.toLocaleString()} screens</em>}
                  </>
                ) : (
                  <>
                    <b>{h.cell_line || h.screen_id}</b>
                    <span>{[h.condition, h.phenotype, h.author].filter(Boolean).join(' · ')}</span>
                    {!!h.n_hits && <em>{h.n_hits.toLocaleString()} hits</em>}
                  </>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
      {children}
    </>
  );
}

export default function HomeLanding_aaron({
  onOpenGene,
  onStart,
  onExplore,
}: {
  onOpenGene: (gene: string, organism: Organism) => void;
  /** The third case: a ranked gene list from the user's own bench. */
  onStart: () => void;
  onExplore: () => void;
}) {
  const [organism, setOrganism] = useState<Organism>('human');
  /* The size of the comparison corpus, read from the endpoint the comparison page itself uses, so
     the button here and the counter there can never disagree. Stays null if the call fails and the
     button falls back to copy that needs no number — a home page must not depend on an API. */
  const [corpus, setCorpus] = useState<number | null>(null);
  /* The arrival runs once, on the first frame after mount, so the page is painted in its start
     state before anything moves. */
  const [arrived, setArrived] = useState(false);

  ensureEditorialFonts();

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

  const pickGene = useCallback((term: string) => onOpenGene(term, organism), [onOpenGene, organism]);
  return (
    <div className={`rxhome${arrived ? ' anim' : ''}`}>
      <style>{CSS}</style>

      <div className="cap">
        <h1 className="mark rise">RETI<b>C</b>LE<span>beta</span></h1>
      </div>

      <div className="split">
        <section className="half genes">
          <h2 className="hh">Single Gene Query</h2>
          <Side mode="gene" organism={organism} onPick={pickGene} />
          {/* The toggle stays. It is not decoration on a stripped-down side — without it half the
              corpus is unreachable, because a mouse symbol looked up against the human index
              returns nothing and says nothing about why. */}
          <div className="orgs">
            {(['human', 'mouse'] as Organism[]).map((o) => (
              <button
                key={o}
                type="button"
                className={o === organism ? 'on' : ''}
                onClick={() => setOrganism(o)}
                aria-pressed={o === organism}
              >{o === 'human' ? 'Human' : 'Mouse'}</button>
            ))}
          </div>
        </section>

        <section className="half screens">
          <h2 className="hh">Analyze your screening result</h2>
          {/* Ochre, not teal: in this palette teal is what is already established and ochre is what
              the screens measured, which is exactly what lies on the other side of this button. The
              count is read live from the same endpoint the comparison page counts from, so the two
              can never quote different numbers — and stays null if that call fails, because a home
              page must not go blank over an API. */}
          <button className="own" onClick={onStart} type="button">
            <span>
              {corpus == null
                ? 'Compare my screen'
                : <>Compare against <b>{corpus.toLocaleString()}</b> published screens</>}
            </span>
            <span aria-hidden="true">→</span>
          </button>
          <div className="brings">CSV, TSV, or a plain list of gene symbols</div>
        </section>
      </div>

      <div className="foot">
        2,157 harmonized CRISPR screens · pure BioGRID ORCS — no literature mining ·{' '}
        <button onClick={onExplore} type="button">Explorer</button>
      </div>
    </div>
  );
}
