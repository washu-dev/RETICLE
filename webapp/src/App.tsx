/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useCallback, useEffect, type ReactNode } from 'react';
import LandingPage from './components/LandingPage';
import LoginLanding from './components/LoginLanding';
import UploadPage from './components/UploadPage';
import LoadingAnalysis from './components/LoadingAnalysis';
import ResultsPage from './components/ResultsPage';
import ExplorerPage from './components/explorer/ExplorerPage';
import ReticlePage_aaron from './components/reticle_aaron/ReticlePage_aaron';
import MarketingLanding_aaron from './components/landing_aaron/MarketingLanding_aaron';
import StickyControls from './components/StickyControls';
import type { QueryResponse } from './services/reticleApi';
import { initAuth, type User } from './services/auth';

export default function App() {
  // ── Auth gate ──────────────────────────────────────────────────────────
  const [authState, setAuthState] = useState<'loading' | 'in' | 'out'>('loading');
  const [, setUser] = useState<User | null>(null);

  useEffect(() => {
    let cancelled = false;
    initAuth()
      .then((u) => {
        if (cancelled) return;
        setUser(u);
        setAuthState(u ? 'in' : 'out');
      })
      .catch(() => {
        if (!cancelled) setAuthState('out');
      });
    return () => { cancelled = true; };
  }, []);

  // Signed-out visitors get the public marketing page first and reach the SSO card from its CTA,
  // rather than being dropped straight onto a login prompt.
  const [wantsLogin, setWantsLogin] = useState(false);

  const [screen, setScreen] = useState('landing');
  const [genes, setGenes] = useState<any>(null);
  const [analysisOptions, setAnalysisOptions] = useState<any>(null);
  const [queryResults, setQueryResults] = useState<QueryResponse | null>(null);

  const handleStart = () => setScreen('upload');
  const handleExplore = () => setScreen('explorer');
  const handleWiki = () => setScreen('wiki');

  const handleAnalyze = (parsedGenes: any, options: any) => {
    setGenes(parsedGenes);
    setAnalysisOptions(options);
    setScreen('loading');
  };

  const handleDone = useCallback((results: QueryResponse | null) => {
    setQueryResults(results);
    setScreen('results');
  }, []);

  const handleReset = () => {
    setGenes(null);
    setAnalysisOptions(null);
    setQueryResults(null);
    setScreen('upload');
  };

  // Return to the main page from any sub-flow, clearing transient state.
  const handleHome = useCallback(() => {
    setGenes(null);
    setAnalysisOptions(null);
    setQueryResults(null);
    setScreen('landing');
  }, []);

  // While we check the session, render nothing distracting.
  if (authState === 'loading') {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--text-3)', fontSize: '0.9rem',
      }}>Loading…</div>
    );
  }

  // Not signed in → the public marketing page, then the SSO login card on request.
  if (authState === 'out') {
    if (!wantsLogin) return <MarketingLanding_aaron onSignIn={() => setWantsLogin(true)} />;
    return (
      <>
        <LoginLanding />
        {/* Rendered here rather than inside LoginLanding so that component stays untouched. */}
        <button
          onClick={() => setWantsLogin(false)}
          style={{
            position: 'fixed', top: 20, left: 20, zIndex: 20,
            padding: '8px 16px', borderRadius: 8,
            background: 'var(--bg-3)', color: 'var(--text-2)',
            fontSize: '0.85rem', fontWeight: 500,
          }}
        >← Back</button>
      </>
    );
  }

  let screenEl: ReactNode = null;
  if (screen === 'landing') {
    screenEl = <LandingPage onStart={handleStart} onExplore={handleExplore} onWiki={handleWiki} />;
  } else if (screen === 'explorer') {
    screenEl = <ExplorerPage onBack={handleHome} />;
  } else if (screen === 'wiki') {
    screenEl = <ReticlePage_aaron onBack={handleHome} />;
  } else if (screen === 'upload') {
    screenEl = <UploadPage onAnalyze={handleAnalyze} />;
  } else if (screen === 'loading') {
    screenEl = (
      <LoadingAnalysis
        geneCount={genes?.length ?? 25}
        genes={genes}
        options={analysisOptions}
        onDone={handleDone}
      />
    );
  } else if (screen === 'results') {
    screenEl = (
      <ResultsPage
        genes={genes}
        options={analysisOptions}
        queryResults={queryResults}
        onReset={handleReset}
      />
    );
  }

  // Home + Logout stay available on every authenticated screen. Home is hidden
  // on the main page (you're already there).
  return (
    <>
      {screenEl}
      <StickyControls showHome={screen !== 'landing'} onHome={handleHome} />
    </>
  );
}
