import { useEffect, useRef } from 'react';

/**
 * The public marketing landing page — what a visitor sees before signing in.
 *
 * Structure: a hero whose centrepiece is a live readout of one harmonized screen (a field of gene
 * points settling along the essentiality axis), a marquee of the data sources RETICLE harmonizes,
 * the real corpus numbers, the three capabilities, and the dark-gene argument.
 *
 * TWO THINGS THAT LOOK ODD AND ARE DELIBERATE
 * -------------------------------------------
 * 1. **Every CSS selector is prefixed `.rxl`.** The app's global stylesheet is DARK — it sets a
 *    near-black background and light text on `body`, plus bare `a` and `button` rules. This page is
 *    light, lives in the same document, and must not inherit any of that or leak its own styles
 *    back out. Prefixing is what keeps both true; the `.rxl` block also re-declares the custom
 *    properties that were on `:root` in the standalone design.
 *
 * 2. **The markup is injected rather than written as JSX.** It is a static, author-controlled
 *    template with no interpolation of anything user-supplied, and keeping it as one block makes it
 *    reviewable against the design mockup it came from. The interactive parts are wired by the
 *    effect below against refs into that subtree, not by React.
 *
 * The visualization is illustrative — it is generated from a seeded PRNG, not from live API data,
 * and says so in the copy. It runs only while on screen and while the tab is visible, and does not
 * run at all under prefers-reduced-motion.
 */
