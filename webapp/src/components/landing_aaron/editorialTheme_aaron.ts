/**
 * The palette and type the RETICLE feature pages use, for the two screens that sit in front of
 * them: the SSO card and the signed-in home.
 *
 * WHY THIS EXISTS. There were two design systems in the app. The public marketing page is
 * Instrument Sans / Newsreader on a crimson accent; every page BEHIND the login — gene wiki,
 * screen, network — is Fraunces / IBM Plex on teal, ochre and violet. The login card and the home
 * page sat in a third look entirely (a blue gradient on near-black), so a visitor crossed three
 * visual identities to reach one product. These two screens join the pages they lead to, because
 * that is the pair a signed-in user moves between all day.
 *
 * The three accents are not decoration — they carry the same meaning here as inside the product:
 *   know  teal    what is established
 *   eviq  ochre   what the screens measured
 *   pred  violet  what a model proposed
 */

export const FONT_LINK_ID = 'reticle-editorial-fonts';
const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;' +
  '9..144,500;9..144,600&family=IBM+Plex+Sans:wght@300;400;500;600&' +
  'family=IBM+Plex+Mono:wght@400;500&display=swap';

/** Load the editorial faces once, at document level. Shares an id with ReticlePage_aaron's copy,
 *  so whichever screen mounts first pays for it and the other finds it already there. */
export function ensureEditorialFonts(): void {
  if (typeof document === 'undefined' || document.getElementById(FONT_LINK_ID)) return;
  const link = document.createElement('link');
  link.id = FONT_LINK_ID;
  link.rel = 'stylesheet';
  link.href = FONT_HREF;
  document.head.appendChild(link);
}

/** Scoped to a root class so nothing leaks into the rest of the app, which is still on its own
 *  dark theme — these two screens are not a licence to restyle everything else. */
export const EDITORIAL_TOKENS = `
  --paper:#FCFCFB; --ink:#14161A; --ink2:#3A3D44; --muted:#6B7280; --faint:#9AA0A6;
  --line:#E8E6E1; --line2:#F1EFEA; --card:#FFFFFF;
  --know:#1F6F8B; --eviq:#C77D31; --pred:#7C5CBF;
  --know-soft:#1F6F8B14; --eviq-soft:#C77D3114; --pred-soft:#7C5CBF14;
  --serif:"Fraunces",Georgia,serif;
  --sans:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,monospace;
`;

/** The dotted ground every feature page sits on, so the door matches the room. */
export const PAPER_GROUND =
  'radial-gradient(circle at 1px 1px, var(--line2) 1px, transparent 0) 0 0/22px 22px,' +
  'radial-gradient(ellipse at 50% 34%, #FFFFFF 0%, #FBFBF9 55%, #F5F4F0 100%)';
