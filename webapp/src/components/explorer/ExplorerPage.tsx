import { useEffect, useRef } from 'react';
import { mountExplorer } from './vendor/explorerBundle';
import { API_BASE_URL } from '../../config/env';

const FONT_LINK_ID = 'reticle-explorer-fonts';
const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;' +
  '9..144,500;9..144,600&family=IBM+Plex+Sans:wght@300;400;500;600&' +
  'family=IBM+Plex+Mono:wght@400;500&display=swap';

/** Load the Explorer's editorial fonts at the document level (font-faces are not
 *  encapsulated by Shadow DOM, so this is how the shadow content picks them up). */
function ensureFonts(): void {
  if (document.getElementById(FONT_LINK_ID)) return;
  const link = document.createElement('link');
  link.id = FONT_LINK_ID;
  link.rel = 'stylesheet';
  link.href = FONT_HREF;
  document.head.appendChild(link);
}

/**
 * The Explorer page. A thin React wrapper that mounts the vendored prototype
 * (Shadow-DOM isolated) into a host div and drives it via a ref + effect.
 * React owns nothing inside the host node — the vendored code owns its subtree.
 */
export default function ExplorerPage({ onBack }: { onBack: () => void }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ensureFonts();
    const host = hostRef.current;
    if (!host) return;
    (window as unknown as { __rxBack?: () => void }).__rxBack = onBack;
    const cleanup = mountExplorer(host, API_BASE_URL);
    return () => {
      if (typeof cleanup === 'function') cleanup();
      delete (window as unknown as { __rxBack?: () => void }).__rxBack;
      const root = (host as unknown as { __rxRoot?: ShadowRoot }).__rxRoot;
      if (root) root.innerHTML = '';
    };
  }, [onBack]);

  return <div ref={hostRef} style={{ width: '100%', minHeight: '100vh' }} />;
}
