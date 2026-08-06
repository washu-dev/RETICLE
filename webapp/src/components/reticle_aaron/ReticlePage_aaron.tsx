import { useEffect, useRef } from 'react';
import { mountReticle } from './vendor/reticleBundle_aaron';
import { API_BASE_URL } from '../../config/env';

const FONT_LINK_ID = 'reticle-editorial-fonts';
const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;' +
  '9..144,500;9..144,600&family=IBM+Plex+Sans:wght@300;400;500;600&' +
  'family=IBM+Plex+Mono:wght@400;500&display=swap';

/** Load the editorial fonts at the document level.
 *
 *  @font-face rules are not encapsulated by Shadow DOM — a <link> inside the shadow root would
 *  not register the family — so the prototype's own <link> tags are stripped during vendoring
 *  and re-added here instead. Same family set the Explorer page uses; if that page already
 *  added its copy the browser serves this one from cache. */
function ensureFonts(): void {
  if (document.getElementById(FONT_LINK_ID)) return;
  const link = document.createElement('link');
  link.id = FONT_LINK_ID;
  link.rel = 'stylesheet';
  link.href = FONT_HREF;
  document.head.appendChild(link);
}

/**
 * The Gene / Screen / Network pages from the standalone prototype.
 *
 * A thin React wrapper — the same shape as ExplorerPage — that mounts the vendored bundle
 * (Shadow-DOM isolated) into a host div. React owns nothing inside that node; the vendored code
 * owns its whole subtree, including its own tab bar.
 *
 * This is a SEPARATE entry point from the Explorer page rather than a replacement for it: the
 * Explorer is a port of an earlier prototype page (the standalone app has since replaced it with
 * the Gene tab here), and retiring it is a call for whoever owns that page, not a side effect of
 * adding this one.
 */
export default function ReticlePage_aaron({
  onBack,
  initial = 'gene',
  gene,
  organism,
}: {
  onBack: () => void;
  initial?: 'gene' | 'screen' | 'network';
  /** Open straight on this symbol. The home page's search box hands it over so the user does not
   *  type the same gene twice — once to get here, once on arrival. */
  gene?: string;
  /** Which species to resolve `gene` against. Passed through the page's virtual deep link so both
   *  the wiki and network select the correct organism before their first request. */
  organism?: 'human' | 'mouse';
}) {
  const hostRef = useRef<HTMLDivElement>(null);

  // onBack is read through a ref so a caller passing an inline arrow does not tear the whole
  // shadow tree down and re-run every page script on each parent render.
  const backRef = useRef(onBack);
  backRef.current = onBack;

  useEffect(() => {
    ensureFonts();
    const host = hostRef.current;
    if (!host) return;
    const cleanup = mountReticle(host, API_BASE_URL, {
      initial,
      initialGene: gene,
      initialOrganism: organism,
      onBack: () => backRef.current(),
    });
    return () => {
      if (typeof cleanup === 'function') cleanup();
    };
  }, [initial, gene, organism]);

  return <div ref={hostRef} style={{ width: '100%', minHeight: '100vh' }} />;
}
