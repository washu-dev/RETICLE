import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Upload, FileText, ArrowRight, CheckCircle2, AlertCircle, FlaskConical, ChevronDown, ChevronUp, Settings2 } from 'lucide-react';
import { EXAMPLE_GENE_LIST } from '../mockData';
import { detectFormat, suggestScoreColumn, parseGeneList, resolveIdentifiers } from '../utils/geneParser';
import crosswalk from '../data/crosswalk.min.json';

const FORMAT_HINT = `Paste a ranked gene list — CSV or TSV with a header row.

Supported formats:
  MAGeCK gene summary  (id, neg|lfc, neg|score, ...)
  STARS output         (Gene, LFC, q-value, p-value, Rank)
  DESeq2 results       (gene, baseMean, log2FoldChange, padj)
  Simple 2-column      (gene_symbol, score)`;

const ALGORITHMS = ['MAGeCK LFC', 'STARS', 'DRUGz', 'DESeq2', 'Custom'];
const MODALITY_OPTIONS = ['KO', 'CRISPRa', 'CRISPRi'];

const FORMAT_LABELS = {
  MAGECK: 'MAGeCK gene summary',
  STARS: 'STARS output',
  DESEQ2: 'DESeq2 results',
  SIMPLE: 'Simple CSV/TSV',
  UNKNOWN: 'Unknown format',
};

