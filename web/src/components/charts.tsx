import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DailyPoint } from "@/lib/api";

const tooltipStyle = {
  contentStyle: {
    borderRadius: 14,
    border: "1px solid var(--border)",
    background: "var(--card)",
    color: "var(--foreground)",
    fontSize: 12,
    boxShadow: "var(--shadow-card)",
  },
  labelStyle: { color: "var(--muted-foreground)" },
};

const shortDate = (d: string) => {
  const dt = new Date(d);
  return `${dt.getDate()}/${dt.getMonth() + 1}`;
};

export function CoughBars({ data, height = 180 }: { data: DailyPoint[]; height?: number }) {
  const interval = data.length > 30 ? 14 : data.length > 7 ? 6 : 0;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="date" tickFormatter={shortDate} interval={interval} tickLine={false} axisLine={false} />
        <YAxis tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip {...tooltipStyle} cursor={{ fill: "var(--muted)" }} formatter={(v) => [v as number, "Coughs"]} />
        <Bar dataKey="coughs" fill="var(--primary)" radius={[6, 6, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function MetricLine({
  data,
  dataKey,
  label,
  color = "var(--chart-2)",
  height = 160,
  domain,
}: {
  data: DailyPoint[];
  dataKey: keyof DailyPoint;
  label: string;
  color?: string;
  height?: number;
  domain?: [number | string, number | string];
}) {
  const interval = data.length > 30 ? 14 : data.length > 7 ? 6 : 0;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="date" tickFormatter={shortDate} interval={interval} tickLine={false} axisLine={false} />
        <YAxis tickLine={false} axisLine={false} domain={domain ?? ["auto", "auto"]} />
        <Tooltip {...tooltipStyle} formatter={(v) => [v as number, label]} />
        <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2.2} dot={false} activeDot={{ r: 4 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function MetricArea({
  data,
  dataKey,
  label,
  color = "var(--primary)",
  height = 160,
}: {
  data: DailyPoint[];
  dataKey: keyof DailyPoint;
  label: string;
  color?: string;
  height?: number;
}) {
  const interval = data.length > 30 ? 14 : data.length > 7 ? 6 : 0;
  const id = `grad-${String(dataKey)}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="date" tickFormatter={shortDate} interval={interval} tickLine={false} axisLine={false} />
        <YAxis tickLine={false} axisLine={false} />
        <Tooltip {...tooltipStyle} formatter={(v) => [v as number, label]} />
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2.2} fill={`url(#${id})`} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function HourlyBars({ data }: { data: { hour: string; coughs: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: -28, bottom: 0 }}>
        <XAxis dataKey="hour" tickLine={false} axisLine={false} />
        <YAxis tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip {...tooltipStyle} cursor={{ fill: "var(--muted)" }} formatter={(v) => [v as number, "Coughs"]} />
        <Bar dataKey="coughs" fill="var(--primary)" radius={[6, 6, 6, 6]} maxBarSize={22} />
      </BarChart>
    </ResponsiveContainer>
  );
}
