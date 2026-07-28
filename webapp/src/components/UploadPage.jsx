import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import {
  Upload, FileText, ArrowRight, CheckCircle2, AlertCircle,
  ChevronDown, ChevronUp, Lock, Sparkles,
} from 'lucide-react';
import WashuLogo from './washu/WashuLogo';
import Provenance from './washu/Provenance';
import { EXAMPLE_GENE_LIST } from '../mockData';
import {
  detectFormat, suggestScoreColumn, parseGeneList, resolveIdentifiers,
  deriveScreenSignals, directionLabel,
} from '../utils/geneParser';
import crosswalk from '../data/crosswalk.min.json';
import {
  MODALITY, SELECTION_METHOD, ASSAY_DOMAIN, COVERAGE_SCOPE, ORGANISM,
  LIBRARY, COMPARISON_DIRECTION, HIT_THRESHOLD_TYPE, CELL_TYPE, ALGORITHM,
  FORMAT_TO_ALGORITHM,
} from '../data/screenVocab';
import {
  ChipGroup, Field, Combobox, Select, NumberInput,
} from './ui/controls';
import { fetchCorpusCount } from '../services/reticleApi';

const FORMAT_HINT = `Paste a ranked gene list — CSV or TSV with a header row.

Recognized formats:
  MAGeCK gene summary   (id, neg|lfc, neg|score, …)
  STARS output          (Gene, LFC, q-value, Rank)
  DESeq2 results        (gene, baseMean, log2FoldChange, padj)
  BioGRID ORCS export   (#…OFFICIAL_SYMBOL, SCORE.1…, HIT)
  Residual / z-score    (Gene, mean_lfc, z_score, fdr, ranks)
  Simple 2-column       (gene_symbol, score)`;

const FORMAT_LABELS = {
  MAGECK: 'MAGeCK gene summary',
  STARS: 'STARS output',
  DESEQ2: 'DESeq2 results',
  ORCS: 'BioGRID ORCS export',
  RESIDUAL: 'Residual / z-score screen',
  SIMPLE: 'Simple CSV/TSV',
  UNKNOWN: 'Unrecognized format',
};

const DEFAULT_CONTEXT = {
  modality: '', organism: '', selectionMethod: '', coverageScope: '',
  coverageAvailability: '', assayDomain: '', cellLine: '', cellType: '',
  library: '', condition: '', concentration: '', timepoint: '',
  timepointUnit: 'hours', nReplicates: '', comparisonDirection: '',
  hitThresholdType: '', hitThresholdValue: '', direction: '',
  algorithm: '', scoreColumn: '', fileFormat: '',
};

const DEFAULT_CORPUS = {
  organism: 'Any',
  assayDomains: ASSAY_DOMAIN.map(d => d.value),  // all → no-op default (full corpus)
  coverage: 'Any',
  cellTypes: [],
  modalities: [],
  minSharedGenes: 0,
};

const LABEL_CSS = {
  fontSize: '0.72rem', fontWeight: 700, color: 'var(--faint)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
};

