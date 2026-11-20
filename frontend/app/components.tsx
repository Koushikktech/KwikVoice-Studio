import { AlertCircle, ArrowDownRight, Braces, Check, ChevronDown, Circle, Info, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { Turn, ToolOutcome } from "./api";

export function Panel({ title, label, actions, children, className = "" }: {
  title: string; label?: string; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return <section className={"panel " + className}>
    <div className="panel-heading">
      <div className="panel-title"><Braces size={14} aria-hidden="true" /><h2>{title}</h2>{label && <span className="mono muted panel-label">{label}</span>}</div>
      {actions && <div className="panel-actions">{actions}</div>}
    </div>
    {children}
  </section>;
}

export function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  const Icon = error ? AlertCircle : Info;
  return <div className={"notice " + (error ? "error" : "")} role={error ? "alert" : "status"}>
    <Icon size={16} aria-hidden="true" /><div>{children}</div>
  </div>;
}

export function Select({ label, children, ...props }: { label: string; children: ReactNode } & React.ComponentPropsWithoutRef<"select">) {
  return <label className="select-field">
    <span>{label}</span>
    <span className="select-control"><select {...props}>{children}</select><ChevronDown size={14} aria-hidden="true" /></span>
  </label>;
}

export function Spin() {
  return <LoaderCircle size={15} className="spin" aria-hidden="true" />;
}

export function Empty({ children, icon = "circle" }: { children: ReactNode; icon?: "circle" | "arrow" }) {
  const Icon = icon === "arrow" ? ArrowDownRight : Circle;
  return <div className="empty"><Icon size={18} aria-hidden="true" /><p>{children}</p></div>;
}

export function Transcript({ turns, failed = [], shopper = "Shopper" }: { turns: Turn[]; failed?: number[]; shopper?: string }) {
  return <ol className="transcript">
    {turns.map((turn) => <li className={turn.speaker === "agent" && failed.includes(turn.turn) ? "bad-turn" : ""}
      key={turn.turn + turn.speaker}>
      <div className="turn-meta">
        <span className={turn.speaker === "agent" ? "agent-tag" : ""}>{turn.speaker === "agent" ? "Agent" : shopper}</span>
        <span className="muted">Turn {turn.turn}</span>
        {typeof turn.words === "number" && <span className={turn.words > 18 ? "warn" : "muted"}>{turn.words} words</span>}
      </div>
      <p>{turn.text}</p>
    </li>)}
  </ol>;
}

export function ToolEvents({ tools }: { tools: ToolOutcome[] }) {
  return <ol className="tool-list">
    {tools.map((tool, index) => <li key={tool.turn + tool.name + index}>
      <div className="tool-name">
        {tool.ok ? <Check size={14} className="good" aria-hidden="true" /> : <AlertCircle size={14} className="warn" aria-hidden="true" />}
        <code>{tool.name}</code>
      </div>
      <p>{tool.message} <span className="muted">Turn {tool.turn}</span></p>
      <details><summary>{tool.ok ? "Mock 200 OK" : "Mock 422 blocked"} · Payload</summary><pre>{JSON.stringify({ arguments: tool.args, result: tool.card ?? tool.message }, null, 2)}</pre></details>
    </li>)}
  </ol>;
}
