export const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api"; // same-origin; proxied to http://backend:8000 by next.config.mjs rewrites

export async function search(q, { limit = 10, offset = 0, vector = true } = {}) {
  const url = `${API_URL}/search?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}&vector=${vector}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`search failed: ${res.status}`);
  return res.json();
}

export async function getDocument(id) {
  const res = await fetch(`${API_URL}/document/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`document fetch failed: ${res.status}`);
  return res.json();
}

export async function addWordMap(ancient_word, modern_definition) {
  const res = await fetch(`${API_URL}/add_new_word_map`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ancient_word, modern_definition }),
  });
  if (!res.ok) throw new Error(`add_new_word_map failed: ${res.status}`);
  return res.json();
}

export async function getDictionary({ limit = 25, offset = 0 } = {}) {
  const url = `${API_URL}/dictionary?limit=${limit}&offset=${offset}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`dictionary fetch failed: ${res.status}`);
  return res.json();
}

export async function getDocumentsByWord(word, { limit = 25, offset = 0 } = {}) {
  const url = `${API_URL}/documents_by_word?word=${encodeURIComponent(word)}&limit=${limit}&offset=${offset}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`documents_by_word failed: ${res.status}`);
  return res.json();
}

export async function reembed(docId, embed_text) {
  const res = await fetch(`${API_URL}/reembed/${encodeURIComponent(docId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ embed_text }),
  });
  const data = await res.json().catch(() => ({}));
  // 502 returns { ok:false, error }; 400/404 are FastAPI { detail } — surface either.
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || data.detail || `reembed failed: ${res.status}`);
  }
  return data;
}
