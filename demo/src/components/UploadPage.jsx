import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Upload, FileText, ArrowRight, CheckCircle2, AlertCircle, FlaskConical } from 'lucide-react';
import { EXAMPLE_GENE_LIST } from '../mockData';
import { detectFormat, suggestScoreColumn, parseGeneList, resolveIdentifiers } from '../utils/geneParser';
import crosswalk from '../data/crosswalk.min.json';

const FORMAT_HINT = `Paste a ranked gene list — CSV or TSV with a header row.

Supported formats:
  MAGeCK gene summary  (id, neg|lfc, neg|score, ...)
  STARS output         (Gene, LFC, q-value, p-value, Rank)
  DESeq2 results       (gene, baseMean, log2FoldChange, padj)
  Simple 2-column      (gene_symbol, score)

Example (simple):
  gene_symbol,score
  ATG5,-3.21
  ULK1,-2.74
  ...`;

/**
 * Describe a detected format with a short human-readable label.
 * @param {'MAGECK'|'STARS'|'DESEQ2'|'SIMPLE'|'UNKNOWN'} format
 * @param {number} confidence  0–1
 * @returns {string}
 */
function formatLabel(format, confidence) {
  const labels = {
    MAGECK:  'MAGeCK gene summary',
    STARS:   'STARS output',
    DESEQ2:  'DESeq2 results',
    SIMPLE:  'Simple CSV/TSV',
    UNKNOWN: 'Unknown format',
  };
  const conf = confidence >= 0.9 ? '' : confidence >= 0.6 ? ' (likely)' : ' (guessed)';
  return (labels[format] ?? format) + conf;
}