// NOTE: the `.rxl.anim` rules are a COMPOUND selector, not a descendant one. In the standalone
// design the `anim` class went on <body>, an ancestor of everything it gated; here it goes on the
// .rxl root itself, so `.rxl .anim x` would never match and the hero would stay at opacity 0.
const CSS = `
.rxl{
  --paper:      #FBFBFC;
  --paper-2:    #F2F3F6;
  --ink:        #0E1013;
  --ink-2:      #5D646E;
  --ink-3:      #8A919B;
  --rule:       #E4E6EB;
  --rule-2:     #EEF0F3;
  --dot:        #C6CBD3;
  --signal:     #B01F4F;
  --signal-ink: #8A1339;

  --wrap: 1280px;
  --gutter: clamp(22px, 4.4vw, 64px);
  --section: clamp(84px, 10.5vw, 152px);

  --ease: cubic-bezier(.22,.68,.28,1);
}
.rxl *, .rxl *::before, .rxl *::after{ box-sizing:border-box; }
.rxl{
  color-scheme: light only;
  background: var(--paper);
  -webkit-text-size-adjust:100%;
  scroll-behavior:smooth;
}
.rxl{
  margin:0;
  background: var(--paper);
  color: var(--ink);
  font-family:'Instrument Sans', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
  font-size:16px;
  line-height:1.6;
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
  overflow-x:hidden;
}
@media (prefers-reduced-motion: reduce){
.rxl{ scroll-behavior:auto; } }

.rxl h1, .rxl h2, .rxl h3, .rxl p, .rxl ul, .rxl ol, .rxl figure, .rxl blockquote{ margin:0; }
.rxl ul{ padding:0; list-style:none; }
.rxl button{ font:inherit; color:inherit; }
.rxl a{ color:inherit; text-decoration:none; }
.rxl ::selection{ background:rgba(176,31,79,.14); }
.rxl :focus-visible{
  outline:2px solid var(--signal);
  outline-offset:3px;
  border-radius:2px;
}
.rxl .wrap{
  width:100%;
  max-width:var(--wrap);
  margin-inline:auto;
  padding-inline:var(--gutter);
}
.rxl .sr{
  position:absolute; width:1px; height:1px; overflow:hidden;
  clip:rect(0 0 0 0); clip-path:inset(50%); white-space:nowrap;
}
.rxl .eyebrow{
  font-size:.6875rem;
  font-weight:600;
  letter-spacing:.15em;
  text-transform:uppercase;
  color:var(--ink-3);
}
.rxl .display{
  font-family:'Newsreader', Georgia, serif;
  font-weight:300;
  letter-spacing:-.018em;
  line-height:1.04;
  color:var(--ink);
}
.rxl .lede{
  color:var(--ink-2);
  font-size:clamp(1rem, .95rem + .35vw, 1.1875rem);
  line-height:1.62;
  max-width:44ch;
}
.rxl .btn{
  display:inline-flex; align-items:center; gap:.55em;
  border:1px solid transparent;
  border-radius:999px;
  cursor:pointer;
  font-weight:500;
  letter-spacing:-.005em;
  transition: background-color .22s ease, color .22s ease, border-color .22s ease, transform .22s var(--ease);
}
.rxl .btn .arw{ transition:transform .3s var(--ease); }
.rxl .btn:hover .arw{ transform:translateX(3px); }
.rxl .btn-solid{
  background:var(--ink); color:#fff;
  padding:.86em 1.4em;
  font-size:.9375rem;
}
.rxl .btn-solid:hover{ background:#25292F; }
.rxl .btn-ghost{
  background:transparent; color:var(--ink);
  border-color:var(--rule);
  padding:.86em 1.35em;
  font-size:.9375rem;
}
.rxl .btn-ghost:hover{ border-color:#C9CDD4; background:#fff; }
.rxl .btn-sm{ padding:.58em 1.05em; font-size:.875rem; }
.rxl .hdr{
  position:sticky; top:0; z-index:50;
  background:rgba(251,251,252,.82);
  backdrop-filter:saturate(1.6) blur(14px);
  -webkit-backdrop-filter:saturate(1.6) blur(14px);
  border-bottom:1px solid transparent;
  transition:border-color .3s ease, background-color .3s ease;
}
.rxl .hdr.is-stuck{ border-bottom-color:var(--rule); }
.rxl .hdr-in{
  display:flex; align-items:center; gap:24px;
  height:70px;
}
.rxl .brand{ display:flex; align-items:center; gap:10px; margin-right:auto; }
.rxl .brand .mark{ display:block; flex:none; }
.rxl .brand .wordmark{
  font-size:.9375rem; font-weight:600;
  letter-spacing:.19em; text-transform:uppercase;
}
.rxl .nav{ display:flex; align-items:center; gap:30px; }
.rxl .nav a{
  font-size:.875rem; color:var(--ink-2);
  position:relative; padding:.35em 0;
  transition:color .2s ease;
}
.rxl .nav a::after{
  content:''; position:absolute; left:0; right:0; bottom:.05em;
  height:1px; background:var(--ink);
  transform:scaleX(0); transform-origin:left;
  transition:transform .3s var(--ease);
}
.rxl .nav a:hover{ color:var(--ink); }
.rxl .nav a:hover::after{ transform:scaleX(1); }
@media (max-width: 860px){
.rxl .nav{ display:none; } }

.rxl .hero{
  display:flex; flex-direction:column;
  min-height:min(100svh, 960px);
}
.rxl .hero-copy{
  flex:1 1 auto;
  display:flex; flex-direction:column; justify-content:center;
  padding-top:clamp(48px, 8vh, 96px);
  padding-bottom:clamp(40px, 6vh, 76px);
}
.rxl .hero h1{
  font-family:'Newsreader', Georgia, serif;
  font-weight:300;
  font-size:clamp(2.35rem, 6.1vw, 4.85rem);
  line-height:1.045;
  letter-spacing:-.021em;
  margin-top:.34em;
  max-width:15ch;
}
.rxl .hero h1 em{
  font-style:italic;
  font-weight:300;
}
.rxl .hero .lede{ margin-top:1.5rem; }
.rxl .hero-cta{
  display:flex; flex-wrap:wrap; gap:12px;
  margin-top:2.35rem;
}
.rxl .rise{ opacity:0; transform:translateY(16px); }
.rxl.anim .rise{ animation:rise .95s var(--ease) forwards; }
@keyframes rise{ to{ opacity:1; transform:none; } }
.rxl.anim .d1{ animation-delay:.05s }
.rxl.anim .d2{ animation-delay:.14s }
.rxl.anim .d3{ animation-delay:.24s }
.rxl.anim .d4{ animation-delay:.34s }
.rxl .readout{ flex:none; padding-bottom:clamp(20px, 3vh, 34px); }
.rxl .rd-head{
  display:flex; align-items:baseline; justify-content:space-between;
  gap:16px; flex-wrap:wrap;
  padding-bottom:14px;
}
.rxl .rd-slot{ display:flex; align-items:baseline; gap:11px; min-width:0; }
.rxl .rd-key{
  font-size:.625rem; font-weight:600; letter-spacing:.16em;
  text-transform:uppercase; color:var(--ink-3);
}
.rxl .rd-name{
  font-size:.875rem; color:var(--ink);
  font-variant-numeric:tabular-nums;
  letter-spacing:-.005em;
  transition:opacity .28s ease;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.rxl .rd-name.swap{ opacity:0; }
.rxl .rd-legend{
  display:flex; align-items:center; gap:8px;
  font-size:.75rem; color:var(--ink-3);
}
.rxl .rd-legend .sw{
  width:7px; height:7px; border-radius:50%;
  background:var(--signal); flex:none;
}
.rxl .field{
  position:relative;
  width:100vw; margin-left:calc(50% - 50vw);
  height:clamp(158px, 26vh, 268px);
}
.rxl #viz{
  display:block; width:100%; height:100%;
  -webkit-mask-image:linear-gradient(to right, transparent 0, #000 8%, #000 96%, transparent 100%);
  mask-image:linear-gradient(to right, transparent 0, #000 8%, #000 96%, transparent 100%);
}
.rxl .axis{
  width:100vw; margin-left:calc(50% - 50vw);
  height:1px; background:var(--rule);
  transform:scaleX(0); transform-origin:left center;
}
.rxl.anim .axis{ animation:draw 1.25s var(--ease) .28s forwards; }
@keyframes draw{ to{ transform:scaleX(1); } }
.rxl .axis-key{
  display:flex; justify-content:space-between; align-items:center;
  gap:12px;
  padding-top:11px;
  font-size:.6875rem; letter-spacing:.055em;
  color:var(--ink-3);
}
.rxl .axis-key .mid{ letter-spacing:.14em; text-transform:uppercase; }
@media (max-width:600px){
.rxl .axis-key .mid{ display:none; } }

.rxl .dot{ opacity:0; }
.rxl .dot{
  transition: transform 1500ms var(--ease), fill 900ms ease, opacity 800ms ease;
}
.rxl .viz-live .d-bulk{ fill:var(--dot); opacity:.92; }
.rxl .viz-live .d-mid{ fill:var(--signal); opacity:.40; }
.rxl .viz-live .d-sig{ fill:var(--signal); opacity:.95; }
.rxl .arc{
  fill:none; stroke:var(--signal); stroke-width:.75; opacity:0;
  stroke-dasharray:var(--len); stroke-dashoffset:var(--len);
}
.rxl .viz-live .arc{ animation:arc 4400ms ease forwards; }
@keyframes arc{
  0%  { stroke-dashoffset:var(--len); opacity:0; }
  18% { opacity:.34; }
  58% { stroke-dashoffset:0; opacity:.34; }
  82% { opacity:.34; }
  100%{ stroke-dashoffset:0; opacity:0; }
}
.rxl .hit{
  font-family:'Instrument Sans', sans-serif;
  font-size:10px; font-weight:500; letter-spacing:.09em;
  fill:var(--signal-ink); opacity:0;
  transition:opacity .6s ease;
}
.rxl .viz-live .hit{ opacity:.85; }
.rxl .hit-tick{ stroke:var(--signal); stroke-width:.75; opacity:0; transition:opacity .6s ease; }
.rxl .viz-live .hit-tick{ opacity:.3; }
.rxl .sources{
  border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule);
  padding-block:clamp(26px, 3.4vw, 38px);
  background:#fff;
}
.rxl .sources-key{
  text-align:center; margin-bottom:clamp(20px, 2.4vw, 28px);
}
.rxl .marquee{
  position:relative; overflow:hidden;
  -webkit-mask-image:linear-gradient(to right, transparent 0, #000 7%, #000 93%, transparent 100%);
  mask-image:linear-gradient(to right, transparent 0, #000 7%, #000 93%, transparent 100%);
}
.rxl .mq-track{
  display:flex; width:max-content;
  animation:slide 52s linear infinite;
}
.rxl .marquee:hover .mq-track{ animation-play-state:paused; }
@keyframes slide{ from{ transform:translate3d(0,0,0); } to{ transform:translate3d(-50%,0,0); } }
.rxl .mq-set{
  display:flex; align-items:center;
  gap:clamp(34px, 4.6vw, 68px);
  padding-right:clamp(34px, 4.6vw, 68px);
}
.rxl .mq-set li{
  display:flex; align-items:center;
  gap:clamp(34px, 4.6vw, 68px);
  font-size:clamp(.9375rem, 1.05vw, 1.0625rem);
  font-weight:600;
  letter-spacing:-.012em;
  color:#3F454E;
  white-space:nowrap;
}
.rxl .mq-set li::after{
  content:''; width:4px; height:4px; flex:none;
  background:var(--rule); transform:rotate(45deg);
}
.rxl .stats{ padding-block:clamp(56px, 7vw, 96px); }
.rxl .stat-grid{
  display:grid; grid-template-columns:repeat(5, 1fr);
  gap:0;
}
.rxl .stat{
  padding:4px 20px 4px 0;
  border-left:1px solid var(--rule);
  padding-left:22px;
}
.rxl .stat:first-child{ border-left:0; padding-left:0; }
.rxl .stat .num{
  font-family:'Newsreader', Georgia, serif;
  font-weight:300;
  font-size:clamp(1.65rem, 2.8vw, 2.6rem);
  line-height:1.05; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;
  display:block;
}
.rxl .stat .lab{
  display:block; margin-top:.7em;
  font-size:.75rem; color:var(--ink-2); line-height:1.4;
}
@media (max-width:780px){
.rxl .stat-grid{ grid-template-columns:1fr; }
.rxl .stat{
    border-left:0; padding:15px 0;
    border-top:1px solid var(--rule);
    display:flex; align-items:baseline; justify-content:space-between; gap:18px;
  }
.rxl .stat:first-child{ padding-left:0; }
.rxl .stat .lab{ margin-top:0; text-align:right; max-width:19ch; }
}

.rxl .caps{ padding-block:0 var(--section); }
.rxl .sec-head{ max-width:34ch; margin-bottom:clamp(44px, 5.5vw, 72px); }
.rxl .sec-head h2{
  font-family:'Newsreader', Georgia, serif;
  font-weight:300;
  font-size:clamp(1.85rem, 3.5vw, 3rem);
  line-height:1.1; letter-spacing:-.02em;
  margin-top:.5em;
}
.rxl .cap-grid{
  display:grid; grid-template-columns:repeat(3, 1fr);
  gap:clamp(30px, 3.6vw, 56px);
}
@media (max-width:880px){
.rxl .cap-grid{ grid-template-columns:1fr; gap:0; } }

.rxl .cap{ border-top:1px solid var(--ink); padding-top:20px; }
@media (max-width:880px){
.rxl .cap{ border-top:1px solid var(--rule); padding:26px 0; }
.rxl .cap:first-child{ border-top-color:var(--ink); }
}

.rxl .cap .tag{
  font-size:.6875rem; font-weight:600; letter-spacing:.15em;
  text-transform:uppercase; color:var(--ink);
}
.rxl .cap h3{
  font-family:'Newsreader', Georgia, serif;
  font-weight:300; font-size:clamp(1.3rem, 1.9vw, 1.6rem);
  line-height:1.22; letter-spacing:-.015em;
  margin-top:1.15rem;
}
.rxl .cap p{
  margin-top:.85rem; font-size:.9375rem; line-height:1.62;
  color:var(--ink-2); max-width:38ch;
}
.rxl .dark{
  background:var(--paper-2);
  border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule);
  padding-block:var(--section);
}
.rxl .dark-in{
  display:grid; grid-template-columns:minmax(0,1fr) minmax(0,.85fr);
  gap:clamp(34px, 5vw, 88px);
  align-items:start;
}
@media (max-width:880px){
.rxl .dark-in{ grid-template-columns:1fr; } }

.rxl .dark blockquote{
  font-family:'Newsreader', Georgia, serif;
  font-weight:300; font-style:italic;
  font-size:clamp(1.6rem, 3.3vw, 2.7rem);
  line-height:1.2; letter-spacing:-.018em;
  border-left:1px solid var(--signal);
  padding-left:clamp(18px, 2vw, 28px);
  margin-top:1.1em;
}
.rxl .dark-body p{
  color:var(--ink-2); font-size:clamp(.9375rem, 1vw, 1.0625rem);
  line-height:1.68; max-width:42ch;
}
.rxl .dark-body p + p{ margin-top:1.1em; }
.rxl .dark-body .mark-n{ color:var(--ink); font-weight:500; font-variant-numeric:tabular-nums; }
.rxl .close{ padding-block:var(--section); text-align:center; }
.rxl .close h2{
  font-family:'Newsreader', Georgia, serif;
  font-weight:300;
  font-size:clamp(2rem, 4.4vw, 3.6rem);
  line-height:1.08; letter-spacing:-.021em;
  margin-top:.4em;
}
.rxl .close p{ margin:1.35rem auto 0; color:var(--ink-2); max-width:40ch; font-size:1rem; }
.rxl .close .btn{ margin-top:2.2rem; }
.rxl .ftr{ border-top:1px solid var(--rule); padding-block:38px 46px; }
.rxl .ftr-in{
  display:flex; align-items:center; justify-content:space-between;
  gap:20px; flex-wrap:wrap;
  font-size:.8125rem; color:var(--ink-3);
}
.rxl .ftr .brand .wordmark{ font-size:.8125rem; }
.rxl .ftr .credit{ max-width:52ch; line-height:1.55; }
.rxl .ftr .credit b{ font-weight:500; color:var(--ink-2); }
.rxl .rev{ opacity:0; transform:translateY(18px); transition:opacity .8s var(--ease), transform .8s var(--ease); }
.rxl .rev.in{ opacity:1; transform:none; }


@media (prefers-reduced-motion: reduce){
.rxl.anim .rise, .rxl .rise{ opacity:1; transform:none; animation:none; }
.rxl .axis, .rxl.anim .axis{ transform:none; animation:none; }
.rxl .dot{ transition:none; }
.rxl .arc, .rxl .viz-live .arc{ animation:none; opacity:.28; stroke-dashoffset:0; }
.rxl .rev{ opacity:1; transform:none; transition:none; }
.rxl .mq-track{ animation:none; }
.rxl .btn, .rxl .btn .arw, .rxl .nav a::after{ transition:none; }
}

.rxl .no-motion .mq-track{
  animation:none;
  flex-wrap:wrap; justify-content:center; width:auto;
  row-gap:14px;
}
.rxl .no-motion .mq-dup{ display:none; }
.rxl .no-motion .marquee{ -webkit-mask-image:none; mask-image:none; }`;

