// Apple-Stocks-style chart via lightweight-charts (PLAN.md §13.1).
import { createChart, ColorType, LineStyle, AreaSeries } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar } from "../lib/api";

export function PriceChart({ bars, levels = [], height = 320 }: {
  bars: Bar[]; levels?: { price: number; label: string; color?: string }[]; height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !bars.length) return;
    const styles = getComputedStyle(document.documentElement);
    const label = styles.getPropertyValue("--label").trim() || "#000";
    const sep = styles.getPropertyValue("--separator").trim();
    const first = bars[0].close;
    const last = bars[bars.length - 1].close;
    const up = last >= first;
    const green = styles.getPropertyValue("--green").trim() || "#34c759";
    const red = styles.getPropertyValue("--red").trim() || "#ff3b30";
    const color = up ? green : red;

    const chart = createChart(ref.current, {
      width: ref.current.clientWidth,
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: label, fontFamily: "var(--font-mono)" },
      grid: { horzLines: { color: sep, style: LineStyle.Dotted }, vertLines: { visible: false } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: false },
      crosshair: { mode: 1, vertLine: { labelBackgroundColor: color }, horzLine: { labelBackgroundColor: color } },
      handleScale: false, handleScroll: false,
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: color, lineWidth: 2,
      topColor: `${color}22`, bottomColor: `${color}00`,
      priceLineVisible: false, lastValueVisible: true,
    });
    series.setData(bars.map((b) => ({ time: b.date, value: b.close })));
    // dashed prev-close baseline
    series.createPriceLine({ price: first, color: sep, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
    for (const lv of levels) {
      series.createPriceLine({ price: lv.price, color: lv.color || "var(--orange)", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: lv.label });
    }
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: ref.current!.clientWidth });
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [bars, height, JSON.stringify(levels)]);
  return <div ref={ref} style={{ width: "100%" }} />;
}
