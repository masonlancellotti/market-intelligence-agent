// Brief renderer with evidence hover-cards (PLAN.md §13.2). Minimal markdown → JSX,
// with [type:id] evidence markers turned into hover chips backed by the evidence map.
import { useState } from "react";

function EvidenceChip({ id, evidence }: { id: string; evidence: Record<string, any> }) {
  const [open, setOpen] = useState(false);
  const ev = evidence[id];
  return (
    <span style={{ position: "relative", display: "inline-block" }}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <sup className="accent caption" style={{ cursor: "help", marginLeft: 1 }}>[{id.split(":")[0]}]</sup>
      {open && ev && (
        <span className="card material" style={{
          position: "absolute", bottom: "1.4em", left: 0, zIndex: 30, minWidth: 220, maxWidth: 320,
          padding: 10, borderRadius: 10, boxShadow: "var(--card-shadow)",
        }}>
          <span className="caption sec-label" style={{ display: "block" }}>{id} · {ev.source || ev.kind}</span>
          <span className="subhead" style={{ display: "block", marginTop: 4 }}>{ev.label ?? String(ev.value)}</span>
          {ev.value != null && <span className="tnum footnote accent" style={{ display: "block", marginTop: 2 }}>{String(ev.value)}</span>}
        </span>
      )}
    </span>
  );
}

function inline(text: string, evidence: Record<string, any>, key: string) {
  // split on [type:id] and **bold**
  const parts: any[] = [];
  const re = /\[([a-z]):([^\]]+)\]|\*\*([^*]+)\*\*|_([^_]+)_/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1]) parts.push(<EvidenceChip key={`${key}-${i}`} id={`${m[1]}:${m[2]}`} evidence={evidence} />);
    else if (m[3]) parts.push(<strong key={`${key}-${i}`}>{m[3]}</strong>);
    else if (m[4]) parts.push(<em key={`${key}-${i}`} className="sec-label">{m[4]}</em>);
    last = re.lastIndex; i++;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function BriefMarkdown({ markdown, evidence = {} }: { markdown: string; evidence?: Record<string, any> }) {
  const lines = markdown.split("\n");
  const out: any[] = [];
  let table: string[][] | null = null;

  const flushTable = (k: string) => {
    if (!table) return;
    const [head, , ...rows] = table;
    out.push(
      <div key={k} className="xscroll" style={{ margin: "8px 0" }}>
        <table className="grid">
          <thead><tr>{head.map((h, i) => <th key={i}>{h.trim()}</th>)}</tr></thead>
          <tbody>{rows.map((r, ri) => (
            <tr key={ri}>{r.map((c, ci) => <td key={ci} className={ci > 0 ? "num-cell" : ""}>{inline(c.trim(), evidence, `${k}-${ri}-${ci}`)}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
    );
    table = null;
  };

  lines.forEach((ln, i) => {
    const k = `l${i}`;
    if (ln.trim().startsWith("|")) {
      const cells = ln.split("|").slice(1, -1);
      (table ||= []).push(cells);
      return;
    }
    flushTable(`t${i}`);
    if (ln.startsWith("# ")) out.push(<h1 key={k} className="title1" style={{ margin: "4px 0 8px" }}>{inline(ln.slice(2), evidence, k)}</h1>);
    else if (ln.startsWith("## ")) out.push(<h2 key={k} className="title3 accent" style={{ margin: "18px 0 6px" }}>{inline(ln.slice(3), evidence, k)}</h2>);
    else if (ln.startsWith("### ")) out.push(<h3 key={k} className="headline" style={{ margin: "12px 0 4px" }}>{inline(ln.slice(4), evidence, k)}</h3>);
    else if (ln.startsWith("- ") || ln.startsWith("* ")) out.push(<li key={k} className="callout" style={{ margin: "3px 0 3px 18px" }}>{inline(ln.slice(2), evidence, k)}</li>);
    else if (ln.startsWith("> ")) out.push(<blockquote key={k} className="callout" style={{ borderLeft: "3px solid var(--orange)", paddingLeft: 12, margin: "8px 0", color: "var(--secondaryLabel)" }}>{inline(ln.slice(2), evidence, k)}</blockquote>);
    else if (ln.trim() === "---") out.push(<hr key={k} className="hairline" style={{ border: 0, margin: "14px 0" }} />);
    else if (ln.trim()) out.push(<p key={k} className="body" style={{ margin: "6px 0" }}>{inline(ln, evidence, k)}</p>);
  });
  flushTable("tend");
  return <div>{out}</div>;
}
