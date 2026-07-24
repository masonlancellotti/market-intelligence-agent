import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { Quote, HistoryResp } from "../lib/api";
import { Card, Delta, Badge, Loading, Segmented } from "../components/ui";
import { PriceChart } from "../components/PriceChart";
import { BriefMarkdown } from "../components/BriefMarkdown";
import { fmtPrice, fmtPct, fmtNum, fmtTime, dirClass } from "../lib/format";

interface MarketDetailResp {
  instrument: { ticker: string; name: string; kind: string; tier: string; sector?: string | null };
  quote: Quote | null;
  signals: Record<string, number>;
  dossier: { structured_json?: string; markdown?: string; updated_at?: string } | null;
}

const RANGES = ["1W", "1M", "3M", "6M", "1Y", "5Y"];

const SIGNAL_FIELDS: { key: string; label: string; fmt: (v: number) => string; color?: boolean }[] = [
  { key: "rsi14", label: "RSI (14)", fmt: (v) => fmtNum(v, 1) },
  { key: "sma50", label: "SMA 50", fmt: (v) => fmtPrice(v) },
  { key: "sma200", label: "SMA 200", fmt: (v) => fmtPrice(v) },
  { key: "atr_pct", label: "ATR %", fmt: (v) => `${fmtNum(v, 2)}%` },
  { key: "volume_z", label: "Volume Z", fmt: (v) => fmtNum(v, 2), color: true },
  { key: "pct_from_52w_high", label: "From 52W High", fmt: (v) => fmtPct(v, 1), color: true },
  { key: "macd", label: "MACD", fmt: (v) => fmtNum(v, 2), color: true },
  { key: "donchian20_upper", label: "Donchian Hi", fmt: (v) => fmtPrice(v) },
  { key: "donchian20_lower", label: "Donchian Lo", fmt: (v) => fmtPrice(v) },
];

function matKind(m: number | null | undefined): string {
  if (m == null) return "P2";
  if (m >= 4) return "P0";
  if (m >= 3) return "P1";
  return "P2";
}

export default function MarketDetail() {
  const { ticker = "" } = useParams();
  const [range, setRange] = useState("1Y");

  const detailQ = useQuery({ queryKey: ["market", ticker], queryFn: () => endpoints.marketDetail(ticker), enabled: !!ticker });
  const historyQ = useQuery({ queryKey: ["history", ticker, range], queryFn: () => endpoints.history(ticker, range), enabled: !!ticker });
  const newsQ = useQuery({ queryKey: ["news", ticker], queryFn: () => endpoints.news(`?ticker=${encodeURIComponent(ticker)}`), enabled: !!ticker });

  const detail = detailQ.data as MarketDetailResp | undefined;
  const q = detail?.quote;
  const history = historyQ.data as HistoryResp | undefined;
  const news = newsQ.data?.news || [];
  const sigFields = SIGNAL_FIELDS.filter((f) => detail?.signals?.[f.key] != null);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "grid", gap: 8 }}>
        <Link to="/markets" className="footnote accent">← Markets</Link>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
          <h1 className="large-title">{ticker}</h1>
          {detail?.instrument?.name && <span className="title3 sec-label">{detail.instrument.name}</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span className="tnum title1">{fmtPrice(q?.price)}</span>
          <Delta pct={q?.change_pct} />
          {q?.is_stale && <Badge kind="P1">STALE</Badge>}
        </div>
      </header>

      {detailQ.isError && <Card><Empty text={`Couldn't load ${ticker}.`} /></Card>}

      <Card title="Price" action={<Segmented options={RANGES} value={range} onChange={setRange} />}>
        {historyQ.isLoading ? (
          <Loading rows={6} />
        ) : history && history.bars.length ? (
          <PriceChart bars={history.bars} height={340} />
        ) : (
          <Empty text="No price history for this range." />
        )}
      </Card>

      <Card title="Signals">
        {detailQ.isLoading ? (
          <Loading rows={3} />
        ) : sigFields.length ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(148px, 1fr))", gap: 12 }}>
            {sigFields.map((f) => {
              const v = detail!.signals[f.key];
              const cls = f.color ? dirClass(v) : "";
              return (
                <div key={f.key} className="card" style={{ minWidth: 0 }}>
                  <div className="footnote sec-label">{f.label}</div>
                  <div className={`tnum title3 ${cls}`} style={{ marginTop: 4 }}>{f.fmt(v)}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <Empty text="No signals computed yet." />
        )}
      </Card>

      {detail?.dossier?.markdown && (
        <Card title="Dossier" hero>
          <BriefMarkdown markdown={detail.dossier.markdown} evidence={{}} />
        </Card>
      )}

      <Card title="News">
        {newsQ.isLoading ? (
          <Loading rows={4} />
        ) : news.length ? (
          <div style={{ display: "grid" }}>
            {news.map((n) => (
              <a key={n.id} href={n.url} target="_blank" rel="noreferrer" className="hairline"
                style={{ display: "flex", gap: 12, padding: "10px 0", alignItems: "flex-start" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="subhead">{n.title}</div>
                  <div className="caption sec-label" style={{ marginTop: 2 }}>{n.source} · {fmtTime(n.published_at)}</div>
                </div>
                {n.materiality != null && <Badge kind={matKind(n.materiality)}>M{n.materiality}</Badge>}
              </a>
            ))}
          </div>
        ) : (
          <Empty text="No recent news for this ticker." />
        )}
      </Card>
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>
);
