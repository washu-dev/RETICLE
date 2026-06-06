# RETICLE Graph Explorer

Interactive browser-based visualization of Screen-Gene-Publication relationships.

## Architecture

- **Backend**: Node.js/Express API (port 3001) in `/graph-api`
- **Frontend**: React + Cytoscape.js (port 3000) in `/graph-ui`
- **Database**: PostgreSQL (reticle_biogrid)

## Directory Structure

```
/Volumes/SD\ Media/projects/RETICLE/
├── graph-api/              # Backend API
│   ├── package.json
│   ├── server.js
│   └── node_modules/
├── graph-ui/               # Frontend React app
│   ├── package.json
│   ├── src/
│   │   ├── App.js
│   │   ├── App.css
│   │   ├── index.js
│   │   ├── index.css
│   │   └── components/
│   ├── public/
│   │   └── index.html
│   └── node_modules/
├── scripts/                # Data loading & processing
├── database/               # Migrations
└── Domain/                 # Data files
```

## Setup

### 1. Install Backend Dependencies

```bash
cd /Volumes/SD\ Media/projects/RETICLE/graph-api
npm install
```

### 2. Install Frontend Dependencies

```bash
cd /Volumes/SD\ Media/projects/RETICLE/graph-ui
npm install
```

## Running

### Terminal 1: Start Backend API

```bash
cd /Volumes/SD\ Media/projects/RETICLE/graph-api
npm start
```

Expected output:
```
✓ Connected to PostgreSQL
🚀 RETICLE Graph API running on http://localhost:3001
📊 GET http://localhost:3001/api/graph/overview
```

### Terminal 2: Start Frontend

```bash
cd /Volumes/SD\ Media/projects/RETICLE/graph-ui
npm start
```

This will open `http://localhost:3000` in your browser automatically.

## Features

### Main Graph View
- **Interactive force-directed graph** showing top 10 screens with related genes and publications
- **Node colors**:
  - Blue: Screens (largest nodes)
  - Purple: Genes (medium nodes)
  - Pink: Publications (medium nodes)
- **Hover effects**: Shows connections
- **Click to select**: Shows details in side panel
- **Resizable**: Drag edges to resize panels

### Detail Panel
Displays information about the selected node:

#### Screen Node
- BioGrid Screen ID
- Number of genes in screen
- Number of publications
- **Drill down**: "View Genes in Screen" → table

#### Gene Node
- Gene symbol
- Entrez ID (clickable link to NCBI)
- Number of screens
- External links: NCBI Gene, UniProt
- **Drill down**: "View Screens with Gene" → table

#### Publication Node
- PMID (clickable link to PubMed)
- DOI (if available, link to DOI.org)
- Number of screens
- External links: PubMed, PMC, DOI

### Table Views

#### Screen → Genes Table
Shows all genes in a selected screen
- Gene symbol
- Entrez ID
- Number of publications
- Click "View Screens →" to pivot to screens

#### Gene → Screens Table
Shows all screens containing a selected gene
- BioGrid Screen ID
- Organism
- Source
- Number of publications
- Click "View Genes →" to pivot back to genes

## API Endpoints

```
GET  /api/graph/overview                    # Top 10 screens with graph data
GET  /api/screen/:screenId/genes            # Genes in a screen
GET  /api/gene/:geneId/screens              # Screens containing a gene
GET  /api/publication/:pubId/screens        # Screens from a publication
GET  /api/publication/:pubId/details        # Publication metadata
GET  /api/health                            # Health check
```

## Customization

### Change Initial Load Size
Edit `graph-api/server.js` line 30:
```javascript
LIMIT 10  // Change this number
```

### Change Colors
Edit `graph-ui/src/components/GraphView.js` in the style section.

### Change Layout
Options: `cose-bilkent`, `cose`, `fcose`, `breadthfirst`, etc.
Edit `GraphView.js` layout config:
```javascript
layout: {
  name: 'cose-bilkent'  // Try other layouts
}
```

## Data Prerequisites

Before running the app, ensure:

1. **Database populated**: 
   ```bash
   cd scripts
   python init_screen_gene_publication.py
   python load_screen_gene_scores.py
   python populate_publication_metadata.py
   ```

2. **Check data**:
   ```bash
   psql -c "SELECT COUNT(*) FROM screen_gene_publication;"
   # Should show > 0 rows
   ```

## Troubleshooting

### "Failed to load graph data"
- Check backend is running: `curl http://localhost:3001/api/health`
- Check `.env` database config in scripts folder
- Check PostgreSQL connection

### Empty graph
- Run data loading scripts (see Data Prerequisites)
- Check that screen_gene_publication has rows

### Slow graph rendering
- Reduce LIMIT in graph-api/server.js (try 5 instead of 10)
- Check browser console for errors
- Try a different layout algorithm

## Development

### Backend Logs
```bash
cd graph-api
npm install nodemon --save-dev
npm run dev  # Auto-restart on file changes
```

### Frontend Logs
```bash
cd graph-ui
npm start  # Shows warnings and errors in console
```

### Database Debugging
```bash
psql -U reticle_admin -h reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com -d reticle_biogrid

# Check graph data
SELECT COUNT(*) FROM screen_gene_publication;
SELECT COUNT(DISTINCT screen_id) FROM screen_gene_publication;
SELECT COUNT(DISTINCT gene_id) FROM screen_gene_publication;
SELECT COUNT(DISTINCT publication_id) FROM screen_gene_publication;
```

## Next Steps

- [ ] Add search/filter
- [ ] Export as SVG
- [ ] 3D graph view
- [ ] Node clustering
- [ ] Timeline animation
