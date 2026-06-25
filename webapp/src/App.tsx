/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useCallback } from 'react';
import LandingPage from './components/LandingPage';
import UploadPage from './components/UploadPage';
import LoadingAnalysis from './components/LoadingAnalysis';
import ResultsPage from './components/ResultsPage';
import type { QueryResponse } from './services/reticleApi';

export default function App() {
  const [screen, setScreen] = useState('landing');
  const [genes, setGenes] = useState<any>(null);
  const [analysisOptions, setAnalysisOptions] = useState<any>(null);
  const [queryResults, setQueryResults] = useState<QueryResponse | null>(null);

  const handleStart = () => setScreen('upload');

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

  if (screen === 'landing') return <LandingPage onStart={handleStart} />;
  if (screen === 'upload')  return <UploadPage onAnalyze={handleAnalyze} />;
  if (screen === 'loading') return (
    <LoadingAnalysis
      geneCount={genes?.length ?? 25}
      genes={genes}
      options={analysisOptions}
      onDone={handleDone}
    />
  );
  if (screen === 'results') return (
    <ResultsPage
      genes={genes}
      options={analysisOptions}
      queryResults={queryResults}
      onReset={handleReset}
    />
  );
  return null;
}
