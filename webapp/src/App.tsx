/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useCallback, useEffect, type ReactNode } from 'react';
// LandingPage is no longer routed — see the 'landing' branch below for why it is still here.
import HomeLanding_aaron from './components/landing_aaron/HomeLanding_aaron';
import LoginLanding from './components/LoginLanding';
import UploadPage from './components/UploadPage';
import LoadingAnalysis from './components/LoadingAnalysis';
import DashboardView from './components/shell/DashboardView';
import ExplorerPage from './components/explorer/ExplorerPage';
import ReticlePage_aaron from './components/reticle_aaron/ReticlePage_aaron';
import MarketingLanding_aaron from './components/landing_aaron/MarketingLanding_aaron';
import StickyControls from './components/StickyControls';
import type { QueryResponse } from './services/reticleApi';
import { initAuth, type User } from './services/auth';

// Local-dev escape hatch: preview the UI without WashU SSO. Engages ONLY in a
// non-production build with REACT_APP_DEV_NO_AUTH="true" (see webpack DefinePlugin),
// so it can never weaken auth in a deployed bundle.
const DEV_NO_AUTH =
  process.env.NODE_ENV !== 'production' && process.env.REACT_APP_DEV_NO_AUTH === 'true';

export default function App() {
  // ── Auth gate ──────────────────────────────────────────────────────────
  const [authState, setAuthState] = useState<'loading' | 'in' | 'out'>('loading');
  const [, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (DEV_NO_AUTH) {
      setUser({ oid: 'dev', name: 'Dev User', email: 'dev@wustl.edu', tenant: 'dev' });
      setAuthState('in');
      return;
    }
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

  // Which of the vendored tabs to open, and on which gene. The home page's search box hands both
  // over so a user types a symbol once, not once to get in and again on arrival.
  const [reticleTab, setReticleTab] = useState<'gene' | 'screen' | 'network'>('gene');
  const [reticleGene, setReticleGene] = useState<string | undefined>(undefined);
  const [reticleOrg, setReticleOrg] = useState<'human' | 'mouse' | undefined>(undefined);

  const handleStart = () => setScreen('upload');
  const handleExplore = () => setScreen('explorer');
  const openReticle = (
    tab: 'gene' | 'screen' | 'network',
    gene?: string,
    organism?: 'human' | 'mouse',
  ) => {
    setReticleTab(tab);
    setReticleGene(gene);
    setReticleOrg(organism);
    setScreen('wiki');
  };

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
        {/* Returns to the marketing page. It lives here rather than inside LoginLanding because it
            is about where the HOST put that card, not about signing in. Styled to the same paper
            palette the card now uses — the dark-theme vars it used to read render as pale grey on
            white and made it all but invisible. */}
        <button
          onClick={() => setWantsLogin(false)}
          style={{
            position: 'fixed', top: 20, left: 20, zIndex: 20,
            padding: '8px 15px', borderRadius: 9,
            border: '1px solid #E8E6E1', background: '#FFFFFF', color: '#6B7280',
            fontFamily: '"IBM Plex Sans", system-ui, sans-serif',
            fontSize: '12.5px', fontWeight: 500, cursor: 'pointer',
          }}
        >← Back</button>
      </>
    );
  }

  let screenEl: ReactNode = null;
  if (screen === 'landing') {
    // components/LandingPage.jsx is NO LONGER ROUTED — it is left on disk untouched rather than
    // deleted, because it is being reworked on feature/50-ui-unification-brainstorm and removing
    // it here would hand that branch a conflict for nothing. If that rework lands and is preferred,
    // point this line back at it.
    screenEl = (
      <HomeLanding_aaron
        onOpenGene={(gene, organism) => openReticle('gene', gene, organism)}
        onOpenScreen={(screenId) => openReticle('screen', screenId)}
        onStart={handleStart}
        onExplore={handleExplore}
      />
    );
  } else if (screen === 'explorer') {
    screenEl = <ExplorerPage onBack={handleHome} />;
  } else if (screen === 'wiki') {
    screenEl = (
      <ReticlePage_aaron
        onBack={handleHome}
        initial={reticleTab}
        gene={reticleGene}
        organism={reticleOrg}
      />
    );
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
      <DashboardView
        genes={genes}
        options={analysisOptions}
        queryResults={queryResults}
        onNewAnalysis={handleReset}
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
