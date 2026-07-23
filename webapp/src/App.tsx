/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useCallback, useEffect, type ReactNode } from 'react';
import LandingPage from './components/LandingPage';
import LoginLanding from './components/LoginLanding';
import UploadPage from './components/UploadPage';
import LoadingAnalysis from './components/LoadingAnalysis';
import ResultsPage from './components/ResultsPage';
import ExplorerPage from './components/explorer/ExplorerPage';
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

  const [screen, setScreen] = useState('landing');
  const [genes, setGenes] = useState<any>(null);
  const [analysisOptions, setAnalysisOptions] = useState<any>(null);
  const [queryResults, setQueryResults] = useState<QueryResponse | null>(null);

  const handleStart = () => setScreen('upload');
  const handleExplore = () => setScreen('explorer');

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

  // Not signed in → the SSO login landing page (single "Login" button).
  if (authState === 'out') return <LoginLanding />;

  let screenEl: ReactNode = null;
  if (screen === 'landing') {
    screenEl = <LandingPage onStart={handleStart} onExplore={handleExplore} />;
  } else if (screen === 'explorer') {
    screenEl = <ExplorerPage onBack={handleHome} />;
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
