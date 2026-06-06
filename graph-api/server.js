#!/usr/bin/env node
/**
 * RETICLE Graph API Server
 * Serves data for screen-gene-publication visualization
 */

const express = require('express');
const cors = require('cors');
const { Client } = require('pg');
require('dotenv').config();  // Reads .env in current directory

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

// Database connection
const dbConfig = {
  host: process.env.DB_HOST || 'localhost',
  port: process.env.DB_PORT || 5432,
  database: process.env.DB_NAME || 'reticle_biogrid',
  user: process.env.DB_USER || 'reticle_admin',
  password: process.env.DB_PASSWORD || ''
};

// Add SSL for AWS RDS
if (process.env.DB_SSL === 'true' || process.env.DB_HOST.includes('rds.amazonaws.com')) {
  dbConfig.ssl = {
    rejectUnauthorized: false  // For RDS with self-signed certs
  };
}

const db = new Client(dbConfig);

db.connect().then(() => {
  console.log('✓ Connected to PostgreSQL');
}).catch(err => {
  console.error('✗ Database connection failed:', err);
  process.exit(1);
});

// ============================================================================
// API ROUTES
// ============================================================================

/**
 * GET /api/graph/overview
 * Return top 10 screens with related genes and publications
 */
app.get('/api/graph/overview', async (req, res) => {
  try {
    // Get top 10 screens
    const screensResult = await db.query(`
      SELECT DISTINCT
        s.screen_id,
        s.biogrid_screen_id,
        s.annotation_source,
        s.organism,
        COUNT(DISTINCT sgp.gene_id) as num_genes,
        COUNT(DISTINCT sgp.publication_id) as num_publications
      FROM screen s
      LEFT JOIN screen_gene_publication sgp ON s.screen_id = sgp.screen_id
      GROUP BY s.screen_id, s.biogrid_screen_id, s.annotation_source, s.organism
      ORDER BY s.screen_id DESC
      LIMIT 10
    `);

    // Get all genes and publications related to these screens
    const screenIds = screensResult.rows.map(s => s.screen_id);

    if (screenIds.length === 0) {
      return res.json({ screens: [], genes: [], publications: [], links: [] });
    }

    // Get genes
    const genesResult = await db.query(`
      SELECT DISTINCT
        g.gene_id,
        g.gene_symbol,
        g.entrez_id,
        COUNT(DISTINCT sgp.screen_id) as num_screens
      FROM gene g
      INNER JOIN screen_gene_publication sgp ON g.gene_id = sgp.gene_id
      WHERE sgp.screen_id = ANY($1)
      GROUP BY g.gene_id, g.gene_symbol, g.entrez_id
      LIMIT 100
    `, [screenIds]);

    // Get publications
    const pubsResult = await db.query(`
      SELECT DISTINCT
        p.publication_id,
        p.pmid,
        p.title,
        p.doi,
        COUNT(DISTINCT sgp.screen_id) as num_screens
      FROM publication p
      INNER JOIN screen_gene_publication sgp ON p.publication_id = sgp.publication_id
      WHERE sgp.screen_id = ANY($1)
      GROUP BY p.publication_id, p.pmid, p.title, p.doi
      LIMIT 50
    `, [screenIds]);

    // Get relationships
    const linksResult = await db.query(`
      SELECT DISTINCT
        sgp.screen_id,
        sgp.gene_id,
        sgp.publication_id
      FROM screen_gene_publication sgp
      WHERE sgp.screen_id = ANY($1)
    `, [screenIds]);

    res.json({
      screens: screensResult.rows,
      genes: genesResult.rows,
      publications: pubsResult.rows,
      links: linksResult.rows
    });

  } catch (error) {
    console.error('Error fetching graph overview:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /api/screen/:screenId/genes
 * Get all genes in a specific screen
 */
app.get('/api/screen/:screenId/genes', async (req, res) => {
  try {
    const { screenId } = req.params;

    const result = await db.query(`
      SELECT DISTINCT
        g.gene_id,
        g.gene_symbol,
        g.entrez_id,
        g.organism,
        COUNT(DISTINCT sgp.publication_id) as num_publications
      FROM gene g
      INNER JOIN screen_gene_publication sgp ON g.gene_id = sgp.gene_id
      WHERE sgp.screen_id = $1
      GROUP BY g.gene_id, g.gene_symbol, g.entrez_id, g.organism
      ORDER BY g.gene_symbol
    `, [screenId]);

    res.json({
      screenId,
      genes: result.rows
    });

  } catch (error) {
    console.error('Error fetching screen genes:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /api/gene/:geneId/screens
 * Get all screens containing a specific gene
 */
app.get('/api/gene/:geneId/screens', async (req, res) => {
  try {
    const { geneId } = req.params;

    const result = await db.query(`
      SELECT DISTINCT
        s.screen_id,
        s.biogrid_screen_id,
        s.annotation_source,
        s.organism,
        COUNT(DISTINCT sgp.publication_id) as num_publications
      FROM screen s
      INNER JOIN screen_gene_publication sgp ON s.screen_id = sgp.screen_id
      WHERE sgp.gene_id = $1
      GROUP BY s.screen_id, s.biogrid_screen_id, s.annotation_source, s.organism
      ORDER BY s.screen_id
    `, [geneId]);

    res.json({
      geneId,
      screens: result.rows
    });

  } catch (error) {
    console.error('Error fetching gene screens:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /api/publication/:pubId/screens
 * Get all screens from a specific publication
 */
app.get('/api/publication/:pubId/screens', async (req, res) => {
  try {
    const { pubId } = req.params;

    const result = await db.query(`
      SELECT DISTINCT
        s.screen_id,
        s.biogrid_screen_id,
        s.annotation_source,
        s.organism,
        COUNT(DISTINCT sgp.gene_id) as num_genes
      FROM screen s
      INNER JOIN screen_gene_publication sgp ON s.screen_id = sgp.screen_id
      WHERE sgp.publication_id = $1
      GROUP BY s.screen_id, s.biogrid_screen_id, s.annotation_source, s.organism
      ORDER BY s.screen_id
    `, [pubId]);

    res.json({
      publicationId: pubId,
      screens: result.rows
    });

  } catch (error) {
    console.error('Error fetching publication screens:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /api/publication/:pubId/details
 * Get publication metadata
 */
app.get('/api/publication/:pubId/details', async (req, res) => {
  try {
    const { pubId } = req.params;

    const result = await db.query(`
      SELECT
        publication_id,
        pmid,
        title,
        journal,
        doi,
        abstract_text,
        publication_date
      FROM publication
      WHERE publication_id = $1
    `, [pubId]);

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Publication not found' });
    }

    res.json(result.rows[0]);

  } catch (error) {
    console.error('Error fetching publication details:', error);
    res.status(500).json({ error: error.message });
  }
});

// ============================================================================
// HEALTH CHECK
// ============================================================================

app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ============================================================================
// START SERVER
// ============================================================================

app.listen(PORT, () => {
  console.log(`\n🚀 RETICLE Graph API running on http://localhost:${PORT}`);
  console.log(`📊 GET http://localhost:${PORT}/api/graph/overview`);
  console.log(`\n`);
});

// Graceful shutdown
process.on('SIGINT', async () => {
  console.log('\n\nShutting down...');
  await db.end();
  process.exit(0);
});
