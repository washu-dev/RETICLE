import { Home, LogOut } from 'lucide-react';
import { logout } from '../services/auth';

/**
 * Persistent, always-visible utility controls. Rendered by App on top of every
 * authenticated screen (fixed bottom-right so it never collides with a screen's
 * own top nav). Home returns to the main page; Logout ends the SSO session.
 */
export default function StickyControls({ showHome = true, onHome }) {
  const pill = {
    display: 'flex', alignItems: 'center', gap: 7,
    padding: '9px 15px', borderRadius: 10,
    border: '1px solid var(--border)',
    background: 'rgba(11,17,32,0.85)', backdropFilter: 'blur(12px)',
    color: 'var(--text-1)', fontSize: '0.85rem', fontWeight: 600,
    boxShadow: '0 4px 16px rgba(0,0,0,0.35)', cursor: 'pointer',
  };

  return (
    <div style={{
      position: 'fixed', bottom: 20, right: 20, zIndex: 1000,
      display: 'flex', gap: 10,
    }}>
      {showHome && (
        <button onClick={onHome} title="Back to main page" style={pill}>
          <Home size={15} /> Home
        </button>
      )}
      <button
        onClick={logout}
        title="Sign out"
        style={{ ...pill, color: 'var(--text-2)' }}
      >
        <LogOut size={15} /> Logout
      </button>
    </div>
  );
}
