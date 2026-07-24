import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { Health, Costs } from "../lib/api";
import { Card, Badge, Loading } from "../components/ui";
import { fmtNum, fmtTime, ago } from "../lib/format";

interface Connector { connector: string; status: string; last_success: string | null; items_24h: number; enabled: boolean; }
interface Job { id: string; name?: string; next_run_time: string | null; trigger: string; }
interface AgentRun { id: number; agent: string; model: string; started_at: string; status: string; cost_usd: number; }
interface Info { version: string; vec_available: boolean; keys_present: Record<string, boolean>; }

function statusColor(status: string, enabled: boolean): string {
  if (!enabled || status === "disabled") return "var(--gray)";
  if (status === "ok" || status === "green") return "var(--green)";
  if (status === "amber") return "var(--orange)";
  if (status === "red" || status === "error" || status === "circuit_open") return "var(--red)";
  return "var(--gray)";
}
const overallKind = (o: string) => (o === "green" ? "green" : o === "amber" ? "P1" : "P0");
const stateColor = (s: string) => (s === "exhausted" ? "var(--red)" : s === "warn" ? "var(--orange)" : "var(--green)");
const pctColor = (p: number) => (p >= 100 ? "var(--red)" : p >= 80 ? "var(--orange)" : "var(--green)");

function CostBar({ label, used, cap, pct, color }: { label: string; used: number; cap: number; pct: number; color: string }) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span className="footnote sec-label">{label}</span>
        <span className="footnote tnum">${fmtNum(used, 2)} / ${fmtNum(cap, 2)}</span>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: "var(--fill)" }}>
        <div style={{ width: `${w}%`, height: "100%", background: color, borderRadius: 4, transition: "width 500ms var(--ease-spring)" }} />
      </div>
      <div className="caption sec-label tnum">{fmtNum(pct, 1)}%</div>
    </div>
  );
}

export default function System() {
  const healthQ = useQuery({ queryKey: ["health"], queryFn: endpoints.health });
  const costsQ = useQuery({ queryKey: ["costs"], queryFn: endpoints.costs });
  const schedQ = useQuery({ queryKey: ["scheduler"], queryFn: endpoints.scheduler });
  const runsQ = useQuery({ queryKey: ["agent-runs"], queryFn: endpoints.agentRuns });
  const infoQ = useQuery({ queryKey: ["info"], queryFn: endpoints.info });

  const health = healthQ.data as Health | undefined;
  const costs = costsQ.data as Costs | undefined;
  const connectors = (health?.connectors || []) as Connector[];
  const jobs = (schedQ.data?.jobs || []) as Job[];
  const runs = (runsQ.data?.runs || []) as AgentRun[];
  const info = infoQ.data as Info | undefined;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h1 className="large-title">System</h1>
        {health && <Badge kind={overallKind(health.overall)}>{health.overall.toUpperCase()}</Badge>}
      </header>

      <Card title="Connectors">
        {healthQ.isLoading ? (
          <Loading rows={4} />
        ) : connectors.length ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
            {connectors.map((c) => (
              <div key={c.connector} className="card" style={{ borderLeft: `3px solid ${statusColor(c.status, c.enabled)}`, minWidth: 0 }}>
                <div className="subhead" style={{ fontWeight: 600 }}>{c.connector}</div>
                <div className="caption sec-label">{c.status}{!c.enabled ? " · disabled" : ""}</div>
                <div className="tnum footnote" style={{ marginTop: 8 }}>{c.items_24h ?? 0} <span className="sec-label">/ 24h</span></div>
                <div className="caption sec-label">{ago(c.last_success)}</div>
              </div>
            ))}
          </div>
        ) : (
          <Empty text="No connectors registered." />
        )}
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 18 }}>
        <Card title="LLM cost"
          action={costs && <Badge kind={costs.state === "ok" ? "green" : costs.state === "warn" ? "P1" : "P0"}>{costs.state}</Badge>}>
          {costsQ.isLoading ? (
            <Loading rows={3} />
          ) : costs ? (
            <div style={{ display: "grid", gap: 16 }}>
              <CostBar label="Today" used={costs.today_usd} cap={costs.daily_cap_usd} pct={costs.today_pct} color={stateColor(costs.state)} />
              <CostBar label="Month to date" used={costs.month_usd} cap={costs.monthly_cap_usd} pct={costs.month_pct} color={pctColor(costs.month_pct)} />
            </div>
          ) : (
            <Empty text="No cost data." />
          )}
        </Card>

        <Card title="Info">
          {infoQ.isLoading ? (
            <Loading rows={3} />
          ) : info ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span className="footnote sec-label">Version</span>
                <span className="footnote tnum">{info.version}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span className="footnote sec-label">Vector search</span>
                <span className="footnote tnum" style={{ color: info.vec_available ? "var(--green)" : "var(--gray)" }}>
                  {info.vec_available ? "available" : "off"}
                </span>
              </div>
              <div>
                <div className="footnote sec-label" style={{ marginBottom: 6 }}>API keys</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {Object.entries(info.keys_present || {}).map(([k, present]) => (
                    <span key={k} className="caption tnum" style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <span style={{ color: present ? "var(--green)" : "var(--gray)" }}>●</span>
                      {k.replace(/_api_key|_key|_token|_id/g, "").replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <Empty text="No info." />
          )}
        </Card>
      </div>

      <Card title="Scheduler">
        {schedQ.isLoading ? (
          <Loading rows={4} />
        ) : jobs.length ? (
          <div className="xscroll">
            <table className="grid">
              <thead>
                <tr><th>Job</th><th>Next run</th><th>Trigger</th></tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td>{j.name || j.id}</td>
                    <td className="tnum" style={{ whiteSpace: "nowrap" }}>{fmtTime(j.next_run_time)}</td>
                    <td className="caption sec-label">{j.trigger}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty text="Scheduler idle — no jobs queued." />
        )}
      </Card>

      <Card title="Agent runs">
        {runsQ.isLoading ? (
          <Loading rows={4} />
        ) : runs.length ? (
          <div className="xscroll">
            <table className="grid">
              <thead>
                <tr><th>Agent</th><th>Model</th><th>Status</th><th className="num-cell">Cost</th><th>Started</th></tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontWeight: 600 }}>{r.agent}</td>
                    <td className="tnum sec-label">{r.model}</td>
                    <td>
                      <span style={{ color: r.status === "ok" ? "var(--green)" : r.status === "error" ? "var(--red)" : "var(--secondaryLabel)" }}>
                        {r.status}
                      </span>
                    </td>
                    <td className="num-cell">${fmtNum(r.cost_usd, 4)}</td>
                    <td className="sec-label" style={{ whiteSpace: "nowrap" }}>{fmtTime(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty text="No agent runs logged." />
        )}
      </Card>
    </div>
  );
}

const Empty = ({ text }: { text: string }) => (
  <div className="footnote sec-label" style={{ padding: "12px 0" }}>{text}</div>
);
