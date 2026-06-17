import React from 'react';
import { useGreeting } from '../hooks/useGreeting';
import '../styles/greeting.css';

export default function GreetingDisplay(): React.ReactElement {
  const { data, loading, error } = useGreeting();

  return (
    <section className="greeting-section" aria-live="polite" aria-busy={loading}>
      <div className="greeting-container">
        <h2 className="greeting-heading">Welcome</h2>

        {loading && (
          <div className="greeting-loading" role="status">
            <p>Loading greeting message...</p>
            <div className="spinner" aria-hidden="true"></div>
          </div>
        )}

        {error && (
          <div className="greeting-error" role="alert">
            <p>Failed to load greeting message</p>
            <details>
              <summary>Error details</summary>
              <p>{error}</p>
            </details>
          </div>
        )}

        {data && !loading && !error && (
          <div className="greeting-content">
            <p className="greeting-message">{data.message}</p>
            <p className="greeting-description">
              This message was retrieved from the RETICLE API. The platform is ready for
              genomic analysis and screening operations.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