export default function UploadPage({ onAnalyze }) {
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState('');
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState('');

  // Parse state
  const [detected, setDetected] = useState(null);
  const [idColumn, setIdColumn] = useState('');
  const [scoreColumn, setScoreColumn] = useState('');
  const [hitColumn, setHitColumn] = useState('');
  const [scoreCands, setScoreCands] = useState([]);
  const [mappingOpen, setMappingOpen] = useState(false);

  // Describe-your-screen state
  const [context, setContext] = useState(DEFAULT_CONTEXT);
  const [edited, setEdited] = useState(() => new Set());
  const [autoFilled, setAutoFilled] = useState(() => new Set());
  const [detailOpen, setDetailOpen] = useState(false);

  // Compare-to state
  const [corpus, setCorpus] = useState(DEFAULT_CORPUS);
  const [corpusCount, setCorpusCount] = useState(null);
  const [corpusLoading, setCorpusLoading] = useState(false);

  const fileRef = useRef();
  const detectTimer = useRef(null);

  // ── Detection (debounced) ────────────────────────────────────────────────
  const runDetect = useCallback((raw) => {
    if (!raw.trim()) {
      setDetected(null); setIdColumn(''); setScoreColumn(''); setHitColumn(''); setScoreCands([]);
      return;
    }
    const det = detectFormat(raw);
    setDetected(det);
    setIdColumn(det.idColumn || '');
    setHitColumn(det.hitColumn || '');
    const { defaultColumn, candidates } = suggestScoreColumn(det.columns, det.format);
    setScoreColumn(defaultColumn);
    setScoreCands(candidates);
  }, []);

  useEffect(() => {
    clearTimeout(detectTimer.current);
    detectTimer.current = setTimeout(() => runDetect(text), 200);
    return () => clearTimeout(detectTimer.current);
  }, [text, runDetect]);

  // ── Parse + derive signals ───────────────────────────────────────────────
  const parseResult = useMemo(() => {
    if (!text.trim() || !detected) return { genes: [], warnings: [] };
    return parseGeneList(text, {
      format: detected.format, delimiter: detected.delimiter,
      idColumn, scoreColumn, hitColumn,
    });
  }, [text, detected, idColumn, scoreColumn, hitColumn]);

  const signals = useMemo(
    () => (detected ? deriveScreenSignals(detected, parseResult.genes) : null),
    [detected, parseResult.genes]
  );

  const parsedCount = parseResult.genes.length;
  const hasScreen = Boolean(detected && parsedCount > 0);

  // ── Auto-fill the describe form from detected signals ────────────────────
  useEffect(() => {
    if (!signals || !detected) return;
    const auto = {
      organism: signals.organism || '',
      coverageAvailability: signals.coverageAvailability || '',
      direction: signals.direction || '',
      condition: signals.condition || '',
      algorithm: FORMAT_TO_ALGORITHM[detected.format] || '',
      scoreColumn,
      fileFormat: detected.format,
    };
    setContext(prev => {
      const next = { ...prev };
      for (const [k, v] of Object.entries(auto)) {
        if (v && !edited.has(k)) next[k] = v;
      }
      return next;
    });
    setAutoFilled(new Set(Object.entries(auto).filter(([, v]) => v).map(([k]) => k)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signals, detected, scoreColumn]);

  // ── Live corpus count (debounced) ────────────────────────────────────────
  useEffect(() => {
    const controller = new AbortController();
    setCorpusLoading(true);
    const t = setTimeout(() => {
      fetchCorpusCount(corpus, controller.signal)
        .then(n => { setCorpusCount(n); setCorpusLoading(false); })
        .catch(() => { setCorpusLoading(false); });
    }, 250);
    return () => { clearTimeout(t); controller.abort(); };
  }, [corpus]);

  // ── Field setters ────────────────────────────────────────────────────────
  function setField(field, value) {
    setContext(prev => ({ ...prev, [field]: value }));
    setEdited(prev => new Set(prev).add(field));
  }
  function prov(field) {
    if (edited.has(field)) return { kind: 'source', label: 'You entered' };
    if (autoFilled.has(field) && context[field]) return { kind: 'computed', label: 'Auto-detected' };
    return undefined;
  }
  function setCorpusField(field, value) {
    setCorpus(prev => ({ ...prev, [field]: value }));
  }
  function toggleCorpusList(field, value) {
    setCorpus(prev => {
      const list = prev[field];
      return { ...prev, [field]: list.includes(value) ? list.filter(x => x !== value) : [...list, value] };
    });
  }
  function useRecommendedPool() {
    setCorpus({
      ...DEFAULT_CORPUS,
      organism: context.organism || 'Human',
      assayDomains: ['fitness'],
      coverage: 'FULL',
    });
  }

  // ── Input handlers ───────────────────────────────────────────────────────
  function loadExample() {
    setText(EXAMPLE_GENE_LIST);
    setFileName('EXAMPLE_GENE_LIST');
    setError('');
  }
  function handleFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => { setText(e.target.result); setFileName(file.name); setError(''); };
    reader.readAsText(file);
  }
  function clearScreen() {
    setText(''); setFileName(''); setError('');
    setContext(DEFAULT_CONTEXT); setEdited(new Set()); setAutoFilled(new Set());
  }

  // ── Submit ───────────────────────────────────────────────────────────────
  function handleSubmit() {
    if (!text.trim()) { setError('Paste a gene list or upload a file to start.'); return; }
    const det = detectFormat(text);
    const effectiveScore = scoreColumn || suggestScoreColumn(det.columns, det.format).defaultColumn;
    const { genes, warnings } = parseGeneList(text, {
      format: det.format, delimiter: det.delimiter,
      idColumn: idColumn || det.idColumn, scoreColumn: effectiveScore, hitColumn,
    });
    if (genes.length < 5) {
      setError(`RETICLE needs at least 5 genes to compare. ${warnings[0] ?? ''}`);
      return;
    }
    const resolveOrganism = context.organism === 'Mouse' ? 'Mouse' : 'Human';
    const { genes: resolved } = resolveIdentifiers(genes, resolveOrganism, crosswalk);
    setError('');

    const screenContext = {
      ...context,
      scoreColumn: effectiveScore,
      fileFormat: det.format,
      nReplicates: context.nReplicates ? Number(context.nReplicates) : undefined,
      hitThresholdValue: context.hitThresholdValue ? Number(context.hitThresholdValue) : undefined,
    };

    onAnalyze(resolved, {
      algorithm: context.algorithm || 'MAGeCK LFC',
      organism: context.organism || 'Both',
      modalities: context.modality ? [context.modality] : ['KO', 'CRISPRa'],
      pathwayAnalysis: false,
      format: det.format,
      scoreColumn: effectiveScore,
      screenContext,
      corpusFilters: corpus,
    });
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--warm-gray)' }}>
      <Nav />

      <div style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: '48px 40px 96px' }}>
        <div style={{ width: '100%', maxWidth: 860 }}>

          {/* Hero */}
          <div className="eyebrow" style={{ marginBottom: 10 }}>Screen input</div>
          <h2 style={{ fontSize: '2rem', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.1, marginBottom: 8 }}>
            Bring your screen — see what the corpus <span className="emph" style={{ color: 'var(--washu-red)' }}>already knows</span>.
          </h2>
          <p style={{ color: 'var(--fg-muted)', marginBottom: 28, fontSize: '0.98rem', maxWidth: 620 }}>
            Drop a ranked screen or paste a few favorite genes. RETICLE reads the file, confirms what it
            found, and compares it against published WashU screens.
          </p>

          {/* ── Section: Input ── */}
          <Section n={1} title="Your screen">
            <div
              className={`upload-zone${isDragOver ? ' drag-over' : ''}`}
              onClick={() => (text ? null : fileRef.current?.click())}
              onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={e => { e.preventDefault(); setIsDragOver(false); handleFile(e.dataTransfer.files[0]); }}
              style={{ marginBottom: 14, cursor: text ? 'default' : 'pointer', background: 'var(--white)' }}
            >
              {text ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'center' }}>
                  <CheckCircle2 size={20} color="var(--green-washu)" />
                  <span style={{ color: 'var(--green-washu)', fontWeight: 600 }}>
                    {fileName || 'Pasted list'} — {parsedCount} genes read
                  </span>
                  <button onClick={e => { e.stopPropagation(); clearScreen(); }}
                    style={{ color: 'var(--faint)', fontSize: '0.8rem', textDecoration: 'underline' }}>
                    clear
                  </button>
                </div>
              ) : (
                <>
                  <Upload size={26} color="var(--faint)" style={{ marginBottom: 10 }} />
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>Drop a screen file (.csv / .tsv / .txt)</div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--faint)' }}>or click to browse — MAGeCK, STARS, DESeq2, BioGRID ORCS, or a simple list</div>
                </>
              )}
            </div>
            <input ref={fileRef} type="file" accept=".csv,.tsv,.txt" style={{ display: 'none' }}
              onChange={e => handleFile(e.target.files[0])} />

            <textarea
              value={text}
              onChange={e => { setText(e.target.value); setError(''); }}
              placeholder={FORMAT_HINT}
              rows={text ? 5 : 9}
              style={{
                width: '100%', resize: 'vertical', padding: '13px 15px',
                background: 'var(--white)', border: '1px solid var(--border)',
                borderRadius: 9, color: 'var(--fg)', fontSize: '0.85rem',
                fontFamily: 'var(--font-mono)', outline: 'none', lineHeight: 1.6,
              }}
              onFocus={e => (e.target.style.borderColor = 'var(--teal)')}
              onBlur={e => (e.target.style.borderColor = 'var(--border)')}
            />

            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
              <button onClick={loadExample}
                style={{
                  display: 'flex', alignItems: 'center', gap: 7, padding: '8px 14px', borderRadius: 8,
                  border: '1px solid var(--border)', color: 'var(--fg-muted)', fontSize: '0.85rem', background: 'var(--white)',
                }}>
                <FileText size={15} /> Load example (Orvedahl screen)
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--faint)', fontSize: '0.8rem' }}>
                <Lock size={13} /> Unpublished screens stay on your WashU session unless you contribute them.
              </div>
            </div>
          </Section>

          {/* ── Section: Parse-confirm receipt (the signature) ── */}
          {hasScreen && (
            <Section n={2} title="What we read">
              <div style={{
                background: 'var(--white)', border: '1px solid var(--border)',
                borderTop: '3px solid var(--washu-red)', borderRadius: '3px 3px 10px 10px',
                padding: '20px 22px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--fg)' }}>
                    {fileName || 'Pasted gene list'}
                  </div>
                  <Provenance kind="computed" label="Auto-detected" />
                </div>

                <div style={{
                  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                  gap: '14px 24px', marginTop: 16,
                }}>
                  <Fact label="Genes read" value={parsedCount.toLocaleString()} />
                  <Fact label="Format" value={FORMAT_LABELS[detected.format] ?? detected.format} />
                  <Fact label="Organism" value={signals?.organism ?? 'not stated — set below'} />
                  <Fact label="Direction" value={directionLabel(signals?.direction)} />
                  <Fact label="Score column" value={scoreColumn || '—'} />
                  <Fact label="Coverage"
                    value={signals?.coverageAvailability === 'HITS_ONLY' ? 'Hits only' : 'Every gene scored'} />
                  {signals?.hitCount != null && <Fact label="Hits flagged" value={signals.hitCount.toLocaleString()} />}
                  {signals?.condition && <Fact label="Condition" value={signals.condition} />}
                </div>

                {detected.format === 'UNKNOWN' && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 14, color: 'var(--washu-red)', fontSize: '0.83rem' }}>
                    <AlertCircle size={15} /> We couldn't confidently match this format — check the column mapping below.
                  </div>
                )}

                {/* Fix column mapping */}
                <button onClick={() => setMappingOpen(o => !o)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6, marginTop: 16,
                    fontSize: '0.82rem', color: 'var(--teal)', fontWeight: 600,
                  }}>
                  {mappingOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />} Fix column mapping
                </button>
                {mappingOpen && (
                  <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14,
                    marginTop: 12, paddingTop: 14, borderTop: '1px solid var(--border)',
                  }}>
                    <Field label="Gene / ID column">
                      <Select value={idColumn} onChange={setIdColumn} ariaLabel="ID column"
                        options={detected.columns.map(c => ({ value: c, label: c }))} />
                    </Field>
                    <Field label="Score column">
                      <Select value={scoreColumn} onChange={setScoreColumn} ariaLabel="Score column"
                        options={(scoreCands.length ? scoreCands : detected.columns.map(c => ({ value: c, label: c })))} />
                    </Field>
                    <Field label="Hit column (optional)">
                      <Select value={hitColumn} onChange={setHitColumn} ariaLabel="Hit column"
                        options={[{ value: '', label: 'None' }, ...detected.columns.map(c => ({ value: c, label: c }))]} />
                    </Field>
                  </div>
                )}
              </div>
            </Section>
          )}

          {/* ── Section: Describe your screen ── */}
          {hasScreen && (
            <Section n={3} title="Describe your screen"
              subtitle="Auto-detected where we could — correct anything that's wrong. This is how the corpus is keyed.">
              <Card>
                <Grid>
                  <Field label="Modality" prov={prov('modality')}>
                    <ChipGroup options={MODALITY} value={context.modality} onChange={v => setField('modality', v)} />
                  </Field>
                  <Field label="Organism" prov={prov('organism')}>
                    <ChipGroup options={ORGANISM} value={context.organism} onChange={v => setField('organism', v)} />
                  </Field>
                </Grid>
                <Grid>
                  <Field label="Selection" prov={prov('selectionMethod')}>
                    <ChipGroup options={SELECTION_METHOD} value={context.selectionMethod} onChange={v => setField('selectionMethod', v)} />
                  </Field>
                  <Field label="Assay domain" hint="Governs which corpus screens are comparable." prov={prov('assayDomain')}>
                    <ChipGroup options={ASSAY_DOMAIN} value={context.assayDomain} onChange={v => setField('assayDomain', v)} />
                  </Field>
                </Grid>
                <Field label="Library coverage" prov={prov('coverageScope')}>
                  <ChipGroup options={COVERAGE_SCOPE} value={context.coverageScope} onChange={v => setField('coverageScope', v)} />
                </Field>

                <button onClick={() => setDetailOpen(o => !o)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6, marginTop: 4,
                    fontSize: '0.82rem', color: 'var(--teal)', fontWeight: 600,
                  }}>
                  {detailOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />} Add more detail
                </button>

                {detailOpen && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 18, paddingTop: 4 }}>
                    <Grid>
                      <Field label="Cell line" prov={prov('cellLine')}>
                        <Combobox listId="celllines" value={context.cellLine} onChange={v => setField('cellLine', v)}
                          placeholder="e.g. THP-1, HeLa, BV-2" options={[]} />
                      </Field>
                      <Field label="Cell type" prov={prov('cellType')}>
                        <Combobox listId="celltypes" value={context.cellType} onChange={v => setField('cellType', v)}
                          placeholder="e.g. macrophage" options={CELL_TYPE} />
                      </Field>
                    </Grid>
                    <Grid>
                      <Field label="Library" prov={prov('library')}>
                        <Combobox listId="libraries" value={context.library} onChange={v => setField('library', v)}
                          placeholder="e.g. Brunello" options={LIBRARY} />
                      </Field>
                      <Field label="Scoring algorithm" prov={prov('algorithm')}>
                        <Select value={context.algorithm} onChange={v => setField('algorithm', v)} ariaLabel="Algorithm"
                          options={[{ value: '', label: '—' }, ...ALGORITHM.map(a => ({ value: a.value, label: a.label }))]} />
                      </Field>
                    </Grid>
                    <Grid>
                      <Field label="Treatment / condition" prov={prov('condition')}>
                        <Combobox listId="conditions" value={context.condition} onChange={v => setField('condition', v)}
                          placeholder="e.g. IFNγ + TNF" options={[]} />
                      </Field>
                      <Field label="Concentration" prov={prov('concentration')}>
                        <Combobox listId="conc" value={context.concentration} onChange={v => setField('concentration', v)}
                          placeholder="e.g. 10 ng/ml" options={[]} />
                      </Field>
                    </Grid>
                    <Grid>
                      <Field label="Timepoint" prov={prov('timepoint')}>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <NumberInput value={context.timepoint} onChange={v => setField('timepoint', v)} min={0} ariaLabel="Timepoint" />
                          <Select value={context.timepointUnit} onChange={v => setField('timepointUnit', v)} ariaLabel="Timepoint unit"
                            options={[{ value: 'hours', label: 'hours' }, { value: 'days', label: 'days' }]} />
                        </div>
                      </Field>
                      <Field label="Replicates" prov={prov('nReplicates')}>
                        <NumberInput value={context.nReplicates} onChange={v => setField('nReplicates', v)} min={1} ariaLabel="Replicates" />
                      </Field>
                    </Grid>
                    <Grid>
                      <Field label="Comparison direction" prov={prov('comparisonDirection')}>
                        <ChipGroup options={COMPARISON_DIRECTION} value={context.comparisonDirection}
                          onChange={v => setField('comparisonDirection', v)} />
                      </Field>
                      <Field label="Hit threshold" prov={prov('hitThresholdValue')}>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <Select value={context.hitThresholdType} onChange={v => setField('hitThresholdType', v)} ariaLabel="Hit threshold type"
                            options={[{ value: '', label: 'type' }, ...HIT_THRESHOLD_TYPE.map(h => ({ value: h.value, label: h.label }))]} />
                          <NumberInput value={context.hitThresholdValue} onChange={v => setField('hitThresholdValue', v)}
                            step={0.01} min={0} placeholder="0.10" ariaLabel="Hit threshold value" />
                        </div>
                      </Field>
                    </Grid>
                  </div>
                )}
              </Card>
            </Section>
          )}

          {/* ── Section: Compare against ── */}
          {hasScreen && (
            <Section n={4} title="Compare against"
              subtitle="Narrow the corpus to the screens worth comparing to. Defaults to everything.">
              <Card>
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  gap: 12, flexWrap: 'wrap', marginBottom: 4,
                }}>
                  <CohortCount count={corpusCount} loading={corpusLoading} filters={corpus} />
                  <button onClick={useRecommendedPool}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 7,
                      border: '1px solid var(--teal-line)', background: 'var(--teal-wash)', color: 'var(--teal)',
                      fontSize: '0.8rem', fontWeight: 600,
                    }}>
                    <Sparkles size={13} /> Use recommended pool
                  </button>
                </div>

                <Grid>
                  <Field label="Organism">
                    <ChipGroup value={corpus.organism} onChange={v => setCorpusField('organism', v)}
                      options={[{ value: 'Any', label: 'Any' }, ...ORGANISM]} />
                  </Field>
                  <Field label="Coverage">
                    <ChipGroup value={corpus.coverage} onChange={v => setCorpusField('coverage', v)}
                      options={[{ value: 'Any', label: 'Any' }, { value: 'FULL', label: 'Genome-wide (full)' }]} />
                  </Field>
                </Grid>
                <Field label="Assay domain" hint="Comparisons are most reliable within the same domain.">
                  <ChipGroup multi options={ASSAY_DOMAIN} value={corpus.assayDomains}
                    onChange={v => toggleCorpusList('assayDomains', v)} />
                </Field>
                <Grid>
                  <Field label="Modality">
                    <ChipGroup multi options={MODALITY} value={corpus.modalities}
                      onChange={v => toggleCorpusList('modalities', v)} />
                  </Field>
                  <Field label="Minimum shared genes" hint="Screens must share at least this many hits with yours.">
                    <NumberInput value={String(corpus.minSharedGenes || '')} min={0}
                      onChange={v => setCorpusField('minSharedGenes', Number(v) || 0)} ariaLabel="Minimum shared genes" />
                  </Field>
                </Grid>
              </Card>
            </Section>
          )}

          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 16, color: 'var(--washu-red)', fontSize: '0.88rem' }}>
              <AlertCircle size={16} /> {error}
            </div>
          )}

          {/* Primary action */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 28 }}>
            <button onClick={handleSubmit} disabled={!hasScreen}
              style={{
                display: 'flex', alignItems: 'center', gap: 9, padding: '13px 28px', borderRadius: 9,
                background: hasScreen ? 'var(--washu-red)' : 'var(--bg-3)',
                color: hasScreen ? 'white' : 'var(--faint)', fontSize: '0.95rem', fontWeight: 700,
                border: hasScreen ? '2px solid var(--washu-red)' : '1px solid var(--border)',
                transition: 'all 0.15s',
              }}>
              Compare to the corpus <ArrowRight size={17} />
            </button>
          </div>
        </div>
      </div>

      {/* Datalist for cell lines (kept outside the field so it survives collapse) */}
      <datalist id="celllines">
        {['THP-1', 'HeLa', 'BV-2', 'HEK293T', 'RAW264.7', 'J774A.1', 'NIH-3T3', 'K562', 'Jurkat'].map(c =>
          <option key={c} value={c} />)}
      </datalist>
    </div>
  );
}

