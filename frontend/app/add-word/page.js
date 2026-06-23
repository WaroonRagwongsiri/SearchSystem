"use client";

import { useState } from "react";
import { addWordMap } from "@/lib/api";

export default function AddWordPage() {
  const [ancient_word, setAncient] = useState("");
  const [modern_definition, setModern] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null); // { ok, msg }

  async function onSubmit(e) {
    e.preventDefault();
    if (saving) return;
    setStatus(null);
    setSaving(true);
    try {
      await addWordMap(ancient_word, modern_definition);
      setStatus({ ok: true, msg: `Saved “${ancient_word}” → modern definition.` });
      setAncient("");
      setModern("");
    } catch (err) {
      setStatus({ ok: false, msg: err.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="container">
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
    </div>
  );
}
