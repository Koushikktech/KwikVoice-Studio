export const API = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export type Flow = "cart-recovery" | "cod-confirmation";
export type Engine = "fixture" | "gemini";
export type Mode = "replay" | "text" | "live";
export type Preset = { merchant: { id: string; name: string }; cart: { id: string } };
export type Persona = { id: string; name: string; title: string; description: string; challenge: string };
export type Settings = {
  presets: Preset[];
  personas: Persona[];
  gemini: { available: boolean; text_model: string; judge_model: string; live_model: string };
};
export type Diagnostic = { line: number; code: string; message: string; fixable: boolean };
export type Lint = { diagnostics: Diagnostic[]; score: number; fixed_prompt: string };
export type Context = {
  cart_id: string;
  first_name: string;
  merchant_name: string;
  products: string[];
  price: Record<"cod" | "upi" | "savings" | "subtotal" | "cod_fee", string>;
  spoken: Record<string, string>;
  discount_percent: number;
  waives_fee: boolean;
  rounding: string;
};
export type Turn = { turn: number; speaker: "shopper" | "agent"; text: string; words?: number; final?: boolean };
export type ToolOutcome = {
  turn: number;
  name: string;
  ok: boolean;
  message: string;
  args: Record<string, unknown>;
  card?: {
    kind: "checkout" | "cod" | "callback";
    cart_id: string;
    amount?: string;
    savings?: string;
    discount_percent?: number;
    url?: string;
  };
};
export type Check = { label: string; detail: string; passed: boolean; turn: number; category: string; root_cause?: string };
export type Verdict = {
  persona_id: string;
  passed: boolean | null;
  checks: Check[];
  transcript: Turn[];
  tools: ToolOutcome[];
  error?: string;
};
export type Score = { passed: number; failed: number; errors: number; total: number };
export type Session = {
  session_id: string;
  revision: string;
  context: Context;
  transformations: { field: string; before: string; after: string }[];
  prompt: string;
  lint: Lint;
  results: Record<string, Verdict>;
  score: Score;
  before: { score: Score; failed_ids: string[]; patch_id: string } | null;
  pending_ids: string[];
};
export type Patch = {
  id: string;
  revision: string;
  prompt: string;
  diff: string;
  reason: string;
  evidence: Check & { persona_id: string };
  base_template?: string;
};
export type SwarmEvent =
  | { type: "start"; persona_ids: string[]; engine: Engine }
  | ({ type: "turn"; persona_id: string } & Turn)
  | ({ type: "tool"; persona_id: string } & ToolOutcome)
  | ({ type: "assertion"; persona_id: string } & Check)
  | { type: "interruption"; persona_id: string; turn: number }
  | ({ type: "verdict" } & Verdict)
  | ({ type: "complete"; ran_ids: string[]; engine: Engine } & Session)
  | { type: "error"; message: string };
export type StudioEvent =
  | { type: "ready"; mode: Mode; model?: string }
  | ({ type: "transcript" } & Turn)
  | ({ type: "tool" } & ToolOutcome)
  | { type: "first_audio"; ms: number }
  | { type: "interrupted"; turn: number }
  | { type: "error" | "notice"; message: string }
  | { type: "done" };

export const money = (value: string) => new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 2,
  minimumFractionDigits: value.endsWith(".00") ? 0 : 2,
}).format(Number(value));

export const sessionFields = (session: Session) => ({
  session_id: session.session_id, revision: session.revision,
});

async function checkResponse(response: Response) {
  if (response.ok) return response;
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  const message = typeof detail === "string" ? detail : Array.isArray(detail)
    ? detail.map((error) => error.loc.slice(1).join(".") + " " + error.msg).join(". ")
    : "The backend could not complete this request.";
  throw new Error(message, { cause: response.status });
}

async function request(path: string, init?: RequestInit) {
  return checkResponse(await fetch(API + path, init));
}

export async function getSettings(): Promise<Settings> {
  return (await request("/api/presets")).json();
}

export async function post<T>(path: string, data: unknown, signal?: AbortSignal): Promise<T> {
  return (await request(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data), signal,
  })).json();
}

export async function streamSwarm(
  data: unknown, onEvent: (event: SwarmEvent) => void, signal: AbortSignal,
) {
  const response = await request("/api/swarm/run", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data), signal,
  });
  if (!response.body) throw new Error("The backend returned an empty QA stream.");
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let pending = "";
  let finished = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += value;
      let delimiter = pending.indexOf("\n\n");
      while (delimiter >= 0) {
        const dataLine = pending.slice(0, delimiter).split("\n").find((line) => line.startsWith("data: "));
        pending = pending.slice(delimiter + 2);
        if (dataLine) {
          const event: SwarmEvent = JSON.parse(dataLine.slice(6));
          onEvent(event);
          finished ||= event.type === "complete" || event.type === "error";
        }
        delimiter = pending.indexOf("\n\n");
      }
    }
    if (!finished) throw new Error("The QA stream closed before all results arrived.");
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export const errorMessage = (error: unknown) => error instanceof Error
  ? error.message === "Failed to fetch" ? "The backend is unreachable. Start it and try again." : error.message
  : "The request failed.";
