import { useState } from 'react';
import { FlaskConical, LogIn } from 'lucide-react';
import { startLogin } from '../services/auth';

export default function LoginLanding() {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

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
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24,
      background: 'radial-gradient(ellipse 70% 55% at 50% 0%, rgba(37,99,184,0.18) 0%, transparent 70%)',
    }}>
      <div className="card" style={{
        width: '100%', maxWidth: 420, textAlign: 'center',
        padding: '40px 32px', display: 'flex', flexDirection: 'column', alignItems: 'center',
      }}>
        {/* Logo */}
        <div style={{
          width: 52, height: 52, borderRadius: 12,
          background: 'linear-gradient(135deg, #2563b8, #4f9cf9)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 20,
        }}>
          <FlaskConical size={26} color="white" />
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
          <span style={{ fontWeight: 800, fontSize: '1.6rem', letterSpacing: '-0.03em' }}>RETICLE</span>
          <span style={{ color: 'var(--text-3)', fontSize: '0.85rem' }}>beta</span>
        </div>

        <p style={{ color: 'var(--text-2)', fontSize: '0.95rem', lineHeight: 1.6, marginBottom: 28 }}>
          Rationale Engine To Inform CRISPR List Entities.
          <br />Sign in with your WashU account to continue.
        </p>

        {error && (
          <div role="alert" style={{
            width: '100%', marginBottom: 18, padding: '10px 14px', borderRadius: 8,
            border: '1px solid rgba(229,72,77,0.35)', background: 'rgba(229,72,77,0.1)',
            color: '#f0a3a6', fontSize: '0.85rem', lineHeight: 1.5,
          }}>{error}</div>
        )}

        <button
          onClick={handleLogin}
          disabled={busy}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
            padding: '14px 24px', borderRadius: 10,
            background: 'linear-gradient(135deg, #2563b8, #4f9cf9)',
            color: 'white', fontSize: '1rem', fontWeight: 600,
            opacity: busy ? 0.7 : 1, cursor: busy ? 'default' : 'pointer',
            boxShadow: '0 4px 20px rgba(79,156,249,0.35)',
            transition: 'transform 0.15s, box-shadow 0.15s',
          }}
          onMouseEnter={e => { if (!busy) { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 28px rgba(79,156,249,0.45)'; } }}
          onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '0 4px 20px rgba(79,156,249,0.35)'; }}
        >
          <LogIn size={18} /> {busy ? 'Redirecting…' : 'Login'}
        </button>

        <p style={{ color: 'var(--text-3)', fontSize: '0.75rem', marginTop: 20 }}>
          WashU DI² · Weidenbaum / IFNγ Macrophage Program
        </p>
      </div>
    </div>
  );
}
