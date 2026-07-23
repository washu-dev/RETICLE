import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Search } from 'lucide-react';
import WashuLogo from '../washu/WashuLogo';

/**
 * The unified analysis shell: WashU top bar + scroll-spy section rail + a main
 * content column with a sticky context bar. One scrolling "instrument" — the
 * screen view (W1). The right-hand gene drawer (W2) mounts separately, above
 * this, so a gene click from anywhere folds into the same screen.
 */

export interface ShellSection {
  id: string;
  label: string;
}

export interface ContextItem {
  k: string;
  v: string;
}

interface DashboardShellProps {
  sections: ShellSection[];
  context: ContextItem[];
  /** Initials shown in the SSO avatar (e.g. "OO"). */
  initials?: string;
  onNewAnalysis: () => void;
  onLookupGene: (symbol: string) => void;
  /** The scrolling sections. Each child's top-level element id must match a
   *  section id above for scroll-spy to track it. */
  children: ReactNode;
}

export default function DashboardShell({
  sections,
  context,
  initials = 'OO',
  onNewAnalysis,
  onLookupGene,
  children,
}: DashboardShellProps) {
  const [active, setActive] = useState(sections[0]?.id ?? '');
  const [term, setTerm] = useState('');
  const mainRef = useRef<HTMLDivElement>(null);

  // Scroll-spy: highlight the rail link for the section currently in view.
  useEffect(() => {
    const els = sections
      .map((s) => document.getElementById(s.id))
      .filter((el): el is HTMLElement => el != null);
    if (els.length === 0) return;

    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) setActive(en.target.id);
        });
      },
      { rootMargin: '-45% 0px -50% 0px' }
    );
    els.forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, [sections]);

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    const s = term.trim();
    if (s) onLookupGene(s);
  }

  return (
    <div>
      {/* ===== TOP BAR ===== */}
      <header style={topbar}>
        <WashuLogo height={30} />
        <span style={appname}>
          RETI<span style={{ color: 'var(--washu-red)' }}>C</span>LE
        </span>
        <div style={{ flex: 1 }} />
        <form onSubmit={submitSearch} style={search} role="search">
          <Search size={15} color="var(--faint)" aria-hidden="true" />
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Look up a gene (e.g. Jak2)"
            aria-label="Look up a gene"
            style={searchInput}
          />
        </form>
        <div style={sso}>
          <span style={avatar} aria-hidden="true">{initials}</span>
          <span>WashU SSO</span>
        </div>
      </header>

      <div style={shell}>
        {/* ===== RAIL ===== */}
        <nav style={rail} aria-label="Sections">
          <div className="eyebrow" style={{ margin: '2px 8px 12px' }}>Analysis</div>
          {sections.map((s, i) => {
            const on = active === s.id;
            return (
              <a
                key={s.id}
                href={`#${s.id}`}
                aria-current={on ? 'true' : undefined}
                style={{ ...navlink, ...(on ? navlinkActive : null) }}
              >
                {on && <span style={navlinkBar} aria-hidden="true" />}
                <span style={{ ...navNum, ...(on ? { color: 'var(--washu-red)' } : null) }}>
                  {String(i + 1).padStart(2, '0')}
                </span>
                {s.label}
              </a>
            );
          })}
          <div style={{ flex: 1 }} />
          <button className="btn-primary" style={btnPrimary} onClick={onNewAnalysis}>New analysis</button>
        </nav>

        {/* ===== MAIN ===== */}
        <div style={{ minWidth: 0 }} ref={mainRef}>
          <div style={ctxbar}>
            {context.map((c, i) => (
              <div key={c.k} style={{ display: 'flex', alignItems: 'center', gap: 26 }}>
                {i > 0 && <span style={ctxSep} aria-hidden="true" />}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={ctxK}>{c.k}</span>
                  <span style={ctxV} className="tnum">{c.v}</span>
                </div>
              </div>
            ))}
          </div>
          <div style={content}>{children}</div>
        </div>
      </div>
    </div>
  );
}

/* ---- styles (WashU tokens) ---- */
const BAR_H = 64;

const topbar: React.CSSProperties = {
  position: 'sticky', top: 0, zIndex: 40, background: 'var(--white)',
  borderTop: '3px solid var(--washu-red)', borderBottom: '1px solid var(--border)',
  display: 'flex', alignItems: 'center', gap: 16, padding: '11px 20px',
};
const appname: React.CSSProperties = {
  fontWeight: 700, letterSpacing: '0.02em', paddingLeft: 16, marginLeft: 2,
  borderLeft: '1px solid var(--border-2)',
};
const search: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, background: 'var(--warm-gray)',
  border: '1px solid var(--border-2)', borderRadius: 6, padding: '8px 12px', minWidth: 250,
};
const searchInput: React.CSSProperties = {
  border: 'none', background: 'none', outline: 'none', fontSize: '0.9rem', color: '#111', width: '100%',
};
const sso: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 9, fontSize: '0.875rem', color: 'var(--fg-muted)',
};
const avatar: React.CSSProperties = {
  width: 32, height: 32, borderRadius: '50%', background: 'var(--washu-red)', color: '#fff',
  display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: '0.8rem',
};
const shell: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: '238px 1fr', minHeight: `calc(100vh - ${BAR_H}px)`,
};
const rail: React.CSSProperties = {
  background: 'var(--white)', borderRight: '1px solid var(--border)', padding: '20px 14px',
  position: 'sticky', top: BAR_H, height: `calc(100vh - ${BAR_H}px)`,
  display: 'flex', flexDirection: 'column',
};
const navlink: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 11, width: '100%', textAlign: 'left',
  padding: '10px 12px', borderRadius: 6, color: '#222', fontSize: '0.9rem', fontWeight: 600,
  textDecoration: 'none', position: 'relative', marginBottom: 2,
};
const navlinkActive: React.CSSProperties = { color: 'var(--washu-red)', background: 'var(--warm-gray)' };
const navlinkBar: React.CSSProperties = {
  position: 'absolute', left: 0, top: 8, bottom: 8, width: 3,
  background: 'var(--washu-red)', borderRadius: '0 3px 3px 0',
};
const navNum: React.CSSProperties = { fontSize: '0.72rem', color: 'var(--faint)', width: 16, fontWeight: 600 };
const btnPrimary: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700,
  fontSize: '0.875rem', padding: '11px 16px', borderRadius: 6,
  border: '2px solid var(--washu-red)', background: 'var(--washu-red)', color: '#fff', width: '100%',
};
const ctxbar: React.CSSProperties = {
  background: 'var(--white)', borderBottom: '1px solid var(--border)', padding: '13px 34px',
  display: 'flex', alignItems: 'center', gap: 26, flexWrap: 'wrap',
  position: 'sticky', top: BAR_H, zIndex: 20,
};
const ctxSep: React.CSSProperties = { width: 1, height: 28, background: 'var(--border)' };
const ctxK: React.CSSProperties = {
  fontSize: '0.65rem', letterSpacing: '0.07em', textTransform: 'uppercase',
  color: 'var(--faint)', fontWeight: 700,
};
const ctxV: React.CSSProperties = { fontSize: '0.94rem', color: '#111', fontWeight: 600 };
const content: React.CSSProperties = { padding: '20px 34px 120px', maxWidth: 1120 };
