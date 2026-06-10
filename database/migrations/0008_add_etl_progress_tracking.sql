-- ETL Progress Checkpoint Tracking
-- Enables resumable ETL pipeline on failure

CREATE TABLE IF NOT EXISTS etl_progress (
    run_id INT PRIMARY KEY,
    stage VARCHAR(50) NOT NULL,
    rows_processed INT DEFAULT 0,
    last_row_timestamp TIMESTAMP,
    error_message TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_etl_progress_stage ON etl_progress(stage);
CREATE INDEX IF NOT EXISTS idx_etl_progress_updated ON etl_progress(last_updated);

COMMENT ON TABLE etl_progress IS 'Tracks progress of ETL pipeline stages to enable resumable processing on failure';
COMMENT ON COLUMN etl_progress.stage IS 'Current stage: screens, genes, pairs, aggregates';
COMMENT ON COLUMN etl_progress.rows_processed IS 'Number of rows processed in current stage';
COMMENT ON COLUMN etl_progress.error_message IS 'Last error encountered, if any';
