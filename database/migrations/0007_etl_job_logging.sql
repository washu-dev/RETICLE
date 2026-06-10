-- RETICLE ETL Job Logging
-- Tracks all SLURM job executions and performance metrics

CREATE TABLE IF NOT EXISTS etl_job_log (
    job_log_id SERIAL PRIMARY KEY,
    slurm_job_id VARCHAR(20) NOT NULL,
    version_id INT NOT NULL,
    duration_seconds NUMERIC NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    num_threads INT,
    chunk_size INT,
    batch_size INT,
    error_message TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (version_id) REFERENCES data_load_version(version_id),
    CONSTRAINT valid_status CHECK (
        CASE WHEN status = 'failed' THEN error_message IS NOT NULL
             ELSE TRUE END
    )
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_etl_job_log_slurm_id ON etl_job_log(slurm_job_id);
CREATE INDEX IF NOT EXISTS idx_etl_job_log_version ON etl_job_log(version_id);
CREATE INDEX IF NOT EXISTS idx_etl_job_log_completed_at ON etl_job_log(completed_at DESC);

-- View for recent jobs
CREATE OR REPLACE VIEW etl_job_stats AS
SELECT
    version_id,
    COUNT(*) as total_runs,
    AVG(duration_seconds) as avg_duration,
    MIN(duration_seconds) as min_duration,
    MAX(duration_seconds) as max_duration,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_runs,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_runs,
    MAX(completed_at) as last_run
FROM etl_job_log
GROUP BY version_id
ORDER BY version_id DESC;

-- View for performance trends
CREATE OR REPLACE VIEW etl_job_performance AS
SELECT
    job_log_id,
    slurm_job_id,
    version_id,
    duration_seconds,
    num_threads,
    ROUND(duration_seconds * num_threads / 100.0, 2) as thread_efficiency,
    status,
    completed_at
FROM etl_job_log
WHERE status = 'completed'
ORDER BY completed_at DESC;