// ── Small presentational helpers ───────────────────────────────────────────

function Nav() {
  return (
    <nav style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '11px 40px', borderTop: '3px solid var(--washu-red)',
      borderBottom: '1px solid var(--border)', background: 'var(--white)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <WashuLogo height={28} />
        <span style={{ fontWeight: 700, letterSpacing: '0.02em', paddingLeft: 16, borderLeft: '1px solid var(--border-2)' }}>
          RETI<span style={{ color: 'var(--washu-red)' }}>C</span>LE
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {['Describe', 'Compare', 'Results'].map((step, i) => (
          <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: i === 0 ? 'var(--washu-red)' : 'var(--warm-gray)',
              fontSize: '0.72rem', fontWeight: 700, color: i === 0 ? 'white' : 'var(--faint)',
              border: i === 0 ? 'none' : '1px solid var(--border)',
            }}>{i + 1}</div>
            <span style={{ fontSize: '0.875rem', color: i === 0 ? 'var(--fg)' : 'var(--faint)', fontWeight: i === 0 ? 600 : 400 }}>{step}</span>
            {i < 2 && <span style={{ color: 'var(--faint)', fontSize: '0.75rem' }}>›</span>}
          </div>
        ))}
      </div>
    </nav>
  );
}

function Section({ n, title, subtitle, children }) {
  return (
    <section style={{ marginTop: 28 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: '0.78rem', fontWeight: 700,
          color: 'var(--washu-red)', minWidth: 20,
        }}>{String(n).padStart(2, '0')}</span>
        <h3 style={{ fontSize: '1.05rem', fontWeight: 700, letterSpacing: '-0.01em' }}>{title}</h3>
      </div>
      {subtitle && (
        <p style={{ fontSize: '0.85rem', color: 'var(--fg-muted)', margin: '0 0 12px 30px' }}>{subtitle}</p>
      )}
      <div style={{ marginLeft: 30 }}>{children}</div>
    </section>
  );
}

