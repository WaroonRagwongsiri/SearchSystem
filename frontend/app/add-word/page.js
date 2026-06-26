"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { addWordMap, getDictionary } from "@/lib/api";

const PAGE_SIZE = 25;

export default function AddWordPage() {
  const [ancient_word, setAncient] = useState("");
  const [modern_definition, setModern] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null); // { ok, msg }

  // dictionary table state
  const [dict, setDict] = useState(null); // { results, total, counts }
  const [page, setPage] = useState(0);
  const [dictError, setDictError] = useState(null);

  const loadDict = useCallback(async (p) => {
    setDictError(null);
    try {
      setDict(await getDictionary({ limit: PAGE_SIZE, offset: p * PAGE_SIZE }));
      setPage(p);
    } catch (err) {
      setDictError(err.message);
    }
  }, []);

  useEffect(() => {
    loadDict(0);
  }, [loadDict]);

  async function onSubmit(e) {
    e.preventDefault();
    if (saving) return;
    setStatus(null);
    setSaving(true);
    // optimistic: show the new word immediately (save is instant now — no extraction round-trip)
    const optimistic = { ancient_word, modern_definition, _pending: true };
    setDict((d) => ({
      ...(d ?? { total: 0, results: [] }),
      results: [optimistic, ...((d?.results) ?? [])].slice(0, PAGE_SIZE),
      total: (d?.total ?? 0) + 1,
    }));
    try {
      const row = await addWordMap(ancient_word, modern_definition);
      setStatus({ ok: true, msg: `Saved “${ancient_word}” → modern definition.` });
      setAncient("");
      setModern("");
      setDict((d) => ({
        ...d,
        results: (d.results ?? []).map((r) => (r._pending ? { ...row } : r)),
      }));
    } catch (err) {
      setStatus({ ok: false, msg: err.message });
      // save failed — drop the optimistic row; the banner carries the error
      setDict((d) => ({
        ...d,
        total: Math.max(0, (d?.total ?? 1) - 1),
        results: (d.results ?? []).filter((r) => !r._pending),
      }));
    } finally {
      setSaving(false);
      loadDict(page); // refetch for accurate ordering
    }
  }

  return (
    <div className="container container--wide">
      <h1 className="page-title">Add word map</h1>
      <p className="muted" style={{ marginBottom: "var(--s-2)" }}>
        Insert or update a historical → modern Thai mapping.
      </p>

      <form className="word-form" onSubmit={onSubmit}>
        <label className="field">
          <span>Ancient word</span>
          <input
            type="text"
            value={ancient_word}
            onChange={(e) => setAncient(e.target.value)}
            placeholder="คำโบราณ"
            required
          />
        </label>
        <label className="field">
          <span>Modern definition</span>
          <textarea
            value={modern_definition}
            onChange={(e) => setModern(e.target.value)}
            rows={4}
            placeholder="ความหมายในปัจจุบัน"
            required
          />
        </label>
        <button
          type="submit"
          className="btn btn--primary"
          disabled={saving || !ancient_word.trim() || !modern_definition.trim()}
        >
          {saving ? "Saving…" : "Save mapping"}
        </button>
      </form>

      {status && (
        <div
          className={`state ${status.ok ? "state--success" : "state--error"}`}
          role={status.ok ? "status" : "alert"}
        >
          <p className="state__title">{status.ok ? "Saved" : "Couldn't save"}</p>
          {status.msg}
        </div>
      )}

      <DictionaryTable dict={dict} error={dictError} page={page} onPage={loadDict} />
    </div>
  );
}

function DictionaryTable({ dict, error, page, onPage }) {
  const pages = dict ? Math.ceil(dict.total / PAGE_SIZE) : 1;
  return (
    <section className="dict-section">
      <h2 className="dict-section__title">Dictionary</h2>

      {!dict && !error && <p className="muted">Loading…</p>}

      {error && (
        <div className="state state--error" role="alert">
          <p className="state__title">Couldn&apos;t load dictionary</p>
          {error}
        </div>
      )}

      {dict && (
        <>
          <p className="dict-summary tnum">
            <span>{dict.total.toLocaleString()}</span> words
          </p>

          {dict.results.length === 0 ? (
            <p className="muted">No words yet.</p>
          ) : (
            <div className="dict-table-wrap">
              <table className="dict-table">
                <thead>
                  <tr>
                    <th>Ancient</th>
                    <th>Definition</th>
                  </tr>
                </thead>
                <tbody>
                  {dict.results.map((r) => (
                    <tr key={r._pending ? "__pending__" : r.ancient_word} className={r._pending ? "is-pending" : ""}>
                      <td className="serif dict-table__ancient">
                        {r._pending ? (
                          r.ancient_word
                        ) : (
                          <Link href={`/review/${encodeURIComponent(r.ancient_word)}`}>
                            {r.ancient_word} <span className="muted">→ review</span>
                          </Link>
                        )}
                      </td>
                      <td className="dict-table__def">{r.modern_definition}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {pages > 1 && (
            <nav className="pager" aria-label="Dictionary pagination">
              <button className="pager__btn" disabled={page === 0} onClick={() => onPage(page - 1)}>
                ‹ Prev
              </button>
              <span className="pager__info tnum">
                Page {page + 1} of {pages}
              </span>
              <button
                className="pager__btn"
                disabled={(page + 1) * PAGE_SIZE >= dict.total}
                onClick={() => onPage(page + 1)}
              >
                Next ›
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
