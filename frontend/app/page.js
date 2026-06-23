"use client";

import { useState } from "react";
import { search } from "@/lib/api";

export default function Home() {
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [useVector, setUseVector] = useState(true);
  const [submitted, setSubmitted] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    if (!q.trim() || loading) return;
    setLoading(true);
    setError(null);
    setSubmitted(true);
    try {
      setData(await search(q, { vector: useVector }));
    } catch (err) {
      setError(err.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <section className="hero fade-in">
        <h1>
          Search the archive
          <span className="th">ค้นหาจดหมายเหตุ</span>
        </h1>
        <p className="lead">
          Lexical, fuzzy, and vector search across 313,600 historical Thai
          documents — find meaning even when the spelling has changed.
        </p>
      </section>

      <div className="container container--wide" style={{ paddingTop: 0 }}>
        <form className="search-form" onSubmit={onSubmit} role="search">
          <input
            type="text"
            className="search-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="ค้นหาคำ หรือวลี…"
            aria-label="Search query"
            autoFocus
          />
          <button
            type="submit"
            className="btn btn--primary"
            disabled={loading || !q.trim()}
            aria-label="Search"
          >
            <SearchIcon />
            {loading ? "Searching…" : "Search"}
          </button>
          <label className="switch" title="Match by meaning (vector), not just exact spelling">
            <input
              type="checkbox"
              checked={useVector}
              onChange={(e) => setUseVector(e.target.checked)}
            />
            <span className="switch__track">
              <span className="switch__thumb" />
            </span>
            <span className="switch__label">Vector</span>
          </label>
        </form>

        {!submitted && !loading && <EmptyHint />}

        {loading && <Skeleton />}

        {!loading && error && (
          <div className="state state--error" role="alert">
            <p className="state__title">Search failed</p>
            {error}
          </div>
        )}

        {!loading && !error && data && <Results data={data} query={q} vector={useVector} />}
      </div>
    </>
  );
}

function EmptyHint() {
  return (
    <div className="state state--empty">
      <p className="state__title serif" style={{ fontSize: "var(--fs-500)" }}>
        Begin a search
      </p>
      Try a modern or historical Thai word. With{" "}
      <strong style={{ color: "var(--ink)" }}>Vector</strong> on, results match by
      meaning — useful when the archive uses archaic spelling.
    </div>
  );
}

function Skeleton() {
  return (
    <ul className="skeleton" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <li className="skeleton__row" key={i}>
          <span className="skeleton__bar skeleton__bar--score" />
          <span className="skeleton__bars">
            <span className="skeleton__bar" style={{ width: "92%" }} />
            <span className="skeleton__bar" style={{ width: "68%" }} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function Results({ data, query, vector }) {
  // ponytail: /search can still return a stub notice; surface it honestly.
  if (data.detail) {
    return (
      <div className="state state--warn">
        <p className="state__title">Heads up</p>
        {data.detail}
      </div>
    );
  }
  const items = data.results || [];
  if (!items.length) {
    return (
      <div className="state state--empty">
        <p className="state__title serif" style={{ fontSize: "var(--fs-500)" }}>
          No matches
        </p>
        Nothing found for “{query}”. Try another spelling, or toggle vector mode.
      </div>
    );
  }
  return (
    <>
      <p className="search-meta">
        <span>
          <span className="tnum">{items.length}</span> result{items.length === 1 ? "" : "s"}{" "}
          for “{query}”
        </span>
        <span>{vector ? "lexical · fuzzy · vector" : "lexical · fuzzy"}</span>
      </p>
      <ul className="results">
        {items.map((r) => (
          <li className="result" key={r.id}>
            <span className="result__score tnum">
              {typeof r.score === "number" ? r.score.toFixed(3) : r.score ?? "—"}
            </span>
            <span className="result__body">
              <span className="result__snippet">
                {r.snippet ?? r.modernized_content ?? "—"}
              </span>
              {r.id && <span className="result__id">{r.id}</span>}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function SearchIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}
