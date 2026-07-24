// Typed API client for meridiand (PLAN.md §13.3). All endpoints under /api/*.

export async function api<T = any>(path: string): Promise<T> {
  const r = await fetch(path.startsWith("/api") ? path : `/api${path}`);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

// ---- shared types (mirror the backend payloads) ----
export interface Quote {
  ticker: string; name: string; kind: string; tier: string; sector?: string;
  price: number | null; prev_close: number | null; day_open?: number | null;
  day_high?: number | null; day_low?: number | null; volume?: number | null;
  change_pct: number | null; is_stale: boolean | null; ts: string | null; source?: string;
}
export interface MarketsResp { instruments: Quote[]; by_tier: Record<string, Quote[]>; count: number; }

export interface Regime {
  score: number | null; bucket: string; prev_bucket?: string;
  components?: Record<string, number>; coverage?: number; at?: string;
}
export interface Breadth {
  pct_above_50dma?: number; pct_above_200dma?: number; advancers?: number; decliners?: number;
  new_20d_highs?: number; new_20d_lows?: number; net_new_highs?: number; universe_size?: number;
  sector_rs?: { ticker: string; ret_1m: number | null; ret_3m: number | null }[];
  correlation_shifts?: { pair: string[]; corr_now: number; corr_prev: number; delta: number }[];
}
export interface Alert {
  id?: number; rule_id: string; priority: string; title: string; body: string;
  fired_at: string; ticker?: string | null;
}
export interface SignalsResp { regime: Regime | null; breadth: Breadth | null; noise_governor: any; alerts: Alert[]; }

export interface Bar { date: string; open: number; high: number; low: number; close: number; volume: number; }
export interface HistoryResp { ticker: string; range: string; bars: Bar[]; count: number; }

export interface NewsItem {
  id: number; source: string; url: string; title: string; summary?: string;
  published_at: string; tickers: string[]; materiality: number | null; category?: string; cluster_id?: number;
}
export interface Filing {
  id: number; ticker: string; form: string; filed_at: string; url: string;
  items: string[]; materiality: number | null; summary?: string;
}
export interface Insider {
  id: number; ticker: string; insider_name: string; role: string; action: string;
  shares: number; price: number; value_usd: number; traded_at: string; cluster_flag: number;
}
export interface MacroResp {
  series: Record<string, { value: number; date: string; prev: number | null }>;
  fed_odds: { venue: string; question: string; yes_prob: number; prev_prob: number | null }[];
  cnn_fng: { score: number; rating: string } | null;
  crypto_fng: { value: number; label: string } | null;
  crypto_global?: any;
  upcoming_events: { name: string; scheduled_at: string; importance: string; consensus?: string; previous?: string }[];
}
export interface BriefMeta {
  id: number; kind: string; for_date: string; model: string; cost_usd: number;
  created_at: string; delivered_at: string | null; audio_path: string | null;
}
export interface Brief extends BriefMeta {
  markdown: string; evidence: Record<string, any>; factcheck: any;
}
export interface Health {
  overall: string; ts: string; scheduler: { ok: boolean; age_s: number | null };
  db_writable: boolean; disk_pct: number | null;
  connectors: { connector: string; status: string; last_success: string | null; items_24h: number; enabled: boolean }[];
  connector_summary: { red: number; amber: number; total: number };
}
export interface Costs {
  today_usd: number; daily_cap_usd: number; today_pct: number;
  month_usd: number; monthly_cap_usd: number; month_pct: number; state: string;
  by_agent_7d: { agent: string; n: number; cost: number }[];
}

export const endpoints = {
  markets: () => api<MarketsResp>("/markets"),
  marketDetail: (t: string) => api(`/markets/${encodeURIComponent(t)}`),
  history: (t: string, range: string) => api<HistoryResp>(`/markets/${encodeURIComponent(t)}/history?range=${range}`),
  signals: () => api<SignalsResp>("/signals"),
  regimeHistory: () => api<{ history: { date: string; score: number; bucket: string }[] }>("/signals/regime/history"),
  news: (q = "") => api<{ news: NewsItem[]; count: number }>(`/news${q}`),
  filings: (q = "") => api<{ filings: Filing[]; count: number }>(`/filings${q}`),
  insiders: () => api<{ insiders: Insider[]; clusters: any[] }>("/filings/insiders"),
  macro: () => api<MacroResp>("/macro"),
  briefs: (kind = "") => api<{ briefs: BriefMeta[] }>(`/briefs${kind ? `?kind=${kind}` : ""}`),
  brief: (id: number) => api<{ brief: Brief }>(`/briefs/${id}`),
  latestBrief: (kind = "morning") => api<{ brief: Brief | null }>(`/briefs/latest?kind=${kind}`),
  health: () => api<Health>("/health"),
  costs: () => api<Costs>("/system/costs"),
  agentRuns: () => api<{ runs: any[] }>("/system/agent-runs"),
  scheduler: () => api<{ running: boolean; jobs: any[] }>("/system/scheduler"),
  info: () => api<any>("/system/info"),
  memos: (status = "") => api<{ kanban: Record<string, Memo[]> }>(`/memos${status ? `?status=${status}` : ""}`),
  memo: (id: number) => api<{ memo: Memo }>(`/memos/${id}`),
  journal: () => api<{ entries: JournalEntry[]; calibration: Calibration }>("/journal"),
  calibration: () => api<Calibration>("/calibration"),
};

export interface Memo {
  id: number; ticker: string; direction: string; status: string; thesis: string;
  edge_type?: string; invalidation_level?: number | null; redteam_verdict?: any;
  gate?: { score: number; passes: boolean; gate_min: number; breakdown: Record<string, any> };
  gate_score?: number; predictions?: Prediction[]; journal?: JournalEntry[]; created_at?: string;
  catalysts?: string[]; risks?: string[]; valuation?: any; entry_plan?: string; size_plan?: string;
}
export interface Prediction {
  id: number; claim: string; probability: number; horizon_date: string;
  resolution: string | null; brier: number | null;
}
export interface JournalEntry {
  id: number; ts: string; kind: string; memo_id: number | null; markdown: string; ticker?: string;
}
export interface Calibration {
  n: number; mean_brier: number | null; hit_rate: number | null;
  calibration: { bucket: string; n: number; predicted: number; realized: number }[];
}
