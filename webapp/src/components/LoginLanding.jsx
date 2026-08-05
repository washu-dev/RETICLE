import { useState } from 'react';
import { startLogin } from '../services/auth';
import {
  ensureEditorialFonts,
  EDITORIAL_TOKENS,
  PAPER_GROUND,
} from './landing_aaron/editorialTheme_aaron';

/**
 * The WashU SSO card.
 *
 * Restyled into the editorial palette the rest of the product uses — see
 * landing_aaron/editorialTheme_aaron.ts for why. The sign-in LOGIC is untouched: same startLogin(),
 * same busy and error states, same messages. Only the presentation moved.
 *
 * Self-contained styling on purpose. It used `.card` and --text-2/--text-3 from the app's global
 * dark theme; on a paper background those resolve to pale grey on white and the card disappears.
 * Everything it needs is scoped under .rxlogin instead.
 */
const CSS = `
.rxlogin{
  ${EDITORIAL_TOKENS}
  min-height:100vh; display:flex; align-items:center; justify-content:center;
  padding:24px; background:${PAPER_GROUND};
  color:var(--ink); font-family:var(--sans); line-height:1.5;
}
.rxlogin *{box-sizing:border-box}
.rxlogin .card{
  width:100%; max-width:428px; background:var(--card);
  border:1px solid var(--line); border-radius:18px; padding:44px 40px 34px;
  box-shadow:0 1px 2px #14161A08, 0 14px 44px -18px #14161A1f;
}
/* The mark, not a logo tile. The product signs its own name in the same face it uses for every
   gene it displays — a flask glyph would be the one piece of stock art in the whole system. */
.rxlogin .mark{
  font-family:var(--serif); font-weight:500; font-size:31px; letter-spacing:-.015em;
  color:var(--ink); margin:0;
}
.rxlogin .mark b{color:var(--know); font-weight:600}
.rxlogin .beta{
  font-family:var(--mono); font-size:10px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--faint); margin-left:9px; vertical-align:5px;
}
.rxlogin .expand{
  font-family:var(--mono); font-size:11px; letter-spacing:.055em; color:var(--muted);
  margin:14px 0 0; line-height:1.85;
}
/* The three accents spell the acronym in the order the product actually works in: what is known,
   what the screens measured, what a model proposed. */
.rxlogin .expand i{font-style:normal; font-weight:500}
.rxlogin .expand .k{color:var(--know)}
.rxlogin .expand .e{color:var(--eviq)}
.rxlogin .expand .p{color:var(--pred)}
.rxlogin .rule{height:1px; background:var(--line); margin:26px 0 22px}
.rxlogin .lede{font-size:13.5px; color:var(--ink2); line-height:1.65; margin:0 0 22px}
.rxlogin button{
  width:100%; display:flex; align-items:center; justify-content:center; gap:9px;
  padding:13px 22px; border:1px solid var(--know); border-radius:11px;
  background:var(--know); color:#fff; font-family:var(--sans); font-size:14.5px; font-weight:500;
  cursor:pointer; transition:background .18s, box-shadow .18s, transform .18s;
}
.rxlogin button:hover:not(:disabled){
  background:#1a5f78; box-shadow:0 0 0 4px var(--know-soft); transform:translateY(-1px);
}
.rxlogin button:disabled{cursor:default; opacity:.62}
.rxlogin button:focus-visible{outline:2px solid var(--ink); outline-offset:3px}
.rxlogin .err{
  margin:0 0 18px; padding:11px 14px; border-radius:10px; font-size:12.5px; line-height:1.55;
  border:1px solid var(--eviq); background:var(--eviq-soft); color:#8a5719;
}
.rxlogin .foot{
  font-family:var(--mono); font-size:10.5px; letter-spacing:.045em; color:var(--faint);
  text-align:center; margin:24px 0 0;
}
@media(prefers-reduced-motion:reduce){.rxlogin *{transition:none!important}}
`;

export default function LoginLanding() {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  ensureEditorialFonts();

  const handleLogin = async () => {
    setError(null);
    setBusy(true);
    try {
      await startLogin(); // redirects away on success
    } catch (e) {
      setBusy(false);
      setError(
        e?.message === 'SSO is not configured on the server'
          ? 'Single sign-on is not configured on the server yet.'
          : 'Could not start sign-in. Please try again.'
      );
    }
  };

  return (
    <div className="rxlogin">
      <style>{CSS}</style>
      <div className="card">
        <h1 className="mark">
          RETI<b>C</b>LE<span className="beta">beta</span>
        </h1>
        <p className="expand">
          <i className="k">R</i>ationale <i className="k">E</i>ngine <i className="e">T</i>o{' '}
          <i className="e">I</i>nform <i className="p">C</i>RISPR <i className="p">L</i>ist{' '}
          <i className="p">E</i>ntities
        </p>

        <div className="rule" />

        <p className="lede">
          A functional-genomics workbench over 2,157 harmonized CRISPR screens.
          Sign in with your WashU account to continue.
        </p>

        {error && <div role="alert" className="err">{error}</div>}

        <button onClick={handleLogin} disabled={busy}>
          {busy ? 'Redirecting…' : 'Sign in with WashU'}
          {!busy && <span aria-hidden="true">→</span>}
        </button>

        <p className="foot">WashU DI² · Weidenbaum / IFNγ Macrophage Program</p>
      </div>
    </div>
  );
}
