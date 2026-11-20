import { useEffect, useRef, useState } from "react";
import { ArrowRight, FileCode2, RotateCcw, WandSparkles } from "lucide-react";
import { errorMessage, type Lint, type Session, money, post } from "./api";
import { Empty, Notice, Panel, Spin } from "./components";

export type Draft = { cart: string; merchant: string; prompt: string | null };

export function Pipeline({ draft, session, onDraft, onCompile, busy, dirty, error }: {
  draft: Draft; session: Session | null; onDraft: (draft: Draft) => void;
  onCompile: (draft: Draft) => void; busy: boolean; dirty: boolean; error: string;
}) {
  const [editor, setEditor] = useState<"cart" | "merchant">("cart");
  const [lintState, setLintState] = useState<{ source: string; value: Lint } | null>(null);
  const [lintBusy, setLintBusy] = useState(false);
  const [lintError, setLintError] = useState("");
  const promptEditor = useRef<HTMLTextAreaElement>(null);
  const prompt = draft.prompt ?? session?.prompt ?? "";
  const lint = lintState?.source === prompt ? lintState.value : prompt === session?.prompt ? session.lint : null;
  const price = session?.context.price;
  const policy = session?.context;

  useEffect(() => {
    if (!session || prompt === session.prompt) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void post<Lint>("/api/lint", { prompt }, controller.signal)
        .then((value) => { if (!controller.signal.aborted) setLintState({ source: prompt, value }); })
        .catch((error) => { if (!controller.signal.aborted) setLintError(errorMessage(error)); });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [prompt, session]);

  async function checkLint() {
    setLintBusy(true);
    setLintError("");
    try {
      const value = await post<Lint>("/api/lint", { prompt });
      setLintState({ source: prompt, value });
    } catch (error) {
      setLintError(errorMessage(error));
    } finally {
      setLintBusy(false);
    }
  }

  function goToLine(line: number) {
    const textarea = promptEditor.current;
    if (!textarea) return;
    const lines = prompt.split("\n");
    const offset = lines.slice(0, line - 1).join("\n").length + (line > 1 ? 1 : 0);
    textarea.focus();
    textarea.setSelectionRange(offset, offset + (lines[line - 1]?.length ?? 0));
    textarea.scrollTop = Math.max(0, (line - 4) * 22);
  }

  return <div className="view-content">
    <div className="price-strip" aria-label="Compiled prices">
      <div><span>Items subtotal</span><strong>{price ? money(price.subtotal) : "–"}</strong></div>
      <div><span>COD total</span><strong>{price ? money(price.cod) : "–"}</strong></div>
      <div><span>UPI total</span><strong>{price ? money(price.upi) : "–"}</strong></div>
      <div className="savings"><span>Customer saves</span><strong>{price ? money(price.savings) : "–"}</strong></div>
    </div>
    {policy && <p className="policy mono muted">
      {dirty ? "Last compiled · " : ""}{policy.discount_percent}% UPI cap · {policy.waives_fee ? "UPI waives the COD fee" : "UPI keeps the COD fee"} · {policy.rounding === "whole_rupee_down" ? "Round discounted items down to a whole rupee" : "Round discounted items to the nearest paisa"}
    </p>}
    {error && <Notice error>{error}</Notice>}
    <div className="pipeline-grid">
      <Panel title="Merchant inputs" label="JSON" actions={
        <div className="segments" aria-label="Input editor">
          <button type="button" aria-pressed={editor === "cart"} onClick={() => setEditor("cart")}>Cart</button>
          <button type="button" aria-pressed={editor === "merchant"} onClick={() => setEditor("merchant")}>Brand</button>
        </div>
      }>
        <label className="sr-only" htmlFor="merchant-input">{editor === "cart" ? "Cart JSON" : "Brand JSON"}</label>
        <textarea className="code-editor source-editor" id="merchant-input" value={draft[editor]} spellCheck={false}
          disabled={busy || !session} onChange={(event) => onDraft({ ...draft, [editor]: event.target.value, prompt: null })} />
        <div className="panel-footer"><span className="mono muted">{session?.context.cart_id || "Synthetic cart"}</span>
          <button className="button primary" type="button" disabled={busy || !draft.cart} onClick={() => onCompile(draft)}>
            {busy ? <Spin /> : <ArrowRight size={15} aria-hidden="true" />} Compile inputs
          </button>
        </div>
      </Panel>
      <Panel title="Active prompt" label="JINJA" actions={
        <button className="button quiet small" type="button" onClick={checkLint} disabled={lintBusy || !prompt}>
          {lintBusy ? <Spin /> : <WandSparkles size={14} aria-hidden="true" />} Lint prompt
        </button>
      }>
        <label className="sr-only" htmlFor="active-prompt">Editable active prompt</label>
        <textarea className="code-editor prompt-editor" ref={promptEditor} id="active-prompt" value={prompt}
          spellCheck={false} aria-describedby={dirty ? "pending-edits" : undefined}
          disabled={busy || !session} onChange={(event) => onDraft({ ...draft, prompt: event.target.value })} />
        <div className="panel-footer">
          <span className="mono muted" id="pending-edits">{dirty ? "Uncompiled edits" : session ? "Saved in session" : "Waiting for backend"}</span>
          <button className="button quiet small" type="button" disabled={busy || !session} onClick={() => onCompile({ ...draft, prompt: null })}>
            <RotateCcw size={14} aria-hidden="true" /> Render template
          </button>
        </div>
      </Panel>
      <Panel title="Cleaned variables">
        {session ? <div className="transformations">
          {session.transformations.map((change, index) => <div className="transformation" key={change.field + index}>
            <span className="mono muted">{change.field}</span>
            <div><span>{change.before}</span><ArrowRight size={14} aria-hidden="true" /><strong>{change.after}</strong></div>
          </div>)}
          <details className="spoken-details"><summary>Spoken prices</summary>
            {(["cod", "upi", "savings"] as const).map((key) => <div className="transformation" key={key}>
              <span className="mono muted">{key.toUpperCase()}</span>
              <div><span>{money(session.context.price[key])}</span><ArrowRight size={14} aria-hidden="true" /><strong>{session.context.spoken[key]}</strong></div>
            </div>)}
          </details>
        </div> : <Empty>Compile a cart to see how it will be spoken.</Empty>}
      </Panel>
      <Panel title="Speech diagnostics" actions={lint && <span className="mono score-tag">{lint.score} / 100</span>}>
        {lintError && <Notice error>{lintError}</Notice>}
        {lint?.diagnostics.length ? <ul className="diagnostics">
          {lint.diagnostics.map((issue) => <li key={issue.line + issue.code}>
            <button type="button" className="line-link mono" onClick={() => goToLine(issue.line)}>Line {issue.line}</button>
            <span>{issue.message}</span>
          </li>)}
        </ul> : <Empty icon="arrow">{lint ? "No speech issues found." : "Lint the current text to check spoken turns."}</Empty>}
        {lint && lint.fixed_prompt !== prompt && <div className="panel-footer">
          <button className="button secondary small" type="button" onClick={() => onDraft({ ...draft, prompt: lint.fixed_prompt })}>
            <FileCode2 size={14} aria-hidden="true" /> Use safe fixes
          </button>
        </div>}
      </Panel>
    </div>
  </div>;
}
