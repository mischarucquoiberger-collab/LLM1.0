// Lightweight client for the FastAPI backend endpoints this React UI relies on.

/** Extract a clean, human-readable error message from backend responses. */
const cleanError = (text, fallback) => {
  if (!text) return fallback;
  if (text.trimStart().startsWith('<')) return fallback;
  // FastAPI JSON error responses: {"detail":"..."} or {"detail":[{...}]}
  try {
    const json = JSON.parse(text);
    if (typeof json.detail === 'string') return json.detail;
    if (Array.isArray(json.detail)) return json.detail.map((d) => d.msg || d.message || '').filter(Boolean).join('; ') || fallback;
  } catch {}
  return text.length > 200 ? text.slice(0, 200) : text;
};

const toFormBody = (payload) => {
  const params = new URLSearchParams();
  Object.entries(payload || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      params.append(key, value);
    }
  });
  return params;
};

export async function startReport({ stock_code, company_name = '', mode = 'full' }) {
  const body = toFormBody({ stock_code, company_name, mode });
  const res = await fetch('/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(cleanError(text, `Start failed with status ${res.status}`));
  }
  return res.json().catch(() => ({}));
}

export async function getStatus(jobId) {
  const res = await fetch(`/status/${jobId}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const error = new Error(cleanError(text, `Status failed with ${res.status}`));
    error.status = res.status;
    throw error;
  }
  return res.json().catch(() => ({}));
}

export const buildDownloadUrl = (filename) => filename ? `/download?file=${encodeURIComponent(filename)}` : null;
export const buildViewUrl = (filename) => filename ? `/download?inline=1&file=${encodeURIComponent(filename)}` : null;

export function subscribeToStream(jobId, { onDraft, onStage, onDone, onError } = {}) {
  const es = new EventSource(`/stream/${jobId}`);
  es.addEventListener("draft", (e) => {
    try {
      const data = JSON.parse(e.data);
      onDraft?.(data.meta?.chunk || "");
    } catch {}
  });
  es.addEventListener("draft_reset", () => onDraft?.("\0RESET"));
  es.addEventListener("stage", (e) => {
    try {
      onStage?.(JSON.parse(e.data));
    } catch {}
  });
  es.addEventListener("done", () => { onDone?.(); es.close(); });
  es.addEventListener("error", () => { onError?.("Stream connection lost"); es.close(); });
  return es;
}

/**
 * Stream report-context chat (Haiku-powered, no tools).
 * Same SSE format as streamChat but only emits text/error/done.
 */
export async function streamReportChat(jobId, messages, { onText, onError, onDone, signal, file, sources, company } = {}) {
  const payload = { messages };
  if (jobId) payload.job_id = jobId;
  if (file) payload.file = file;
  if (sources) payload.sources = sources;
  if (company) payload.company = company;

  let res;
  try {
    res = await fetch('/api/report-chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (e) {
    if (e.name === 'AbortError') return;
    onError?.(`Connection failed: ${e.message}`);
    return;
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    onError?.(cleanError(text, `Chat failed with status ${res.status}`));
    return;
  }
  if (!res.body) { onError?.('No response body'); return; }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = null;
  let finished = false;

  const processLine = (line) => {
    if (signal?.aborted || finished) return;
    if (line.startsWith('event: ')) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith('data: ') && eventType) {
      try {
        const data = JSON.parse(line.slice(6));
        if (eventType === 'text') onText?.(data.text);
        else if (eventType === 'error') { finished = true; onError?.(data.message); }
        else if (eventType === 'done') { if (!finished) { finished = true; onDone?.(); } }
      } catch {}
      eventType = null;
    } else if (line === '') {
      eventType = null;
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (buffer.trim()) buffer.split('\n').forEach(processLine);
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.forEach(processLine);
    }
  } catch (e) {
    if (e.name === 'AbortError') { try { reader.cancel(); } catch {} return; }
    try { reader.cancel(); } catch {}
    if (!finished) onError?.(`Connection lost: ${e.message}`);
    return;
  }
  if (!finished) { finished = true; onDone?.(); }
}

export async function fetchDirectors(ticker, name = '') {
  const params = new URLSearchParams({ name });
  const res = await fetch(`/api/directors/${encodeURIComponent(ticker)}?${params}`);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(cleanError(text, `Director fetch failed with status ${res.status}`));
  }
  return res.json().catch(() => ({}));
}

export async function fetchQuote(stockCode) {
  try {
    const res = await fetch(`/api/quote/${encodeURIComponent(stockCode)}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function fetchPriceHistory(stockCode, days = 90, interval = "1d") {
  try {
    const res = await fetch(`/api/price-history/${encodeURIComponent(stockCode)}?days=${days}&interval=${interval}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function deleteJob(jobId) {
  const res = await fetch(`/jobs/${jobId}`, { method: 'DELETE' });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(cleanError(text, `Delete failed with status ${res.status}`));
  }
  return res.json().catch(() => ({}));
}

/**
 * Stream a chat query to the Claude-powered backend.
 * Uses POST with ReadableStream (since EventSource only supports GET).
 */
export async function streamChat(messages, { onText, onToolCall, onToolResult, onToolProgress, onError, onDone, signal, mode } = {}) {
  let res;
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, mode: mode || "stream" }),
      signal,
    });
  } catch (e) {
    if (e.name === 'AbortError') return; // user cancelled
    onError?.(`Connection failed: ${e.message}`);
    return;
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    onError?.(cleanError(text, `Chat failed with status ${res.status}`));
    return;
  }

  if (!res.body) { onError?.('No response body'); return; }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  let errored = false;
  let eventType = null; // persist across chunks

  const fireError = (msg) => { if (!errored) { errored = true; onError?.(msg); } };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        // Process any remaining data in buffer (may contain multiple lines)
        if (buffer.trim()) {
          const remaining = buffer.split('\n');
          buffer = '';
          for (const line of remaining) {
            if (signal?.aborted || finished) break;
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ') && eventType) {
              try {
                const data = JSON.parse(line.slice(6));
                if (eventType === 'text') onText?.(data.text);
                else if (eventType === 'tool_call') onToolCall?.(data);
                else if (eventType === 'tool_result') onToolResult?.(data);
                else if (eventType === 'tool_progress') onToolProgress?.(data);
                else if (eventType === 'error') { finished = true; fireError(data.message); }
                else if (eventType === 'done') { if (!finished) { finished = true; onDone?.(); } }
              } catch {}
              eventType = null;
            } else if (line === '') {
              eventType = null;
            }
          }
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer

      for (const line of lines) {
        if (signal?.aborted || finished) break;
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ') && eventType) {
          try {
            const data = JSON.parse(line.slice(6));
            if (eventType === 'text') onText?.(data.text);
            else if (eventType === 'tool_call') onToolCall?.(data);
            else if (eventType === 'tool_result') onToolResult?.(data);
            else if (eventType === 'error') { finished = true; fireError(data.message); }
            else if (eventType === 'done') { if (!finished) { finished = true; onDone?.(); } }
          } catch {}
          eventType = null;
        } else if (line === '') {
          eventType = null; // blank line resets per SSE spec
        }
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') { try { reader.cancel(); } catch {} return; } // user cancelled
    try { reader.cancel(); } catch {} // clean up reader on any error
    fireError(`Connection lost: ${e.message}`);
    return;
  }
  if (!finished) { finished = true; onDone?.(); }
}