const MARKUP = `
<header class="hdr" id="hdr">
  <div class="wrap hdr-in">
    <a class="brand" href="#top" aria-label="RETICLE home">
      <svg class="mark" width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="6.1" fill="none" stroke="#0E1013" stroke-width="1.1"/>
        <circle cx="10" cy="10" r="1.5" fill="#B01F4F"/>
        <path d="M10 0.9v3.1M10 16v3.1M0.9 10h3.1M16 10h3.1" stroke="#0E1013" stroke-width="1.1" stroke-linecap="round"/>
      </svg>
      <span class="wordmark">Reticle</span>
    </a>
    <nav class="nav" aria-label="Primary">
      <a href="#what">What it does</a>
      <a href="#dark">Dark genes</a>
      <a href="#sources">Sources</a>
    </nav>
    <button type="button" class="btn btn-solid btn-sm js-signin">Sign in</button>
  </div>
</header>

<main id="top">

  
  <section class="hero">
    <div class="wrap hero-copy">
      <p class="eyebrow rise d1">Pooled CRISPR screens &middot; WashU</p>
      <h1 class="rise d2">AI-powered bioinformatics<br class="brk"> for understanding<br class="brk"> every discovered gene.</h1>
      <p class="lede rise d3">
        RETICLE harmonizes 2,157 published pooled screens so you can ask what a knockout
        actually does &mdash; across all of them at once, in one reading, instead of a
        literature crawl.
      </p>
      <div class="hero-cta rise d4">
        <button type="button" class="btn btn-solid js-signin">
          Sign in <span class="arw" aria-hidden="true">&rarr;</span>
        </button>
        <a class="btn btn-ghost" href="#what">See what it does</a>
      </div>
    </div>

    <div class="readout">
      <div class="wrap rd-head">
        <div class="rd-slot">
          <span class="rd-key">Screen</span>
          <span class="rd-name" id="rdName">K562 &middot; proliferation</span>
        </div>
        <div class="rd-legend"><span class="sw" aria-hidden="true"></span> essential in this screen</div>
      </div>

      <div class="field">
        <svg id="viz" aria-hidden="true" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
      <div class="axis"></div>
      <div class="wrap axis-key">
        <span>&larr; depleted</span>
        <span class="mid">log&#8322; fold change</span>
        <span>enriched &rarr;</span>
      </div>
      <p class="sr">
        A visualization of one harmonized screen: each point is a gene, positioned by its
        log2 fold change. Genes in the depleted tail are essential in that screen and are
        highlighted, with lines linking genes that drop out together.
      </p>
    </div>
  </section>

  
  <section class="sources" id="sources" aria-labelledby="srcKey">
    <p class="eyebrow sources-key" id="srcKey">Sources harmonized</p>
    <div class="marquee" id="marquee">
      <div class="mq-track">
        <ul class="mq-set">
          <li>NCBI</li><li>UniProt</li><li>Gene Ontology</li><li>Reactome</li>
          <li>STRING</li><li>DepMap</li><li>BioGRID ORCS</li><li>AlphaFold</li>
          <li>RCSB PDB</li><li>PubMed</li><li>EBI</li>
        </ul>
        <ul class="mq-set mq-dup" aria-hidden="true">
          <li>NCBI</li><li>UniProt</li><li>Gene Ontology</li><li>Reactome</li>
          <li>STRING</li><li>DepMap</li><li>BioGRID ORCS</li><li>AlphaFold</li>
          <li>RCSB PDB</li><li>PubMed</li><li>EBI</li>
        </ul>
      </div>
    </div>
  </section>

  
  <section class="stats">
    <div class="wrap">
      <div class="stat-grid rev">
        <div class="stat"><span class="num">2,157</span><span class="lab">pooled screens, harmonized</span></div>
        <div class="stat"><span class="num">109,412</span><span class="lab">co-essentiality edges</span></div>
        <div class="stat"><span class="num">137,715</span><span class="lab">genes in the knowledge base</span></div>
        <div class="stat"><span class="num">1,032,303</span><span class="lab">GO annotations</span></div>
        <div class="stat"><span class="num">79,397</span><span class="lab">Reactome pathway annotations</span></div>
      </div>
    </div>
  </section>

  
  <section class="caps" id="what">
    <div class="wrap">
      <div class="sec-head rev">
        <p class="eyebrow">What it does</p>
        <h2>Three questions, answered from the same corpus.</h2>
      </div>
      <div class="cap-grid">
        <article class="cap rev">
          <p class="tag">Gene</p>
          <h3>Everything known, next to everything measured.</h3>
          <p>Curated function, GO terms, pathways, structure and a darkness rating &mdash;
             beside the gene&rsquo;s behaviour across every harmonized screen, with an
             AI reading of that footprint.</p>
        </article>
        <article class="cap rev">
          <p class="tag">Screen</p>
          <h3>Find the screens that behave like yours.</h3>
          <p>Start from a single screen and get the ones most correlated with it, ranked
             and kept within their assay domain so a fitness screen is never mistaken
             for a reporter screen.</p>
        </article>
        <article class="cap rev">
          <p class="tag">Network</p>
          <h3>A network drawn from perturbation, not from papers.</h3>
          <p>Genes are linked by how they fail together across screens. No citation
             counts, no text mining &mdash; the edges come out of the data itself.</p>
        </article>
      </div>
    </div>
  </section>

  
  <section class="dark" id="dark">
    <div class="wrap dark-in">
      <div class="rev">
        <p class="eyebrow">Dark genes</p>
        <blockquote>Some genes have no literature at all. They still have a neighbourhood.</blockquote>
      </div>
      <div class="dark-body rev">
        <p>Networks built from published work can only describe genes people have already
           written about. RETICLE&rsquo;s <span class="mark-n">109,412</span> edges are derived
           from how genes behave when they are knocked out, so coverage does not depend on
           anyone having studied them first.</p>
        <p>That is the part that matters. A gene with almost no PubMed record still lands
           among genes whose function is known, and that placement is a hypothesis you can
           take to the bench.</p>
      </div>
    </div>
  </section>

  
  <section class="close">
    <div class="wrap rev">
      <p class="eyebrow">Start anywhere</p>
      <h2>Begin with a gene.</h2>
      <p>Type a symbol and read its footprint across two thousand screens.</p>
      <button type="button" class="btn btn-solid js-signin">
        Sign in <span class="arw" aria-hidden="true">&rarr;</span>
      </button>
    </div>
  </section>

</main>

<footer class="ftr">
  <div class="wrap ftr-in">
    <div class="brand">
      <svg class="mark" width="17" height="17" viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="10" cy="10" r="6.1" fill="none" stroke="#8A919B" stroke-width="1.1"/>
        <circle cx="10" cy="10" r="1.5" fill="#8A919B"/>
        <path d="M10 0.9v3.1M10 16v3.1M0.9 10h3.1M16 10h3.1" stroke="#8A919B" stroke-width="1.1" stroke-linecap="round"/>
      </svg>
      <span class="wordmark">Reticle</span>
    </div>
    <p class="credit">
      Built at <b>Washington University in St.&nbsp;Louis</b> &mdash; DI&sup2; &middot;
      Weidenbaum, IFN&gamma; Macrophage Program.
    </p>
  </div>
</footer>`;

