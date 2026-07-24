import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "../lib/api";
import type { Brief } from "../lib/api";
import { Card, Badge, Loading } from "../components/ui";
import { BriefMarkdown } from "../components/BriefMarkdown";
import { fmtDate, fmtNum } from "../lib/format";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace("_", " ");

interface FactCheck {
  ok?: boolean;
  missing_markers?: string[];
  numeric_mismatches?: unknown[];
  checked_numbers?: number;
}

function FactBadge({ fc }: { fc: FactCheck }) {
  if (fc.ok === true) return <Badge kind="green">Verified</Badge>;
  if (fc.ok === false) {
    const issues = (fc.missing_markers?.length || 0) + (fc.numeric_mismatches?.length || 0);
    return <Badge kind="P1">Unverified · {issues}</Badge>;
  }
  return <Badge kind="P2">No fact-check</Badge>;
}

export default function BriefDetail() {
  const { id = "" } = useParams();
  const briefQ = useQuery({ queryKey: ["brief", id], queryFn: () => endpoints.brief(Number(id)), enabled: !!id });
  const brief = briefQ.data?.brief as Brief | undefined;
  const fc = (brief?.factcheck || {}) as FactCheck;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "grid", gap: 8 }}>
        <Link to="/briefs" className="footnote accent">← Briefs</Link>
        {brief && (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
              <h1 className="large-title">{cap(brief.kind)} brief</h1>
              <span className="title3 sec-label">{fmtDate(brief.for_date)}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <FactBadge fc={fc} />
              <span className="footnote sec-label tnum">{brief.model}</span>
              <span className="footnote sec-label tnum">${fmtNum(brief.cost_usd, 4)}</span>
              {fc.checked_numbers != null && (
                <span className="caption sec-label tnum">{fc.checked_numbers} numbers checked</span>
              )}
            </div>
          </>
        )}
      </header>

      <Card hero>
        {briefQ.isLoading ? (
          <Loading rows={10} />
        ) : brief ? (
          <BriefMarkdown markdown={brief.markdown} evidence={brief.evidence} />
        ) : (
          <div className="footnote sec-label" style={{ padding: "12px 0" }}>Brief not found.</div>
        )}
      </Card>
    </div>
  );
}
