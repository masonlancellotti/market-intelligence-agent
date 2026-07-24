import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { RuleStat, RuleCalibration } from "../lib/api";
import { Card, StatTile, Loading, Info, RetroPill } from "../components/ui";
import { ReliabilityCurve } from "../components/labcharts";

export default function CalibrationLab() {
  const q = useQuery({ queryKey: ["rule-calibration"], queryFn: endpoints.ruleCalibration });
  const [open, setOpen] = useState<string | null>(null);

  const skillColor = (s: number | null | undefined) =>
    s == null ? "var(--secondaryLabel)" : s > 0.02 ? "var(--green)" : s < -0.02 ? "var(--orange)" : "var(--secondaryLabel)";

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "start", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <div style={{ maxWidth: "62ch" }}>
          <h1 className="large-title" style={{ textWrap: "balance" }}>Calibration lab</h1>
          <div className="subhead sec-label" style={{ textWrap: "pretty", marginTop: 2 }}>
            Can simple market rules actually forecast? Each rule makes a probability call — say,
            <em> "after a fear spike, a 62% chance the market is up in a month"</em> — and we replay every time it
            fired in history to score how honest those probabilities really were.
          </div>
        </div>
        <RetroPill text="A backtest over historical data — not live forecasts, not trading advice." />
      </header>

      {q.isError ? (
        <Card><Err onRetry={() => q.refetch()} /></Card>
      ) : q.isLoading ? (
        <Card><Loading rows={6} /></Card>
      ) : !q.data || !q.data.pooled.n ? (
        <Card><Empty /></Card>
      ) : (
        <>
          <Takeaway data={q.data} />

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(168px, 1fr))", gap: 12 }}>
            <Tile label="Predictions tested" value={q.data.pooled.n?.toLocaleString()} sub="every historical instance"
              info="Total number of times any rule fired and could be checked against what the market actually did next." />
            <Tile label="Brier score" value={q.data.pooled.mean_brier?.toFixed(3)} sub="lower is better"
              info="How close the probability calls landed to reality. 0 = perfect, 0.25 = a coin flip. Lower is better." />
            <Tile label="Base rate" value={pct(q.data.pooled.base_rate)} sub="how often it happened"
              info="How often the predicted outcome occurred at all — the bar any real edge has to beat." />
            <Tile label="Skill vs. guessing" value={q.data.pooled.skill_score?.toFixed(3) ?? "—"} sub="0 = no edge"
              valueColor={skillColor(q.data.pooled.skill_score)}
              info="Did the rules beat simply predicting the base rate every time? Above 0 = real edge, below 0 = worse than guessing, near 0 = no edge." />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(300px, 380px) minmax(0, 1fr)", gap: 18 }} className="lab-grid">
            <Card title="Are the probabilities honest?">
              <p className="footnote sec-label" style={{ marginTop: -4, marginBottom: 12, textWrap: "pretty" }}>
                Each dot is a confidence level. If a rule says "60%" and the outcome happened 60% of the time, the dot
                sits on the dashed line — perfectly calibrated. Bigger dots = more predictions behind them.
              </p>
              <ReliabilityCurve points={q.data.pooled.reliability} />
              <p className="caption sec-label" style={{ marginTop: 10, textWrap: "pretty" }}>
                Above the line = the outcome happened <em>more</em> often than the rule predicted; below = less often.
              </p>
            </Card>

            <Card title="Rule-by-rule scorecard" action={<span className="footnote sec-label">{q.data.n_rules} rules · tap a row</span>}>
              <div style={{ overflowX: "auto" }}>
                <table className="lab-table">
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th>Looks ahead<Info label="Looks ahead" text="How far into the future the rule's call applies." /></th>
                      <th>Tests<Info label="Tests" text="How many times this rule fired in history." /></th>
                      <th>Said<Info label="Said" text="The probability the rule assigned to its outcome." /></th>
                      <th>Happened<Info label="Happened" text="How often the outcome actually occurred." /></th>
                      <th>Brier<Info label="Brier" text="Accuracy of this rule's probability calls. Lower is better (0.25 = coin flip)." /></th>
                      <th>Skill<Info label="Skill" text="Better (>0) or worse (<0) than always guessing the base rate." /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {q.data.by_rule.map((r) => (
                      <RuleRow key={r.rule_id} r={r} open={open === r.rule_id}
                        onToggle={() => setOpen(open === r.rule_id ? null : r.rule_id)} skillColor={skillColor} />
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <p className="caption sec-label" style={{ lineHeight: 1.5, textWrap: "pretty" }}>{q.data.label}</p>
        </>
      )}
    </div>
  );
}

// Lead with the honest headline computed from the pooled result.
function Takeaway({ data }: { data: RuleCalibration }) {
  const skill = data.pooled.skill_score ?? 0;
  const verb = skill > 0.03 ? "genuinely beat" : skill < -0.03 ? "trailed" : "roughly matched";
  return (
    <div className="takeaway">
      <span className="mark" aria-hidden="true">✦</span>
      <div className="lede">
        Across <strong>{data.pooled.n?.toLocaleString()} historical calls</strong>, these {data.n_rules} transparent rules
        {" "}<strong>{verb}</strong> a naive base-rate guess (skill score {data.pooled.skill_score?.toFixed(3)}). That's the
        honest result — visible rules, real scores, no manufactured edge. Tap any rule below to see exactly what it claims.
      </div>
    </div>
  );
}

function RuleRow({ r, open, onToggle, skillColor }:
  { r: RuleStat; open: boolean; onToggle: () => void; skillColor: (s: number | null | undefined) => string }) {
  const realized = r.reliability.reduce((a, p) => a + p.realized * p.n, 0) / Math.max(1, r.n);
  return (
    <>
      <tr onClick={onToggle} className={`rule-row ${open ? "open" : ""}`} style={{ cursor: "pointer" }}
        tabIndex={0} role="button" aria-expanded={open}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}>
        <td><span className="mono-id">{prettyRule(r.rule_id)}</span></td>
        <td>{r.horizon}d</td>
        <td>{r.n}</td>
        <td>{pct(r.mean_prob)}</td>
        <td>{pct(realized)}</td>
        <td>{r.mean_brier?.toFixed(3)}</td>
        <td style={{ color: skillColor(r.skill_score) }}>{r.skill_score?.toFixed(3) ?? "—"}</td>
      </tr>
      {open && (
        <tr className="rule-detail">
          <td colSpan={7}>
            <div style={{ padding: "6px 2px 12px", display: "grid", gap: 8 }}>
              {r.rationale && <div className="subhead" style={{ textWrap: "pretty" }}>{r.rationale}</div>}
              <div className="footnote sec-label" style={{ textWrap: "pretty" }}>
                Fires when <code className="lab-code">{r.when}</code>, then predicts <code className="lab-code">{r.predict}</code>{" "}
                over the next {r.horizon} trading days.
              </div>
              <div className="caption sec-label">
                It happened {pct(r.base_rate)} of the time overall; this rule said {pct(r.mean_prob)} on average.
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const prettyRule = (id: string) => id.replace(/_/g, " ");

function Tile({ label, value, sub, info, valueColor }:
  { label: string; value?: string; sub: string; info: string; valueColor?: string }) {
  return (
    <div className="card" style={{ minWidth: 0 }}>
      <div className="footnote sec-label" style={{ marginBottom: 6, display: "flex", alignItems: "center" }}>
        {label}<Info label={label} text={info} />
      </div>
      <div className="tnum title2" style={{ letterSpacing: "-0.01em", color: valueColor }}>{value}</div>
      <div className="caption sec-label" style={{ marginTop: 4 }}>{sub}</div>
    </div>
  );
}

function Empty() {
  return (
    <div style={{ padding: "8px 0" }}>
      <div className="subhead">No backtest yet.</div>
      <div className="footnote sec-label" style={{ marginTop: 6, textWrap: "pretty" }}>
        Score the rulebook over history in two commands (no API keys needed):
      </div>
      <code className="lab-code" style={{ display: "inline-block", marginTop: 8 }}>python manage.py backfill-regime --years 2</code>{" "}
      <code className="lab-code" style={{ display: "inline-block", marginTop: 8 }}>python manage.py backtest-rules</code>
    </div>
  );
}

function Err({ onRetry }: { onRetry: () => void }) {
  return (
    <div style={{ padding: "12px 0" }}>
      <div className="subhead">Couldn't load the rule backtest.</div>
      <div className="footnote sec-label" style={{ marginTop: 4 }}>The daemon may still be starting up.</div>
      <button className="segmented" style={{ marginTop: 10, padding: "6px 14px" }} onClick={onRetry}>Try again</button>
    </div>
  );
}
