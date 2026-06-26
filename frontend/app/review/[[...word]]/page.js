"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getDocumentsByWord, reembed } from "@/lib/api";

const PAGE_SIZES = [25, 50, 100];

export default function ReviewPage() {
  // Optional catch-all: /review → pick-a-word landing; /review/<word> → per-word review.
  // ponytail: Next 16 passes catch-all segments through URL-encoded, so decode here. try/catch
  // makes it safe whether or not Next pre-decodes, and never throws on a stray '%'.
  const params = useParams();
  const raw = params?.word?.[0] ?? "";
  const word = (() => {
    if (!raw) return "";
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  })();

  const [data, setData] = useState(null); // { word, total, results }
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(PAGE_SIZES[0]); // reviews are page-by-page; common words hit thousands of docs
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // overrides avoid a stale `limit` closure when the page size changes (same pattern as the search page)
  const load = useCallback(
    async (p, overrides = {}) => {
      const lim = overrides.limit ?? limit;
      setError(null);
      setLoading(true);
      try {
        setData(await getDocumentsByWord(word, { limit: lim, offset: p * lim }));
        setPage(p);
      } catch (e) {
        setError(e.message);
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [word, limit],
  );

  useEffect(() => {
    if (!word) return;
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [word]);

  function onLimitChange(e) {
    const lim = Number(e.target.value);
    setLimit(lim);
    setPage(0);
    load(0, { limit: lim });
  }

  if (!word) {
    return (
      <div className="container">
        <h1 className="page-title">Review</h1>
        <p className="muted">
          Pick a word to inspect how the modernize step handled its documents — see the
          raw text, the LLM output, and edit what gets embedded. Browse the{" "}
          <Link href="/add-word">dictionary</Link>.
        </p>
      </div>
    );
  }

  const total = data?.total ?? 0;
  const pages = Math.ceil(total / limit) || 1;
  const start = total === 0 ? 0 : page * limit + 1;
  const end = Math.min(total, (page + 1) * limit);

  return (
    <div className="container container--wide">
      <Link className="back-link" href="/add-word">
        ‹ Back to dictionary
      </Link>
      <h1 className="page-title serif">{word}</h1>

      {loading && !data && <p className="muted">Loading…</p>}

      {error && (
        <div className="state state--error" role="alert">
          <p className="state__title">Couldn&apos;t load documents</p>
          {error}
        </div>
      )}

      {data && (
        <>
          <div className="review-toolbar">
            <p className="muted tnum review-summary">
              Showing <span>{start.toLocaleString()}–{end.toLocaleString()}</span> of{" "}
              <span>{total.toLocaleString()}</span> document{total === 1 ? "" : "s"}
            </p>
            <label className="pagesize">
              <span className="pagesize__label">Per page</span>
              <select value={limit} onChange={onLimitChange} aria-label="Documents per page">
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {data.results.length === 0 ? (
            <p className="muted">No modernized documents contain this word.</p>
          ) : (
            <>
              <ReviewPager page={page} pages={pages} total={total} limit={limit} onPage={load} />
              <div className="review-list">
                {data.results.map((r) => (
                  <ReviewCard key={r.id} r={r} />
                ))}
              </div>
              <ReviewPager page={page} pages={pages} total={total} limit={limit} onPage={load} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function ReviewPager({ page, pages, total, limit, onPage }) {
  if (pages <= 1) return null;
  return (
    <nav className="pager" aria-label="Review pagination">
      <button className="pager__btn" disabled={page === 0} onClick={() => onPage(page - 1)}>
        ‹ Prev
      </button>
      <span className="pager__info tnum">
        Page {page + 1} of {pages}
      </span>
      <button
        className="pager__btn"
        disabled={(page + 1) * limit >= total}
        onClick={() => onPage(page + 1)}
      >
        Next ›
      </button>
    </nav>
  );
}

function ReviewCard({ r }) {
  // ponytail: seed with the human override, else the LLM output, else blank.
  const [text, setText] = useState(r.embed_text ?? r.modernized_content ?? "");
  const [state, setState] = useState(null); // { ok, msg }
  const [busy, setBusy] = useState(false);
  // status: is the embedding currently the human edit (embed_text set) or the LLM output?
  const [edited, setEdited] = useState(!!r.embed_text);

  async function onReembed(e) {
    e.preventDefault();
    if (busy) return;
    setState(null);
    setBusy(true);
    try {
      await reembed(r.id, text);
      setEdited(true); // a successful re-embed means the embedding now uses the edit
      setState({ ok: true, msg: "Re-embedded." });
    } catch (err) {
      setState({ ok: false, msg: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="review-card">
      <h2 className="review-card__title">
        <Link href={`/doc/${encodeURIComponent(r.id)}`}>
          {r.subject || r.description || r.id}
        </Link>
        <span className={`badge ${edited ? "badge--done" : "badge--pending"}`} title="What the vector index currently holds for this document">
          {edited ? "Edited" : "Default"}
        </span>
      </h2>

      <div className="review-card__field">
        <span className="review-card__label">
          Status — {edited ? "embeds your edited text" : "embeds the LLM output (no override)"}
        </span>
      </div>

      <div className="review-card__field">
        <span className="review-card__label">Raw</span>
        <p className="serif review-card__read">{r.description || "—"}</p>
      </div>

      <div className="review-card__field">
        <span className="review-card__label">Dictionary context given to the LLM</span>
        <p className="muted">{r.dict_context}</p>
      </div>

      <div className="review-card__field">
        <span className="review-card__label">LLM output (modernize step)</span>
        <p className="serif review-card__read">{r.modernized_content || "—"}</p>
      </div>

      <form className="review-card__field" onSubmit={onReembed}>
        <label className="review-card__label" htmlFor={`embed-${r.id}`}>
          What gets embedded
        </label>
        <textarea
          id={`embed-${r.id}`}
          className="serif"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
        />
        <div className="review-card__actions">
          <button type="submit" className="btn btn--primary" disabled={busy || !text.trim()}>
            {busy ? "Embedding…" : "Re-embed"}
          </button>
          {state && (
            <span
              className={`review-card__msg ${state.ok ? "review-card__msg--ok" : "review-card__msg--err"}`}
              role={state.ok ? "status" : "alert"}
            >
              {state.msg}
            </span>
          )}
        </div>
      </form>
    </article>
  );
}
