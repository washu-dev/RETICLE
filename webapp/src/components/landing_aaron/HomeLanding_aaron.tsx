import { useState } from 'react';
import {
  ensureEditorialFonts,
  EDITORIAL_TOKENS,
  PAPER_GROUND,
} from './editorialTheme_aaron';

/**
 * The signed-in home.
 *
 * WHAT IT REPLACED AND WHY. The previous home led with a headline, a pair of buttons and a row of
 * round-number statistics — the shape a marketing page takes. But nobody reaching this screen needs
 * to be sold the product: they already signed in. They arrive holding one of exactly two things,
 * a gene symbol or a ranked list from their own screen, and the old page made both of them click
 * into a feature and search AGAIN once they got there.
 *
 * So the search box IS the hero. Type FANCD2, press return, land in the gene wiki. The gene wiki
 * therefore gets no card of its own — it is the primary action — and the four cards are the other
 * four places to be. That is also why there is no "Launch app" button: this IS the app.
 *
 * Every number on this page was counted, not estimated. Sources are named beside each one.
 */

/* Counted 2026-08-04 against the shipped corpus, not rounded for effect:
     2,157   distinct SCREEN_ID in harmonized_scores
    28.2M    rows in harmonized_scores (28,237,649)
   109,412   edges in net_edge, context 'all' (5,269 genes, 9,905 of them mutual-best)
     46.4%   CORUM same-complex precision of the top evidence tier, against a 0.615% baseline —
             script/exp_evidence_tiers.py */
const STATS = [
  { n: '2,157', k: 'CRISPR screens harmonized' },
  { n: '28.2M', k: 'gene–screen measurements' },
  { n: '109,412', k: 'co-essentiality edges' },
  { n: '46.4%', k: 'top-tier edges recover a known complex' },
];

type Dest = { key: string; tab?: 'screen' | 'network'; title: string; body: string; note: string; accent: string };

const DESTS: Dest[] = [
  {
    key: 'network',
    tab: 'network',
    title: 'Network',
    body:
      'A gene’s co-essential partners, every edge graded on two independent channels — profile ' +
      'correlation across all screens, and co-hit enrichment across only the screens where both ' +
      'genes were called hits. Then ask the network for a function the gene is not annotated with.',
    note: 'Top-tier edges recover a known CORUM complex 46.4% of the time · 0.6% for a random pair',
    accent: 'var(--know)',
  },
  {
    key: 'screens',
    tab: 'screen',
    title: 'Screens',
    body:
      'Start from one screen instead of one gene: find the screens whose hit sets most resemble ' +
      'it, with the overlap and the study behind each one.',
    note: '1,952 screens with curated cell line, modality and condition',
    accent: 'var(--eviq)',
  },
  {
    key: 'upload',
    title: 'Analyse a gene list',
    body:
      'Bring a ranked list from your own screen. It is cross-referenced against the whole corpus ' +
      'to separate what is already known from what nobody has looked at yet.',
    note: 'Directionality-aware · dark-matter prioritised',
    accent: 'var(--pred)',
  },
  {
    key: 'explorer',
    title: 'Explorer',
    body:
      'The interactive single-gene view: perturbation footprint, context breakdown and an inline ' +
      'association graph you can pull on.',
    note: 'Companion to the gene wiki',
    // ink, not muted: a grey marker beside three coloured ones reads as "disabled", and this is a
    // working page. It is neutral because it carries no evidence class, not because it is lesser.
    accent: 'var(--ink2)',
  },
];

