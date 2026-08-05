/**
 * ui/controls.tsx — shared WashU-skinned form primitives.
 *
 * These replace the inline-styled chip / segmented-control / toggle patterns
 * that were duplicated across UploadPage and GeneDrawer. Selected/interactive
 * state uses the WashU teal accent; the hero red is reserved for primary CTAs.
 * All values come from CSS custom properties in styles/reticle.css.
 */

import type { CSSProperties, ReactNode } from 'react';
import Provenance, { type ProvKind } from '../washu/Provenance';

const TEAL = 'var(--teal)';
const TEAL_WASH = 'rgba(0,125,138,0.10)';

// ---------------------------------------------------------------------------
// Chip — a single toggle-able pill (used for single- and multi-select groups).
// ---------------------------------------------------------------------------
interface ChipProps {
  label: ReactNode;
  active: boolean;
  onClick: () => void;
  title?: string;
  disabled?: boolean;
}

export function Chip({ label, active, onClick, title, disabled }: ChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={disabled}
      aria-pressed={active}
      style={{
        padding: '6px 13px',
        borderRadius: 7,
        fontSize: '0.82rem',
        fontWeight: active ? 600 : 400,
        background: active ? TEAL_WASH : 'var(--white)',
        border: `1px solid ${active ? TEAL : 'var(--border)'}`,
        color: active ? 'var(--teal)' : 'var(--fg-muted)',
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'all 0.12s ease',
      }}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// ChipGroup — a labelled row of chips. `multi` toggles multi-select behavior.
// ---------------------------------------------------------------------------
interface ChipOption { value: string; label: ReactNode; hint?: string }
interface ChipGroupProps {
  options: ChipOption[];
  value: string | string[];
  onChange: (value: string) => void;
  multi?: boolean;
}

export function ChipGroup({ options, value, onChange, multi }: ChipGroupProps) {
  const isActive = (v: string) =>
    multi ? Array.isArray(value) && value.includes(v) : value === v;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {options.map(o => (
        <Chip
          key={o.value}
          label={o.label}
          title={o.hint}
          active={isActive(o.value)}
          onClick={() => onChange(o.value)}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toggle — an on/off switch.
// ---------------------------------------------------------------------------
interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  id?: string;
}

export function Toggle({ checked, onChange, label, id }: ToggleProps) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      style={{
        width: 40, height: 22, borderRadius: 11, flexShrink: 0,
        background: checked ? TEAL : 'var(--bg-3)',
        border: `1px solid ${checked ? TEAL : 'var(--border)'}`,
        position: 'relative', transition: 'all 0.2s',
      }}
    >
      <span style={{
        display: 'block', width: 16, height: 16, borderRadius: '50%',
        background: 'white', position: 'absolute', top: 2,
        left: checked ? 20 : 2, transition: 'left 0.2s',
        boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
      }} />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Field — label + optional hint + optional provenance mark, wrapping a control.
// ---------------------------------------------------------------------------
interface FieldProps {
  label: string;
  hint?: string;
  /** Provenance mark shown to the right of the label (auto-detected vs entered). */
  prov?: { kind: ProvKind; label: string };
  children: ReactNode;
  style?: CSSProperties;
}

export function Field({ label, hint, prov, children, style }: FieldProps) {
  return (
    <div style={style}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 7,
        justifyContent: 'space-between',
      }}>
        <label style={{
          fontSize: '0.72rem', fontWeight: 700, color: 'var(--faint)',
          textTransform: 'uppercase', letterSpacing: '0.07em',
        }}>{label}</label>
        {prov && <Provenance kind={prov.kind} label={prov.label} />}
      </div>
      {children}
      {hint && (
        <div style={{ fontSize: '0.73rem', color: 'var(--faint)', marginTop: 5 }}>{hint}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Combobox — a text input with datalist suggestions (cell line, library, …).
// Accepts free text; the suggestions are just a shortcut.
// ---------------------------------------------------------------------------
interface ComboboxProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label?: string }[];
  placeholder?: string;
  listId: string;
}

export function Combobox({ value, onChange, options, placeholder, listId }: ComboboxProps) {
  return (
    <>
      <input
        type="text"
        value={value}
        list={listId}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        style={inputStyle}
      />
      <datalist id={listId}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label ?? o.value}</option>)}
      </datalist>
    </>
  );
}

// ---------------------------------------------------------------------------
// Select — a native select styled to the system.
// ---------------------------------------------------------------------------
interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  ariaLabel?: string;
}

export function Select({ value, onChange, options, ariaLabel }: SelectProps) {
  return (
    <select
      value={value}
      aria-label={ariaLabel}
      onChange={e => onChange(e.target.value)}
      style={{ ...inputStyle, cursor: 'pointer' }}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

// ---------------------------------------------------------------------------
// NumberInput — a plain number field with system styling.
// ---------------------------------------------------------------------------
interface NumberInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  min?: number;
  step?: number;
  ariaLabel?: string;
}

export function NumberInput({ value, onChange, placeholder, min, step, ariaLabel }: NumberInputProps) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      step={step}
      aria-label={ariaLabel}
      placeholder={placeholder}
      onChange={e => onChange(e.target.value)}
      style={inputStyle}
    />
  );
}

export const inputStyle: CSSProperties = {
  width: '100%',
  padding: '8px 11px',
  background: 'var(--white)',
  border: '1px solid var(--border)',
  borderRadius: 7,
  color: 'var(--fg)',
  fontSize: '0.85rem',
  fontFamily: 'inherit',
  outline: 'none',
};
