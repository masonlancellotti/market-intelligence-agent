import { useState } from "react";
import { Card, Badge, Delta, Segmented, StatTile, Sparkline } from "../components/ui";
import { RegimeGauge } from "../components/RegimeGauge";

const COLORS: { name: string; v: string; border?: boolean }[] = [
  { name: "systemBackground", v: "--systemBackground", border: true },
  { name: "secondarySystemBackground", v: "--secondarySystemBackground", border: true },
  { name: "label", v: "--label" },
  { name: "secondaryLabel", v: "--secondaryLabel" },
  { name: "separator", v: "--separator" },
  { name: "fill", v: "--fill" },
  { name: "blue", v: "--blue" },
  { name: "green", v: "--green" },
  { name: "red", v: "--red" },
  { name: "orange", v: "--orange" },
  { name: "yellow", v: "--yellow" },
  { name: "teal", v: "--teal" },
  { name: "indigo", v: "--indigo" },
  { name: "purple", v: "--purple" },
  { name: "gray", v: "--gray" },
];

const TYPE_SCALE = [
  "large-title", "title1", "title2", "title3", "headline",
  "callout", "subhead", "footnote", "caption",
];

const SPARK = [1, 3, 2, 5, 4, 6, 5, 7];

export default function Design() {
  const [seg, setSeg] = useState("1M");

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header>
        <h1 className="large-title">Design</h1>
        <div className="subhead sec-label">Component gallery · design-system QA</div>
      </header>

      <Card title="Color palette">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 12 }}>
          {COLORS.map((c) => (
            <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{
                width: 34, height: 34, borderRadius: 8, flex: "none",
                background: `var(${c.v})`,
                boxShadow: c.border ? "inset 0 0 0 0.5px var(--separator)" : "none",
              }} />
              <span className="caption tnum" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Type scale">
        <div style={{ display: "grid", gap: 8 }}>
          {TYPE_SCALE.map((t) => (
            <div key={t} style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
              <span className="caption sec-label tnum" style={{ width: 96, flex: "none" }}>{t}</span>
              <span className={t}>The quick brown fox — 0123456789</span>
            </div>
          ))}
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 18 }}>
        <Card title="Badges">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <Badge kind="P0">P0</Badge>
            <Badge kind="P1">P1</Badge>
            <Badge kind="P2">P2</Badge>
            <Badge kind="green">green</Badge>
            <Badge kind="blue">blue</Badge>
          </div>
        </Card>

        <Card title="Delta">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
            <Delta pct={1.24} />
            <Delta pct={-0.87} />
            <Delta pct={0} />
            <Delta pct={null} />
          </div>
        </Card>

        <Card title="Segmented">
          <Segmented options={["1W", "1M", "3M", "1Y"]} value={seg} onChange={setSeg} />
          <div className="caption sec-label tnum" style={{ marginTop: 10 }}>selected: {seg}</div>
        </Card>

        <Card title="Sparkline">
          <Sparkline data={SPARK} width={200} height={44} />
        </Card>
      </div>

      <Card title="StatTiles">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
          <StatTile label="S&P 500" value="6,204.95" delta={0.42} />
          <StatTile label="US 10Y" value="4.19%" delta={-1.31} />
          <StatTile label="VIX" value="16.4" delta={3.02} sub="fear gauge" />
          <StatTile label="Coverage" value="8 / 8" sub="regime inputs" />
        </div>
      </Card>

      <Card title="Regime gauge">
        <div style={{ maxWidth: 260 }}>
          <RegimeGauge score={71} bucket="Risk-On" history={[48, 52, 55, 60, 58, 64, 68, 71]} />
        </div>
      </Card>
    </div>
  );
}
