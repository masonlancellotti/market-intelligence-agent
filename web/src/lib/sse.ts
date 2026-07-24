// Single SSE channel hook (PLAN.md §13.3): quote / alert / brief_ready / health.
import { useEffect, useRef, useState } from "react";

export type SSEEvent = { event: string; data: any };

export function useSSE(onEvent?: (e: SSEEvent) => void) {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    const es = new EventSource("/api/sse");
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    const handle = (name: string) => (ev: MessageEvent) => {
      let data: any = {};
      try { data = JSON.parse(ev.data); } catch { /* ping */ }
      cb.current?.({ event: name, data });
    };
    for (const name of ["hello", "quote", "alert", "brief_ready", "health", "ping"]) {
      es.addEventListener(name, handle(name));
    }
    return () => es.close();
  }, []);

  return { connected };
}

// A store of latest live quotes keyed by ticker, fed by SSE `quote` events.
export function useLiveQuotes() {
  const [quotes, setQuotes] = useState<Record<string, { price: number; change_pct: number | null }>>({});
  const { connected } = useSSE((e) => {
    if (e.event === "quote" && e.data?.ticker) {
      setQuotes((q) => ({ ...q, [e.data.ticker]: { price: e.data.price, change_pct: e.data.change_pct } }));
    }
  });
  return { quotes, connected };
}
