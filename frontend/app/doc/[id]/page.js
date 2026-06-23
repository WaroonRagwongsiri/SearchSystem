"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getDocument } from "@/lib/api";

// ponytail: curated field order + Thai labels for the common metadata; any other
// scalar fields still render, just after these. Nested objects are skipped.
const ORDER = [
  "subject",
  "description",
  "abstract",
  "remarkSubject",
  "branchName",
  "accountName",
  "resourceDigitalFile",
  "ownerDocumentName",
  "fullContentCodeToDisplay",
  "fullContentCode",
  "normalizeFullContentCode",
  "digitalFileID",
  "digitalFileName",
  "unitName",
  "quantityForDisplay",
  "dateRange",
  "yearType",
];

const LABELS = {
  subject: "หัวเรื่อง",
  description: "เนื้อหา",
  abstract: "บทคัดย่อ",
  remarkSubject: "หมายเหตุ",
  branchName: "หน่วยงานเก็บรักษา",
  accountName: "บัญชี",
  resourceDigitalFile: "แหล่งเอกสาร",
  ownerDocumentName: "เจ้าของเอกสาร",
  fullContentCodeToDisplay: "รหัสเนื้อหา",
  fullContentCode: "รหัสเนื้อหา (code)",
  normalizeFullContentCode: "รหัสมาตรฐาน",
  digitalFileID: "รหัสไฟล์ดิจิทัล",
  digitalFileName: "ชื่อไฟล์",
  unitName: "หน่วย",
  quantityForDisplay: "จำนวน",
  dateRange: "ช่วงปี",
  yearType: "ประเภทปี",
};

export default function DocPage() {
  const params = useParams();
  const id = params?.id;
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!id) return;
    getDocument(id).then(setDoc).catch((e) => setError(e.message));
  }, [id]);

  return (
    <div className="container">
      <Link className="back-link" href="/">
        ‹ Back to search
      </Link>
      {error && (
        <div className="state state--error" role="alert">
          <p className="state__title">Document not found</p>
          {error}
        </div>
      )}
      {!doc && !error && <p className="muted">Loading…</p>}
      {doc && <RawDoc doc={doc} />}
    </div>
  );
}

function RawDoc({ doc }) {
  const raw = doc.raw || {};
  const isBlank = (v) => v === null || v === undefined || String(v).trim() === "";
  const ordered = ORDER.filter((k) => k in raw && !isBlank(raw[k]));
  const seen = new Set(ordered);
  const rest = Object.keys(raw).filter(
    (k) => !seen.has(k) && !isBlank(raw[k]) && typeof raw[k] !== "object",
  );
  const fields = [...ordered, ...rest];

  return (
    <article>
      <h1 className="page-title serif">{raw.subject || raw.description || "เอกสาร"}</h1>
      <dl className="raw-doc">
        {fields.map((k) => (
          <div className="raw-doc__row" key={k}>
            <dt>{LABELS[k] || k}</dt>
            <dd>{String(raw[k])}</dd>
          </div>
        ))}
      </dl>
      <p className="result__id" style={{ marginTop: "var(--s-4)" }}>
        id: {doc.id}
      </p>
    </article>
  );
}
