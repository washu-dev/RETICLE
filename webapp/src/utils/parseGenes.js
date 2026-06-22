export function parseGenes(raw) {
  const lines = raw.trim().split('\n').filter(l => l.trim())
  const dataLines = lines.filter(l => !l.toLowerCase().startsWith('gene'))
  if (dataLines.length < 3) return null
  return dataLines
    .map(l => {
      const [sym, score] = l.split(/[,\t]/)
      return { symbol: sym?.trim(), score: parseFloat(score) || 0 }
    })
    .filter(g => g.symbol)
}