const FONT_LINK_ID = 'reticle-landing-fonts';
const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400..600;1,400' +
  '&family=Newsreader:ital,opsz,wght@0,6..72,200..500;1,6..72,200..400&display=swap';

/** @font-face is document-level, so the link goes in <head> rather than inside the component. */
function ensureFonts(): void {
  if (document.getElementById(FONT_LINK_ID)) return;
  const link = document.createElement('link');
  link.id = FONT_LINK_ID;
  link.rel = 'stylesheet';
  link.href = FONT_HREF;
  document.head.appendChild(link);
}

/** One screen's worth of illustrative gene scores. Seeded, so a given screen always looks the same. */
const SCREENS = [
  { name: 'K562 · proliferation', hits: ['RPL23A', 'POLR2A'], seed: 0x51a3 },
  { name: 'THP-1 · IFNγ response', hits: ['JAK1', 'STAT1'], seed: 0x2e77 },
  { name: 'A375 · vemurafenib survival', hits: ['NF1', 'MED12'], seed: 0x9c41 },
  { name: 'HAP1 · core essentiality', hits: ['EIF3B', 'SNRPD1'], seed: 0x1b8d },
  { name: 'Jurkat · TCR signalling', hits: ['LCK', 'ZAP70'], seed: 0x74c2 },
];

