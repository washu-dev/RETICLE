import { useState, useCallback } from 'react';
import LandingPage from './components/LandingPage';
import UploadPage from './components/UploadPage';
import LoadingAnalysis from './components/LoadingAnalysis';
import ResultsPage from './components/ResultsPage';

export default function App() {
  const [screen, setScreen] = useState('landing');
  const [genes, setGenes] = useState(null);

  const handleStart   = () => setScreen('upload');
  const handleAnalyze = (parsedGenes) => { setGenes(parsedGenes); setScreen('loading'); };
  const handleDone    = useCallback(() => setScreen('results'), []);
  const handleReset   = () => { setGenes(null); setScreen('upload'); };

  if (screen === 'landing') return <LandingPage onStart={handleStart} />;
  if (screen === 'upload')  return <UploadPage onAnalyze={handleAnalyze} />;
  if (screen === 'loading') return <LoadingAnalysis geneCount={genes?.length ?? 25} onDone={handleDone} />;
  if (screen === 'results') return <ResultsPage genes={genes} onReset={handleReset} />;
  return null;
}
