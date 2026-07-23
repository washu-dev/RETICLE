/**
 * Provenance — marks a block by the KIND of claim it makes, a RETICLE signature.
 * Three epistemically different sources, never conflated:
 *   ai       — di2 narrative (hypothesis-generating; verify against sources)
 *   computed — deterministic pipeline output (counts, correlations)
 *   source   — measured data & literature
 *
 * Marks are inline SVG (no emoji, per the WashU design system). Colors and
 * type come from the .prov* classes in styles/reticle.css.
 */

import type { CSSProperties } from 'react';

export type ProvKind = 'ai' | 'computed' | 'source';

const CLASS: Record<ProvKind, string> = { ai: 'ai', computed: 'cp', source: 'src' };
const DEFAULT_LABEL: Record<ProvKind, string> = {
  ai: 'AI-generated · di2',
  computed: 'Computed',
  source: 'Source',
};

/** The bare mark glyph for a provenance kind. `aria-hidden` — the label carries meaning. */
export function ProvMark({ kind }: { kind: ProvKind }) {
  if (kind === 'ai') {
    return (
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 2l1.8 5.4L19 9l-5.2 1.6L12 16l-1.8-5.4L5 9l5.2-1.6z" />
      </svg>
    );
  }
  if (kind === 'computed') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" strokeLinecap="round" />
    </svg>
  );
}

interface ProvenanceProps {
  kind: ProvKind;
  /** Override the default label ("Computed", "Source", "AI-generated · di2"). */
  label?: string;
  /** Trailing muted clarifier, shown after an em dash. */
  sub?: string;
  style?: CSSProperties;
}

export default function Provenance({ kind, label, sub, style }: ProvenanceProps) {
  return (
    <div className={`prov ${CLASS[kind]}`} style={style}>
      <ProvMark kind={kind} />
      <span>{label ?? DEFAULT_LABEL[kind]}</span>
      {sub && <span className="sub">— {sub}</span>}
    </div>
  );
}

/** The "How to read" strip: one line explaining all three marks. */
export function ProvenanceLegend({ style }: { style?: CSSProperties }) {
  return (
    <div className="prov-legend" role="note" aria-label="How to read results" style={style}>
      <span style={{ fontWeight: 700, color: 'var(--fg)' }}>How to read:</span>
      <span className="lg"><span className="ai-ink"><ProvMark kind="ai" /></span> <b>AI-generated</b> — di2 narrative</span>
      <span className="lg"><span className="cp-ink"><ProvMark kind="computed" /></span> <b>Computed</b> — deterministic pipeline</span>
      <span className="lg"><span className="src-ink"><ProvMark kind="source" /></span> <b>Source</b> — measured data &amp; literature</span>
    </div>
  );
}