const CSS = `
.rxhome{
  ${EDITORIAL_TOKENS}
  min-height:100vh; background:${PAPER_GROUND};
  color:var(--ink); font-family:var(--sans); line-height:1.5;
}
.rxhome *{box-sizing:border-box}
.rxhome .bar{
  display:flex; align-items:center; gap:14px; padding:14px clamp(20px,4vw,44px);
  border-bottom:1px solid var(--line); background:#FFFFFFcc; backdrop-filter:blur(8px);
  position:sticky; top:0; z-index:5;
}
.rxhome .mark{font-family:var(--serif); font-weight:500; font-size:21px; letter-spacing:-.01em}
.rxhome .mark b{color:var(--know); font-weight:600}
.rxhome .beta{
  font-family:var(--mono); font-size:9.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--faint); margin-left:8px; vertical-align:3px;
}
.rxhome .grow{flex:1}
.rxhome .ghost{
  font-family:var(--sans); font-size:12.5px; color:var(--muted); background:transparent;
  border:1px solid var(--line); border-radius:9px; padding:7px 13px; cursor:pointer; transition:.16s;
}
.rxhome .ghost:hover{border-color:var(--know); color:var(--know)}

.rxhome .wrap{max-width:1080px; margin:0 auto; padding:0 clamp(20px,4vw,44px)}

/* ── hero ─────────────────────────────────────────────────────────────── */
.rxhome .hero{padding:clamp(56px,8vw,96px) 0 clamp(30px,4vw,44px)}
/* 19ch, not 15: at 15 the line broke as "Two thousand / screens, one gene at a / time." and left
   "time." alone on its own line. Two lines, no orphan. */
.rxhome h1{
  font-family:var(--serif); font-weight:400; letter-spacing:-.022em; line-height:1.06;
  font-size:clamp(34px,5.4vw,58px); margin:0 0 16px; max-width:19ch;
}
.rxhome h1 em{font-style:normal; color:var(--know)}
.rxhome .sub{font-size:15px; color:var(--ink2); max-width:56ch; margin:0 0 30px; line-height:1.62}

/* the search IS the hero — an instrument field, not a marketing input */
.rxhome form{
  display:flex; align-items:center; gap:10px; max-width:560px;
  border:1px solid var(--line); border-radius:14px; background:var(--card); padding:5px 5px 5px 16px;
  transition:border-color .18s, box-shadow .18s;
}
.rxhome form:focus-within{border-color:var(--know); box-shadow:0 0 0 4px var(--know-soft)}
.rxhome form input{
  flex:1; min-width:0; border:0; outline:0; background:transparent; color:var(--ink);
  font-family:var(--mono); font-size:16px; letter-spacing:.02em; padding:12px 0;
}
.rxhome form input::placeholder{font-family:var(--sans); letter-spacing:0; color:var(--faint)}
.rxhome form button{
  flex:0 0 auto; border:0; border-radius:10px; background:var(--ink); color:#fff;
  font-family:var(--sans); font-size:13.5px; font-weight:500; padding:11px 18px; cursor:pointer;
  transition:background .16s;
}
.rxhome form button:hover{background:var(--know)}
.rxhome .org{display:flex; align-items:center; gap:7px; margin:13px 0 0}
.rxhome .org button{
  font-family:var(--sans); font-size:12px; padding:4px 12px; border-radius:16px;
  border:1px solid var(--line); background:var(--card); color:var(--muted); cursor:pointer; transition:.15s;
}
.rxhome .org button.on{background:var(--ink); border-color:var(--ink); color:#fff; font-weight:500}
.rxhome .alt{font-size:13.5px; color:var(--muted); margin:24px 0 0}
.rxhome .alt button{
  border:0; background:none; padding:0; cursor:pointer; color:var(--know);
  font-family:inherit; font-size:inherit; text-decoration:underline; text-underline-offset:3px;
}
.rxhome .alt button:hover{color:var(--ink)}

/* ── the counted rule ─────────────────────────────────────────────────── */
.rxhome .stats{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  border-top:1px solid var(--line); border-bottom:1px solid var(--line); margin-top:clamp(34px,5vw,56px);
}
.rxhome .stat{padding:22px 0 20px; border-left:1px solid var(--line2)}
.rxhome .stat:first-child{border-left:0}
.rxhome .stat:not(:first-child){padding-left:22px}
.rxhome .stat b{
  display:block; font-family:var(--mono); font-size:23px; font-weight:500; color:var(--ink);
  letter-spacing:-.01em;
}
.rxhome .stat span{display:block; font-size:11.5px; color:var(--muted); margin-top:5px; line-height:1.45}

/* ── destinations ─────────────────────────────────────────────────────── */
.rxhome .eyebrow{
  font-family:var(--mono); font-size:10px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--faint); margin:clamp(48px,6vw,72px) 0 18px;
}
/* 380px min, so four cards land as 2x2 rather than 3+1 — a lone card on its own row reads as an
   afterthought, and the extra width gives each description a sane measure instead of five words
   per line. */
.rxhome .grid{
  display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(380px,1fr));
  padding-bottom:clamp(56px,8vw,96px);
}
.rxhome .dest{
  text-align:left; background:var(--card); border:1px solid var(--line); border-radius:15px;
  padding:22px 22px 20px; cursor:pointer; font-family:inherit;
  display:flex; flex-direction:column; gap:9px;
  transition:border-color .18s, transform .18s, box-shadow .18s;
}
.rxhome .dest:hover{
  border-color:var(--know); transform:translateY(-2px);
  box-shadow:0 10px 30px -16px #14161A2e;
}
.rxhome .dest:focus-visible{outline:2px solid var(--ink); outline-offset:3px}
.rxhome .dest h3{
  font-family:var(--serif); font-weight:500; font-size:19px; margin:0; letter-spacing:-.01em;
  display:flex; align-items:center; gap:9px;
}
.rxhome .dest h3 i{
  width:7px; height:7px; border-radius:2px; flex:0 0 auto; font-style:normal; margin-top:1px;
}
.rxhome .dest h3 span{margin-left:auto; color:var(--faint); font-family:var(--sans); font-size:15px;
  transition:transform .18s, color .18s}
.rxhome .dest:hover h3 span{transform:translateX(3px); color:var(--know)}
.rxhome .dest p{font-size:13px; color:var(--ink2); line-height:1.6; margin:0}
.rxhome .dest .note{
  font-family:var(--mono); font-size:10.5px; color:var(--muted); line-height:1.5;
  margin-top:auto; padding-top:11px; border-top:1px solid var(--line2);
}
.rxhome .foot{
  border-top:1px solid var(--line); padding:16px clamp(20px,4vw,44px);
  font-family:var(--mono); font-size:10.5px; letter-spacing:.04em; color:var(--faint);
  background:var(--card);
}
/* Below ~560px the button and the field fight for the same row and the field loses — the
   placeholder was clipped to "gene symbol — e.g" with the input a few characters wide. Stack them:
   the search is this page's whole point and it does not get to be the thing that breaks first. */
@media(max-width:560px){
  .rxhome form{flex-direction:column; align-items:stretch; padding:6px; gap:6px}
  .rxhome form input{padding:12px 10px}
  .rxhome form button{width:100%; padding:12px 18px}
  /* The divider and indent separate stats sitting SIDE BY SIDE. Once they stack they become a
     stray rule down the left and a hanging indent on everything but the first. */
  .rxhome .stat{border-left:0; padding:16px 0 14px; border-top:1px solid var(--line2)}
  .rxhome .stat:first-child{border-top:0}
  .rxhome .stat:not(:first-child){padding-left:0}
}
@media(prefers-reduced-motion:reduce){.rxhome *{transition:none!important}}
`;