export default function UploadPage({ onAnalyze }) {
  const [text, setText] = useState('');
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState('');
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [algorithm, setAlgorithm] = useState('MAGeCK LFC');
  const [organism, setOrganism] = useState('Both');
  const [modalities, setModalities] = useState(['KO', 'CRISPRa']);
  const [pathwayAnalysis, setPathwayAnalysis] = useState(false);

  const [detected, setDetected] = useState(null);
  const [scoreColumn, setScoreColumn] = useState('');
  const [scoreCands, setScoreCands] = useState([]);

  const fileRef = useRef();
  const detectTimer = useRef(null);

  const runDetect = useCallback((raw) => {
    if (!raw.trim()) { setDetected(null); setScoreColumn(''); setScoreCands([]); return; }
    const det = detectFormat(raw);
    setDetected(det);
    const { defaultColumn, candidates } = suggestScoreColumn(det.columns, det.format);
    setScoreColumn(defaultColumn);
    setScoreCands(candidates);
  }, []);

  useEffect(() => {
    clearTimeout(detectTimer.current);
    detectTimer.current = setTimeout(() => runDetect(text), 200);
    return () => clearTimeout(detectTimer.current);
  }, [text, runDetect]);

  const parsedCount = useMemo(() => {
    if (!text.trim() || !detected) return null;
    const { genes } = parseGeneList(text, { delimiter: detected.delimiter, idColumn: detected.idColumn, scoreColumn });
    return genes.length;
  }, [text, detected, scoreColumn]);

  function toggleModality(m) {
    setModalities(prev => prev.includes(m) ? prev.filter(x => x !== m) : [...prev, m]);
  }

  function loadExample() {
    setText(EXAMPLE_GENE_LIST);
    setError('');
  }

  async function handleSubmit() {
    if (!text.trim()) { setError('Paste a gene list or upload a file.'); return; }
    const { genes, warnings } = parseGeneList(text, {
      delimiter: detected?.delimiter,
      idColumn: detected?.idColumn,
      scoreColumn,
    });
    if (genes.length < 5) { setError(`Need at least 5 genes. ${warnings[0] ?? ''}`); return; }
    const resolveOrganism = organism === 'Mouse' ? 'Mouse' : 'Human';
    const { genes: resolved } = resolveIdentifiers(genes, resolveOrganism, crosswalk);
    setError('');
    onAnalyze(resolved, {
      algorithm, organism, modalities, pathwayAnalysis,
      format: detected?.format ?? 'SIMPLE', scoreColumn,
    });
  }

  function handleFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => { setText(e.target.result); setError(''); };
    reader.readAsText(file);
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Nav */}
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 40px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-0)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'linear-gradient(135deg, #2563b8, #4f9cf9)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <FlaskConical size={16} color="white" />
          </div>
          <span style={{ fontWeight: 700, fontSize: '1.1rem', letterSpacing: '-0.02em' }}>RETICLE</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {/* Stepper */}
          {['Upload', 'Analyze', 'Results'].map((step, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: i === 0 ? 'var(--blue)' : 'var(--bg-3)',
                fontSize: '0.72rem', fontWeight: 700, color: i === 0 ? 'white' : 'var(--text-3)',
                border: i === 0 ? 'none' : '1px solid var(--border)',
              }}>{i + 1}</div>
              <span style={{ fontSize: '0.875rem', color: i === 0 ? 'var(--text-1)' : 'var(--text-3)', fontWeight: i === 0 ? 600 : 400 }}>{step}</span>
              {i < 2 && <span style={{ color: 'var(--text-3)', fontSize: '0.75rem' }}>›</span>}
            </div>
          ))}
        </div>
      </nav>

      <div style={{ flex: 1, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '60px 40px' }}>
        <div style={{ width: '100%', maxWidth: 800 }}>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: 6, letterSpacing: '-0.02em' }}>
            Upload your gene list
          </h2>
          <p style={{ color: 'var(--text-2)', marginBottom: 32, fontSize: '0.95rem' }}>
            Paste a ranked gene list from your CRISPR screen. Include gene symbols and numerical scores.
          </p>

          {/* Upload area */}
          <div
            className={`upload-zone${isDragOver ? ' drag-over' : ''}`}
            onClick={() => text ? null : fileRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={e => { e.preventDefault(); setIsDragOver(false); handleFile(e.dataTransfer.files[0]); }}
            style={{ marginBottom: 16, cursor: text ? 'default' : 'pointer' }}
          >
            {text ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'center' }}>
                <CheckCircle2 size={20} color="var(--green)" />
                <span style={{ color: 'var(--green)', fontWeight: 600 }}>
                  {parsedCount ?? '?'} genes loaded
                </span>
                <button
                  onClick={e => { e.stopPropagation(); setText(''); setError(''); }}
                  style={{ color: 'var(--text-3)', fontSize: '0.8rem', textDecoration: 'underline' }}
                >clear</button>
              </div>
            ) : (
              <>
                <Upload size={28} color="var(--text-3)" style={{ marginBottom: 12 }} />
                <div style={{ fontWeight: 500, marginBottom: 4 }}>Drop a CSV/TSV file here</div>
                <div style={{ fontSize: '0.875rem', color: 'var(--text-3)' }}>or click to browse</div>
              </>
            )}
          </div>
          <input ref={fileRef} type="file" accept=".csv,.tsv,.txt" style={{ display: 'none' }} onChange={e => handleFile(e.target.files[0])} />

          {/* Text paste */}
          <div style={{ position: 'relative' }}>
            <textarea
              value={text}
              onChange={e => { setText(e.target.value); setError(''); }}
              placeholder={FORMAT_HINT}
              rows={10}
              style={{
                width: '100%', resize: 'vertical', padding: '14px 16px',
                background: 'var(--bg-2)', border: '1px solid var(--border)',
                borderRadius: 10, color: 'var(--text-1)', fontSize: '0.875rem',
                fontFamily: '"JetBrains Mono","Fira Code",Consolas,monospace',
                outline: 'none', lineHeight: 1.6,
                transition: 'border-color 0.15s',
              }}
              onFocus={e => e.target.style.borderColor = 'var(--blue)'}
              onBlur={e => e.target.style.borderColor = 'var(--border)'}
            />
          </div>

          {/* Format detection + score column row */}
          {detected && text.trim() && (
            <div style={{
              marginTop: 10, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
              padding: '8px 12px', background: 'var(--bg-2)', borderRadius: 8, border: '1px solid var(--border)',
              fontSize: '0.82rem',
            }}>
              <span style={{ color: 'var(--text-3)' }}>
                Detected: <strong style={{ color: 'var(--text-2)' }}>{FORMAT_LABELS[detected.format] ?? detected.format}</strong>
              </span>
              {scoreCands.length > 1 && (
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-3)' }}>
                  Score column:
                  <select
                    value={scoreColumn}
                    onChange={e => setScoreColumn(e.target.value)}
                    style={{
                      background: 'var(--bg-1)', border: '1px solid var(--border)',
                      borderRadius: 5, color: 'var(--text-1)', padding: '2px 6px', fontSize: '0.82rem',
                    }}
                  >
                    {scoreCands.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                </label>
              )}
            </div>
          )}

          {/* Analysis options toggle */}
          <div style={{ marginTop: 12 }}>
            <button
              onClick={() => setOptionsOpen(o => !o)}
              style={{
                display: 'flex', alignItems: 'center', gap: 7,
                padding: '8px 14px', borderRadius: 8,
                border: `1px solid ${optionsOpen ? 'var(--blue-dim)' : 'var(--border)'}`,
                background: optionsOpen ? 'rgba(79,156,249,0.06)' : 'var(--bg-2)',
                color: optionsOpen ? 'var(--blue)' : 'var(--text-2)',
                fontSize: '0.85rem', width: '100%', justifyContent: 'space-between',
                transition: 'all 0.15s',
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                <Settings2 size={14} /> Analysis options
              </span>
              {optionsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>

            {optionsOpen && (
              <div style={{
                marginTop: 2, padding: '18px 20px', borderRadius: '0 0 10px 10px',
                background: 'var(--bg-2)', border: '1px solid var(--border)', borderTop: 'none',
                display: 'flex', flexDirection: 'column', gap: 18,
              }}>
                {/* Scoring algorithm */}
                <div>
                  <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
                    Scoring algorithm
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {ALGORITHMS.map(a => (
                      <button
                        key={a}
                        onClick={() => setAlgorithm(a)}
                        style={{
                          padding: '5px 12px', borderRadius: 6, fontSize: '0.82rem',
                          background: algorithm === a ? 'rgba(79,156,249,0.12)' : 'var(--bg-1)',
                          border: `1px solid ${algorithm === a ? 'var(--blue)' : 'var(--border)'}`,
                          color: algorithm === a ? 'var(--blue)' : 'var(--text-2)',
                          fontWeight: algorithm === a ? 600 : 400,
                          transition: 'all 0.12s',
                        }}
                      >{a}</button>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.73rem', color: 'var(--text-3)', marginTop: 5 }}>
                    Specifies the scoring system so RETICLE can harmonize comparisons accurately
                  </div>
                </div>

                {/* Organism */}
                <div>
                  <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
                    Organism
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {['Human', 'Mouse', 'Both'].map(o => (
                      <button
                        key={o}
                        onClick={() => setOrganism(o)}
                        style={{
                          padding: '5px 14px', borderRadius: 6, fontSize: '0.82rem',
                          background: organism === o ? 'rgba(79,156,249,0.12)' : 'var(--bg-1)',
                          border: `1px solid ${organism === o ? 'var(--blue)' : 'var(--border)'}`,
                          color: organism === o ? 'var(--blue)' : 'var(--text-2)',
                          fontWeight: organism === o ? 600 : 400,
                          transition: 'all 0.12s',
                        }}
                      >{o}</button>
                    ))}
                  </div>
                </div>

                {/* Modality */}
                <div>
                  <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
                    Modality filter
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {MODALITY_OPTIONS.map(m => (
                      <button
                        key={m}
                        onClick={() => toggleModality(m)}
                        style={{
                          padding: '5px 14px', borderRadius: 6, fontSize: '0.82rem',
                          background: modalities.includes(m) ? 'rgba(79,156,249,0.12)' : 'var(--bg-1)',
                          border: `1px solid ${modalities.includes(m) ? 'var(--blue)' : 'var(--border)'}`,
                          color: modalities.includes(m) ? 'var(--blue)' : 'var(--text-2)',
                          fontWeight: modalities.includes(m) ? 600 : 400,
                          transition: 'all 0.12s',
                        }}
                      >{m}</button>
                    ))}
                  </div>
                </div>

                {/* Pathway analysis */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-1)' }}>Include pathway co-significance analysis</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-3)', marginTop: 2 }}>Highlights gene clusters that show significance together</div>
                  </div>
                  <button
                    onClick={() => setPathwayAnalysis(p => !p)}
                    style={{
                      width: 40, height: 22, borderRadius: 11, flexShrink: 0,
                      background: pathwayAnalysis ? 'var(--blue)' : 'var(--bg-3)',
                      border: `1px solid ${pathwayAnalysis ? 'var(--blue)' : 'var(--border)'}`,
                      position: 'relative', transition: 'all 0.2s', cursor: 'pointer',
                    }}
                  >
                    <span style={{
                      display: 'block', width: 16, height: 16, borderRadius: '50%',
                      background: 'white', position: 'absolute', top: 2,
                      left: pathwayAnalysis ? 20 : 2, transition: 'left 0.2s',
                    }} />
                  </button>
                </div>
              </div>
            )}
          </div>

          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, color: 'var(--orange)', fontSize: '0.875rem' }}>
              <AlertCircle size={15} /> {error}
            </div>
          )}

          {/* Action row */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 20 }}>
            <button
              onClick={loadExample}
              style={{
                display: 'flex', alignItems: 'center', gap: 7,
                padding: '9px 16px', borderRadius: 8,
                border: '1px solid var(--border)', color: 'var(--text-2)', fontSize: '0.875rem',
                background: 'var(--bg-2)',
              }}
            >
              <FileText size={15} /> Load example data (Orvedahl screen)
            </button>

            <button
              onClick={handleSubmit}
              disabled={!text.trim()}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '11px 24px', borderRadius: 9,
                background: text.trim() ? 'linear-gradient(135deg, #2563b8, #4f9cf9)' : 'var(--bg-3)',
                color: text.trim() ? 'white' : 'var(--text-3)',
                fontSize: '0.9rem', fontWeight: 600,
                boxShadow: text.trim() ? '0 4px 16px rgba(79,156,249,0.3)' : 'none',
                transition: 'all 0.15s',
              }}
            >
              Run RETICLE <ArrowRight size={16} />
            </button>
          </div>

          {/* Format hint */}
          <div style={{ marginTop: 28, padding: 16, background: 'var(--bg-2)', borderRadius: 9, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>Accepted formats</div>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              {[
                ['Ranked list', 'gene_symbol, score', '(e.g. MAGeCK, STARS, DRUGz output)'],
                ['Hit list', 'gene_symbol only', 'Triggers Jaccard overlap mode'],
                ['Supported IDs', 'HGNC symbol, Entrez ID, Ensembl', 'Auto-resolved via canonical crosswalk'],
              ].map(([title, code, note]) => (
                <div key={title}>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-2)', fontWeight: 500, marginBottom: 3 }}>{title}</div>
                  <code style={{ fontSize: '0.78rem', background: 'var(--bg-1)', padding: '2px 7px', borderRadius: 5, color: 'var(--blue)' }}>{code}</code>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-3)', marginTop: 3 }}>{note}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
