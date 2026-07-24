import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { Filing, Insider } from "../lib/api";
import { Card, Badge, Loading, Segmented } from "../components/ui";
import { fmtNum, fmtCompact, fmtTime } from "../lib/format";

interface Cluster { ticker: string; n: number; total: number; }

function matKind(m: number | null | undefined): string {
  if (m == null) return "P2";
  if (m >= 4) return "P0";
  if (m >= 3) return "P1";
  return "P2";
}

function actionColor(a: string): string {
  const u = (a || "").toUpperCase();
  return u === "P" ? "var(--green)" : u === "S" ? "var(--red)" : "var(--secondaryLabel)";
}

export default function Filings() {
  const [form, setForm] = useState("All");
  const filingsQ = useQuery({ queryKey: ["filings"], queryFn: () => endpoints.filings() });
  const insidersQ = useQuery({ queryKey: ["insiders"], queryFn: endpoints.insiders });

  const filings = filingsQ.data?.filings || [];
  const insiders = insidersQ.data?.insiders || [];
  const clusters = (insidersQ.data?.clusters || []) as Cluster[];

  const forms = Array.from(new Set(filings.map((f) => f.form))).slice(0, 6);
  const formOptions = ["All", ...forms];
  const shownFilings = form === "All" ? filings : filings.filter((f) => f.form === form);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h1 className="large-title">Filings</h1>
        {forms.length > 1 && <Segmented options={formOptions} value={form} onChange={setForm} />}
      </header>

      <Card title="Filing stream">
        {filingsQ.isLoading ? (
          <Loading rows={6} />
        ) : shownFilings.length ? (
          <div className="xscroll">
            <table className="grid">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Form</th>
                  <th>Filed</th>
                  <th>Materiality</th>
                  <th>Items</th>
                </tr>
              </thead>
              <tbody>
                {shownFilings.map((f: Filing) => (
                  <tr key={f.id}>
                    <td><Link to={`/markets/${f.ticker}`} style={{ fontWeight: 600 }}>{f.ticker}</Link></td>
                    <td className="tnum">{f.form}</td>
                    <td className="sec-label" style={{ whiteSpace: "nowrap" }}>{fmtTime(f.filed_at)}</td>
                    <td><Badge kind={matKind(f.materiality)}>M{f.materiality ?? "—"}</Badge></td>
                    <td className="sec-label" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {f.items?.length ? f.items.join(", ") : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty text="No filings in the stream yet." />
        )}
      </Card>

      <Card title="Insider activity">
        {insidersQ.isLoading ? (
          <Loading rows={6} />
        ) : (
          <>
            {clusters.length > 0 && (
              <div className="card" style={{ marginBottom: 12, background: "color-mix(in srgb, var(--orange) 12%, var(--secondarySystemBackground))" }}>
                <div className="footnote sec-label" style={{ marginBottom: 6 }}>Insider clusters</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
                  {clusters.map((c) => (
                    <Link key={c.ticker} to={`/markets/${c.ticker}`} style={{ display: "inline-flex", alignItems: "baseline", gap: 6 }}>
                      <span className="headline">{c.ticker}</span>
                      <span className="footnote tnum sec-label">{c.n}× · {fmtCompact(c.total)}</span>
                    </Link>
                  ))}
                </div>
              </div>
            )}
            {insiders.length ? (
              <div className="xscroll">
                <table className="grid">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th>Insider</th>
                      <th>Role</th>
                      <th>Action</th>
                      <th className="num-cell">Shares</th>
                      <th className="num-cell">Value</th>
                      <th>Traded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {insiders.map((t: Insider) => (
                      <tr key={t.id}>
                        <td><Link to={`/markets/${t.ticker}`} style={{ fontWeight: 600 }}>{t.ticker}</Link></td>
                        <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.insider_name}</td>
                        <td className="sec-label" style={{ whiteSpace: "nowrap" }}>{t.role}</td>
                        <td style={{ fontWeight: 700, color: actionColor(t.action) }}>{t.action}</td>
                        <td className="num-cell">{fmtNum(t.shares, 0)}</td>
                        <td className="num-cell">{fmtCompact(t.value_usd)}</td>
                        <td className="sec-label" style={{ whiteSpace: "nowrap" }}>{fmtTime(t.traded_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty text="No insider trades recorded." />
            )}
          </>
        )}
      </Card>
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>
);