// No sign-out control here on purpose: StickyControls already floats Home + Logout over every
// authenticated screen, and a second one on this page would be the same action twice.
export default function HomeLanding_aaron({
  onOpenGene,
  onOpenTab,
  onStart,
  onExplore,
}: {
  onOpenGene: (gene: string, organism: 'human' | 'mouse') => void;
  onOpenTab: (tab: 'gene' | 'screen' | 'network') => void;
  onStart: () => void;
  onExplore: () => void;
}) {
  const [gene, setGene] = useState('');
  const [organism, setOrganism] = useState<'human' | 'mouse'>('human');

  ensureEditorialFonts();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const sym = gene.trim();
    // An empty box opens the wiki anyway rather than doing nothing — a dead-feeling button on the
    // one control this page is built around is worse than landing a step early.
    if (sym) onOpenGene(sym, organism);
    else onOpenTab('gene');
  };

  const go = (d: Dest) => {
    if (d.tab) onOpenTab(d.tab);
    else if (d.key === 'upload') onStart();
    else onExplore();
  };

  return (
    <div className="rxhome">
      <style>{CSS}</style>

      <div className="bar">
        <span className="mark">
          RETI<b>C</b>LE<span className="beta">beta</span>
        </span>
        <div className="grow" />
      </div>

      <div className="wrap">
        <section className="hero">
          <h1>Two thousand screens, <em>one gene at a time</em>.</h1>
          <p className="sub">
            Every published CRISPR screen we could harmonize, in one place — so a gene nobody has
            written a paper about still has evidence you can read.
          </p>

          <form onSubmit={submit}>
            <input
              value={gene}
              onChange={(e) => setGene(e.target.value)}
              placeholder="gene symbol — e.g. FANCD2"
              aria-label="Gene symbol"
              autoComplete="off"
              spellCheck={false}
            />
            <button type="submit">Open gene wiki →</button>
          </form>

          <div className="org">
            {(['human', 'mouse'] as const).map((o) => (
              <button
                key={o}
                className={o === organism ? 'on' : ''}
                onClick={() => setOrganism(o)}
                aria-pressed={o === organism}
              >
                {o === 'human' ? 'Human' : 'Mouse'}
              </button>
            ))}
          </div>

          <p className="alt">
            Working from a screen result instead?{' '}
            <button onClick={onStart}>Analyse a ranked gene list →</button>
          </p>
        </section>

        <div className="stats">
          {STATS.map((s) => (
            <div className="stat" key={s.k}>
              <b>{s.n}</b>
              <span>{s.k}</span>
            </div>
          ))}
        </div>

        <div className="eyebrow">Where to go</div>
        <div className="grid">
          {DESTS.map((d) => (
            <button className="dest" key={d.key} onClick={() => go(d)}>
              <h3>
                <i style={{ background: d.accent }} />
                {d.title}
                <span aria-hidden="true">→</span>
              </h3>
              <p>{d.body}</p>
              <div className="note">{d.note}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="foot">
        WashU DI² · Weidenbaum / IFNγ Macrophage Program · pure BioGRID ORCS CRISPR data — no
        literature mining
      </div>
    </div>
  );
}