function Card({ children }) {
  return (
    <div style={{
      background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 10,
      padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 18,
    }}>{children}</div>
  );
}

function Grid({ children }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '18px 24px' }}>
      {children}
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div>
      <div style={LABEL_CSS}>{label}</div>
      <div style={{ fontSize: '0.95rem', color: 'var(--fg)', marginTop: 3, fontWeight: 500 }}>{value}</div>
    </div>
  );
}

function CohortCount({ count, loading, filters }) {
  const parts = [];
  if (filters.organism !== 'Any') parts.push(filters.organism.toLowerCase());
  if (filters.coverage === 'FULL') parts.push('genome-wide');
  const nDomains = filters.assayDomains.length;
  if (nDomains > 0 && nDomains < ASSAY_DOMAIN.length) parts.push(filters.assayDomains.join(' / '));
  const desc = parts.length ? parts.join(' · ') + ' screens' : 'screens in the corpus';
  return (
    <div style={{ fontSize: '0.95rem', color: 'var(--fg)' }}>
      Comparing against{' '}
      <span style={{ fontWeight: 700, color: 'var(--washu-red)', fontFamily: 'var(--font-mono)' }}>
        {loading || count == null ? '…' : count.toLocaleString()}
      </span>{' '}
      <span style={{ color: 'var(--fg-muted)' }}>{desc}</span>
    </div>
  );
}