export default function UploadPage({ onAnalyze }) {
  const [text,         setText]         = useState('');
  const [isDragOver,   setIsDragOver]   = useState(false);
  const [error,        setError]        = useState('');
  const [warnings,     setWarnings]     = useState([]);

  // Format detection state
  const [detected,     setDetected]     = useState(null);   // { format, delimiter, columns, idColumn, confidence }
  const [scoreColumn,  setScoreColumn]  = useState('');
  const [scoreCands,   setScoreCands]   = useState([]);     // [{value, label}]
  const [organism,     setOrganism]     = useState('Human');

  const fileRef    = useRef();
  const detectTimer = useRef(null);

  // Run format detection (debounced 200ms) whenever text changes
  const runDetect = useCallback((raw) => {
    if (!raw.trim()) {
      setDetected(null);
      setScoreColumn('');
      setScoreCands([]);
      return;
    }

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

  // Derive gene count from current text + detected format + scoreColumn (no effect needed)
  const parsedCount = useMemo(() => {
    if (!text.trim() || !detected) return null;
    const { genes } = parseGeneList(text, {
      format:      detected.format,
      delimiter:   detected.delimiter,
      idColumn:    detected.idColumn,
      scoreColumn,
    });
    return genes.length;
  }, [text, detected, scoreColumn]);

  function loadExample() {
    setText(EXAMPLE_GENE_LIST);
    setError('');
    setWarnings([]);
  }

  function handleSubmit() {
    if (!text.trim()) {
      setError('Paste a gene list or upload a file.');
      return;
    }
    if (!detected || detected.format === 'UNKNOWN') {
      setError('Could not detect a supported format. Check your file and try again.');
      return;
    }

    const { genes: rawGenes, warnings: parseWarnings } = parseGeneList(text, {
      format:      detected.format,
      delimiter:   detected.delimiter,
      idColumn:    detected.idColumn,
      scoreColumn,
    });

    if (rawGenes.length === 0) {
      // parseGeneList already puts the right warning in parseWarnings
      const msg = parseWarnings.find(w => w.includes('No rows')) ||
                  parseWarnings.find(w => w.includes('fewer')) ||
                  parseWarnings.find(w => w.includes('at least')) ||
                  'No genes found. Check your file format.';
      setError(msg);
      setWarnings(parseWarnings.filter(w => w !== msg));
      return;
    }

    const { genes: resolvedGenes, warnings: resolveWarnings } = resolveIdentifiers(
      rawGenes,
      organism,
      crosswalk
    );

    const allWarnings = [...parseWarnings, ...resolveWarnings];
    setWarnings(allWarnings);
    setError('');

    const options = {
      format:      detected.format,
      scoreColumn,
      organism,
      delimiter:   detected.delimiter,
    };

    onAnalyze(resolvedGenes, options);
  }

  function handleFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
      setText(e.target.result);
      setError('');
      setWarnings([]);
    };
    reader.readAsText(file);
  }

  const hasText = Boolean(text.trim());
  const showOptions = hasText && detected && detected.format !== 'UNKNOWN';

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
            Paste a ranked gene list from your CRISPR screen. Supports MAGeCK, STARS, DESeq2, and simple CSV/TSV formats.
          </p>

          {/* Upload zone */}
          <div
            className={`upload-zone${isDragOver ? ' drag-over' : ''}`}
            onClick={() => hasText ? null : fileRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={e => { e.preventDefault(); setIsDragOver(false); handleFile(e.dataTransfer.files[0]); }}
            style={{ marginBottom: 16, cursor: hasText ? 'default' : 'pointer' }}
          >
            {hasText ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'center' }}>
                <CheckCircle2 size={20} color="var(--green)" />
                <span style={{ color: 'var(--green)', fontWeight: 600 }}>
                  {parsedCount !== null ? parsedCount : '?'} genes loaded
                </span>
                <button
                  onClick={e => { e.stopPropagation(); setText(''); setError(''); setWarnings([]); }}
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
              onChange={e => { setText(e.target.value); setError(''); setWarnings([]); }}
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

          {/* Options row — shown only when text is present */}
          {showOptions && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
              marginTop: 12, padding: '10px 14px',
              background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderRadius: 8, fontSize: '0.85rem',
            }}>
              {/* Detected format label */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-2)' }}>
                <span style={{ fontWeight: 600, color: 'var(--text-3)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Detected:</span>
                <span style={{ color: 'var(--blue)', fontWeight: 500 }}>
                  {formatLabel(detected.format, detected.confidence)}
                </span>
              </div>

              {/* Score column selector */}
              {scoreCands.length > 1 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <label style={{ color: 'var(--text-3)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                    Score column:
                  </label>
                  <select
                    value={scoreColumn}
                    onChange={e => setScoreColumn(e.target.value)}
                    style={{
                      background: 'var(--bg-1)', border: '1px solid var(--border)',
                      borderRadius: 5, color: 'var(--text-1)', fontSize: '0.85rem',
                      padding: '3px 8px', cursor: 'pointer',
                    }}
                  >
                    {scoreCands.map(c => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Organism selector */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <label style={{ color: 'var(--text-3)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                  Organism:
                </label>
                <select
                  value={organism}
                  onChange={e => setOrganism(e.target.value)}
                  style={{
                    background: 'var(--bg-1)', border: '1px solid var(--border)',
                    borderRadius: 5, color: 'var(--text-1)', fontSize: '0.85rem',
                    padding: '3px 8px', cursor: 'pointer',
                  }}
                >
                  <option value="Human">Human</option>
                  <option value="Mouse">Mouse</option>
                </select>
              </div>
            </div>
          )}

          {/* Error display */}
          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, color: 'var(--orange)', fontSize: '0.875rem' }}>
              <AlertCircle size={15} /> {error}
            </div>
          )}

          {/* Non-fatal warnings */}
          {warnings.length > 0 && !error && (
            <div style={{ marginTop: 10 }}>
              {warnings.map((w, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--orange)', fontSize: '0.8rem', marginBottom: 2 }}>
                  <AlertCircle size={13} /> {w}
                </div>
              ))}
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
              disabled={!hasText}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '11px 24px', borderRadius: 9,
                background: hasText ? 'linear-gradient(135deg, #2563b8, #4f9cf9)' : 'var(--bg-3)',
                color: hasText ? 'white' : 'var(--text-3)',
                fontSize: '0.9rem', fontWeight: 600,
                boxShadow: hasText ? '0 4px 16px rgba(79,156,249,0.3)' : 'none',
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
                ['MAGeCK',  'id, neg|lfc, neg|score, ...',    'MAGeCK gene_summary output'],
                ['STARS',   'Gene, LFC, q-value, p-value',    'STARS gene-level output'],
                ['DESeq2',  'gene, baseMean, log2FC, padj',   'DESeq2 results() table'],
                ['Simple',  'gene_symbol, score',             'Any 2-column CSV/TSV'],
              ].map(([title, code, note]) => (
                <div key={title}>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-2)', fontWeight: 500, marginBottom: 3 }}>{title}</div>
                  <code style={{ fontSize: '0.78rem', background: 'var(--bg-1)', padding: '2px 7px', borderRadius: 5, color: 'var(--blue)' }}>{code}</code>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-3)', marginTop: 3 }}>{note}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: '0.75rem', color: 'var(--text-3)' }}>
              Supported identifiers: HGNC symbol, Entrez ID, Ensembl ID. Mouse gene symbols auto-resolved via ortholog crosswalk.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