const SMIN = -4.35;
const SMAX = 1.75;
const SVGNS = 'http://www.w3.org/2000/svg';

function mulberry32(a: number): () => number {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gauss(rnd: () => number): number {
  let u = 0;
  let v = 0;
  while (u === 0) u = rnd();
  while (v === 0) v = rnd();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export default function MarketingLanding_aaron({ onSignIn }: { onSignIn: () => void }) {
  const rootRef = useRef<HTMLDivElement>(null);

  // Read through a ref so a caller passing an inline arrow does not tear the whole page down and
  // restart every animation on each parent render.
  const signInRef = useRef(onSignIn);
  signInRef.current = onSignIn;

  useEffect(() => {
    ensureFonts();
    const root = rootRef.current;
    if (!root) return;

    const $ = (sel: string) => root.querySelector(sel);
    // Guarded: matchMedia is absent in jsdom (and in any non-browser render), and an unguarded
    // call takes the whole page down rather than just losing the motion preference. Treating a
    // missing implementation as "no preference expressed" keeps the animated path as the default.
    const reduce =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Everything that has to be undone on unmount is registered here, so the cleanup cannot drift
    // out of sync with the setup as this page grows.
    const cleanups: Array<() => void> = [];
    const on = <K extends keyof WindowEventMap>(
      target: Window | Document,
      type: K | string,
      fn: EventListener,
      opts?: AddEventListenerOptions,
    ) => {
      target.addEventListener(type, fn, opts);
      cleanups.push(() => target.removeEventListener(type, fn, opts));
    };

    root.querySelectorAll('.js-signin').forEach((b) => {
      const h = () => signInRef.current();
      b.addEventListener('click', h);
      cleanups.push(() => b.removeEventListener('click', h));
    });

    // Sticky-header hairline.
    const hdr = $('#hdr');
    const onScroll = () => hdr?.classList.toggle('is-stuck', window.scrollY > 8);
    onScroll();
    on(window, 'scroll', onScroll, { passive: true });

    // Scroll reveal.
    const revs = Array.from(root.querySelectorAll<HTMLElement>('.rev'));
    if (reduce || !('IntersectionObserver' in window)) {
      revs.forEach((el) => el.classList.add('in'));
    } else {
      const io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) {
              e.target.classList.add('in');
              io.unobserve(e.target);
            }
          });
        },
        { rootMargin: '0px 0px -12% 0px', threshold: 0.08 },
      );
      revs.forEach((el, i) => {
        el.style.transitionDelay = `${Math.min(i, 4) * 60}ms`;
        io.observe(el);
      });
      cleanups.push(() => io.disconnect());
    }

    if (reduce) $('#marquee')?.parentElement?.classList.add('no-motion');

    // ── the readout ────────────────────────────────────────────────────────────────────────
    const svg = $('#viz') as SVGSVGElement | null;
    const field = svg?.parentElement;
    const rdName = $('#rdName');
    if (!svg || !field || !rdName) return () => cleanups.forEach((c) => c());

    const gArcs = document.createElementNS(SVGNS, 'g');
    const gDots = document.createElementNS(SVGNS, 'g');
    const gHits = document.createElementNS(SVGNS, 'g');
    svg.append(gArcs, gDots, gHits);

    let dots: SVGCircleElement[] = [];
    let N = 0;
    let W = 0;
    let H = 0;
    let R = 2.3;
    let cur = 0;
    let running = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    let arcTimer: ReturnType<typeof setTimeout> | null = null;
    let resizeTimer: ReturnType<typeof setTimeout> | null = null;
    let swapTimer: ReturnType<typeof setTimeout> | null = null;
    let startTimer: ReturnType<typeof setTimeout> | null = null;

    function scoresFor(seed: number): number[] {
      const rnd = mulberry32(seed);
      const out: number[] = [];
      for (let k = 0; k < N; k++) {
        const u = rnd();
        let s: number;
        if (u < 0.118) s = -2.3 + gauss(rnd) * 0.86;        // essential tail
        else if (u < 0.158) s = 0.85 + gauss(rnd) * 0.42;   // enriched
        else s = gauss(rnd) * 0.52;                         // bulk, no effect
        out.push(Math.max(SMIN + 0.05, Math.min(SMAX - 0.05, s)));
      }
      // Sorted so a point keeps its identity between screens and the settle sweeps left to right.
      out.sort((a, b) => a - b);
      return out;
    }

    function build(): void {
      const rect = field!.getBoundingClientRect();
      W = Math.max(320, Math.round(rect.width));
      H = Math.max(120, Math.round(rect.height));
      svg!.setAttribute('viewBox', `0 0 ${W} ${H}`);

      const wantN = W < 620 ? 165 : W < 1000 ? 300 : 430;
      R = W < 620 ? 1.9 : 2.3;

      if (wantN !== N) {
        N = wantN;
        gDots.textContent = '';
        dots = [];
        const scatter = mulberry32(0x7a31);
        for (let i = 0; i < N; i++) {
          const c = document.createElementNS(SVGNS, 'circle');
          c.setAttribute('r', String(R));
          c.setAttribute('class', 'dot d-bulk');
          c.style.transform = `translate(${scatter() * W}px,${scatter() * H * 0.9}px)`;
          c.style.transitionDelay = `${((i / N) * 430).toFixed(0)}ms`;
          gDots.appendChild(c);
          dots.push(c);
        }
      } else {
        dots.forEach((d) => d.setAttribute('r', String(R)));
      }
    }

    function drawArcs(pts: Array<[number, number, number]>): void {
      gArcs.textContent = '';
      const pool: Array<[number, number, number]> = [];
      for (let i = 0; i < pts.length && pool.length < 26; i++) {
        if (pts[i][2] <= -1.75) pool.push(pts[i]);
      }
      if (pool.length < 6) return;

      const rnd = mulberry32(SCREENS[cur].seed ^ 0x3f1);
      let made = 0;
      let tries = 0;
      while (made < 5 && tries < 40) {
        tries++;
        const a = Math.floor(rnd() * pool.length);
        const b = Math.floor(rnd() * pool.length);
        if (Math.abs(a - b) < 4) continue;
        const p1 = pool[a];
        const p2 = pool[b];
        const cx = (p1[0] + p2[0]) / 2;
        const cy = Math.min(p1[1], p2[1]) - (26 + rnd() * 34);
        const path = document.createElementNS(SVGNS, 'path');
        path.setAttribute('class', 'arc');
        path.setAttribute(
          'd',
          `M${p1[0].toFixed(1)} ${p1[1].toFixed(1)} Q${cx.toFixed(1)} ${cy.toFixed(1)} ` +
            `${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`,
        );
        gArcs.appendChild(path);
        path.style.setProperty('--len', path.getTotalLength().toFixed(1));
        path.style.animationDelay = `${made * 190}ms`;
        made++;
      }
    }

    function place(index: number, animateArcs: boolean): void {
      const sc = SCREENS[index];
      const scores = scoresFor(sc.seed);

      const pad = Math.max(10, W * 0.012);
      const colW = W < 620 ? 11 : W < 1000 ? 16 : 20.5;
      const NB = Math.max(12, Math.round((W - pad * 2) / colW));
      const span = (W - pad * 2) / NB;

      const counts = new Array(NB).fill(0);
      const bins = new Array<number>(N);
      let maxC = 1;
      for (let i = 0; i < N; i++) {
        const x = ((scores[i] - SMIN) / (SMAX - SMIN)) * (W - pad * 2) + pad;
        const idx = Math.max(0, Math.min(NB - 1, Math.floor((x - pad) / span)));
        bins[i] = idx;
        counts[idx]++;
        if (counts[idx] > maxC) maxC = counts[idx];
      }

      const head = W < 620 ? 20 : 30;   // room for the hit labels
      const gap = Math.min(2 * R + 2.3, (H - head) / maxC);
      const stack = new Array(NB).fill(0);

      const pts: Array<[number, number, number]> = new Array(N);
      for (let i = 0; i < N; i++) {
        const idx = bins[i];
        const k = stack[idx]++;
        const px = pad + (idx + 0.5) * span;
        const py = H - 1.5 - (k + 0.5) * gap;
        pts[i] = [px, py, scores[i]];
        const cls =
          scores[i] <= -1.9 ? 'dot d-sig' : scores[i] <= -1.05 ? 'dot d-mid' : 'dot d-bulk';
        const el = dots[i];
        if (el.getAttribute('class') !== cls) el.setAttribute('class', cls);
        el.style.transform = `translate(${px.toFixed(1)}px,${py.toFixed(1)}px)`;
      }

      gHits.textContent = '';
      if (W >= 620) {
        ([[3, -13], [17, -30]] as Array<[number, number]>).forEach((spec, n) => {
          const p = pts[spec[0]];
          if (!p) return;
          const t = document.createElementNS(SVGNS, 'text');
          t.setAttribute('class', 'hit');
          t.setAttribute('x', (p[0] + 7).toFixed(1));
          t.setAttribute('y', (p[1] + spec[1]).toFixed(1));
          t.textContent = sc.hits[n];
          const ln = document.createElementNS(SVGNS, 'line');
          ln.setAttribute('class', 'hit-tick');
          ln.setAttribute('x1', p[0].toFixed(1));
          ln.setAttribute('y1', (p[1] - 4).toFixed(1));
          ln.setAttribute('x2', p[0].toFixed(1));
          ln.setAttribute('y2', (p[1] + spec[1] + 4).toFixed(1));
          gHits.append(ln, t);
        });
      }

      if (arcTimer) { clearTimeout(arcTimer); arcTimer = null; }
      gArcs.textContent = '';
      if (!reduce && animateArcs) arcTimer = setTimeout(() => drawArcs(pts), 1750);
      else if (reduce) drawArcs(pts);
    }

    function advance(): void {
      cur = (cur + 1) % SCREENS.length;
      rdName!.classList.add('swap');
      swapTimer = setTimeout(() => {
        rdName!.textContent = SCREENS[cur].name;
        rdName!.classList.remove('swap');
      }, 280);
      place(cur, true);
    }

    function start(): void {
      if (running || reduce) return;
      running = true;
      timer = setInterval(advance, 7200);
    }
    function stop(): void {
      running = false;
      if (timer) { clearInterval(timer); timer = null; }
    }

    build();
    rdName.textContent = SCREENS[0].name;

    let raf1 = 0;
    let raf2 = 0;
    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        // The standalone design toggled this on <body>; here it belongs to our own root.
        root!.classList.add('anim');
        svg!.classList.add('viz-live');
        place(0, true);
        if (!reduce) startTimer = setTimeout(start, 2600);
      });
    });

    // Run only while the readout is on screen and the tab is visible.
    if (!reduce && 'IntersectionObserver' in window) {
      const vio = new IntersectionObserver(
        (entries) => entries.forEach((e) => (e.isIntersecting ? start() : stop())),
        { threshold: 0 },
      );
      vio.observe(field);
      cleanups.push(() => vio.disconnect());
    }
    on(document, 'visibilitychange', () => (document.hidden ? stop() : start()));

    on(window, 'resize', () => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        const before = N;
        build();
        place(cur, before !== N);
      }, 180);
    }, { passive: true });

    return () => {
      stop();
      [arcTimer, resizeTimer, swapTimer, startTimer].forEach((t) => t && clearTimeout(t));
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      cleanups.forEach((c) => c());
    };
  }, []);

  return (
    <>
      <style>{CSS}</style>
      <div className="rxl" ref={rootRef} dangerouslySetInnerHTML={{ __html: MARKUP }} />
    </>
  );
}
