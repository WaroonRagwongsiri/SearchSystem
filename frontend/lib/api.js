export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function search(q, { limit = 10, offset = 0, vector = true } = {}) {
  const url = `${API_URL}/search?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}&vector=${vector}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`search failed: ${res.status}`);
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
