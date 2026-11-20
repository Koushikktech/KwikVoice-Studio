import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowRight, Check, ChevronRight, Circle, FileDiff, GitBranch, Play, RotateCcw, Square } from "lucide-react";
import type { Check as Assertion, Engine, Patch, Session, Settings, SwarmEvent, ToolOutcome, Turn } from "./api";
import { errorMessage, post, sessionFields, streamSwarm } from "./api";
import { Empty, Notice, Panel, Select, Spin, ToolEvents, Transcript } from "./components";

type Trace = { turns: Turn[]; tools: ToolOutcome[]; checks: Assertion[]; interrupted: boolean; status?: boolean | null; error?: string };
const emptyTrace = (): Trace => ({ turns: [], tools: [], checks: [], interrupted: false });

export function Swarm({ session, settings, dirty, onSession, runButtonRef }: {
  session: Session | null; settings: Settings | null; dirty: boolean; onSession: (session: Session, appliedEdit?: "base" | "rendered") => void; runButtonRef?: React.Ref<HTMLButtonElement>;
}) {
  const [engine, setEngine] = useState<Engine>("fixture");
  const [resultEngine, setResultEngine] = useState<Engine>("fixture");
  const [streamState, setStreamState] = useState<{ revision: string; engine: Engine; traces: Record<string, Trace> }>();
  const [selected, setSelected] = useState("interrupt");
  const [patch, setPatch] = useState<Patch | null>(null);
  const [running, setRunning] = useState(false);
  const [patchBusy, setPatchBusy] = useState(false);
  const [error, setError] = useState("");
  const [ran, setRan] = useState<{ revision: string; ids: string[] }>();
  const abort = useRef<AbortController | null>(null);
  const results = !dirty && engine === resultEngine ? session?.results ?? {} : {};
  const traces = !dirty && streamState && session?.revision === streamState.revision && engine === streamState.engine
    ? streamState.traces : {};
  const before = !dirty && engine === resultEngine ? session?.before : null;
  const pending = before ? session?.pending_ids ?? [] : [];
  const proposal = !dirty && engine === resultEngine && patch?.revision === session?.revision ? patch : null;
  const selectedPersona = settings?.personas.find((persona) => persona.id === selected);
  const stored = results[selected];
  const trace = traces[selected];
  const turns = running && trace ? trace.turns : stored?.transcript.length ? stored.transcript : trace?.turns ?? [];
  const tools = running && trace ? trace.tools : stored?.tools.length ? stored.tools : trace?.tools ?? [];
  const checks = running && trace ? trace.checks : stored?.checks.length ? stored.checks : trace?.checks ?? [];
  const firstFailed = checks.find((item) => !item.passed);
  const score = !dirty && engine === resultEngine ? session?.score : undefined;

  const review = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (proposal && !review.current?.open) review.current?.showModal();
    if (!proposal && review.current?.open) review.current.close();
  }, [proposal]);
  useEffect(() => () => abort.current?.abort(), []);

  function track(event: SwarmEvent, revision: string, engine: Engine) {
    if (event.type === "start") {
      setStreamState({ revision, engine, traces: Object.fromEntries(event.persona_ids.map((id) => [id, emptyTrace()])) });
    } else if (event.type === "complete") {
      setRan({ revision: event.revision, ids: event.ran_ids });
      setResultEngine(event.engine);
      onSession(event);
    } else if (event.type === "error") {
      setError(event.message);
    } else {
      const id = event.persona_id;
      setStreamState((state) => {
        const old = state?.traces[id] ?? emptyTrace();
        const next = { ...old };
        if (event.type === "turn") next.turns = [...old.turns, event];
        if (event.type === "tool") next.tools = [...old.tools, event];
        if (event.type === "assertion") next.checks = [...old.checks, event];
        if (event.type === "interruption") next.interrupted = true;
        if (event.type === "verdict") {
          next.status = event.passed;
          next.error = event.error;
        }
        return { revision, engine, traces: { ...state?.traces, [id]: next } };
      });
    }
  }

  async function run(failedOnly = false, source = session) {
    if (!source || dirty || running) return;
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    setPatch(null);
    setError("");
    try {
      await streamSwarm({ ...sessionFields(source), engine, failed_only: failedOnly },
        (event) => track(event, source.revision, engine), controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) setError(errorMessage(error));
      else setStreamState(undefined);
    } finally {
      setRunning(false);
    }
  }

  async function propose() {
    if (!session || dirty) return;
    setPatchBusy(true);
    setError("");
    try {
      setPatch(await post<Patch>("/api/patch/generate", {
        ...sessionFields(session), persona_id: selected, source: session.prompt,
      }));
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setPatchBusy(false);
    }
  }

  async function apply(verify: boolean) {
    if (!session || !proposal || dirty) return;
    setPatchBusy(true);
    setError("");
    try {
      const updated = await post<Session>("/api/patch/apply", { ...sessionFields(session), patch_id: proposal.id });
      onSession(updated, proposal.base_template ? "base" : "rendered");
      setPatch(null);
      if (verify) await run(true, updated);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setPatchBusy(false);
    }
  }

  return <div className="view-content">
    {error && <Notice error>{error}</Notice>}
    {dirty && <Notice>Save your changes under Merchant and prompt before running tests.</Notice>}
    <div className="run-toolbar">
      <Select label="QA engine" value={engine} disabled={running || patchBusy} onChange={(event) => {
        setEngine(event.target.value as Engine);
        setPatch(null);
        setError("");
      }}>
        <option value="fixture">Deterministic fixture</option>
        <option value="gemini" disabled={!settings?.gemini.available}>Gemini text{settings?.gemini.available ? "" : " (key required)"}</option>
      </Select>
      <div className="run-description">
        <span className="mono">{engine === "fixture" ? "FIXTURE ENGINE" : settings?.gemini.text_model}</span>
        <p>{engine === "fixture" ? "Fixed shopper scripts and measured assertions. No API key needed." : "Structured judge · " + settings?.gemini.judge_model}</p>
      </div>
      <div className="run-buttons">
        {pending.length > 0 && <button type="button" className="button primary" disabled={running || patchBusy || dirty}
          onClick={() => run(true)}><RotateCcw size={15} aria-hidden="true" /> Rerun failed ({pending.length})</button>}
        {running ? <button type="button" className="button secondary" onClick={() => abort.current?.abort()}>
          <Square size={13} aria-hidden="true" /> Stop run
        </button> : <button type="button" ref={runButtonRef} className={"button " + (pending.length ? "secondary" : "primary")}
          disabled={dirty || !session || patchBusy} onClick={() => run()}>
          <Play size={15} aria-hidden="true" /> Run all five
        </button>}
      </div>
    </div>
    <div className="qa-score" aria-live="polite">
      <div><span className="mono muted">SHOPPERS PASSED</span><strong>{score?.total ? score.passed + " / " + score.total : "– / 5"}</strong></div>
      {before && <div><span className="mono muted">BEFORE EDIT</span><strong>{before.score.passed} / {before.score.total}</strong></div>}
      {before && !pending.length && score?.total ? <div><span className="mono muted">MEASURED CHANGE</span>
        <strong className={score.passed >= before.score.passed ? "good" : "warn"}>{score.passed >= before.score.passed ? "+" : ""}{score.passed - before.score.passed} passed</strong></div> : null}
      <div className="score-note">
        {running ? <><Spin /> Streaming shopper turns</> : pending.length ? "Patch applied. Failed verdicts await rerun."
          : score?.errors ? score.errors + (score.errors === 1 ? " model error" : " model errors")
          : ran?.revision && ran.revision === session?.revision ? "Last run tested " + ran.ids.length + (ran.ids.length === 1 ? " shopper." : " shoppers.")
          : "Five fixed scenarios"}
      </div>
    </div>
    <div className="qa-grid">
      <Panel title="Shopper scenarios" label="5 FIXED">
        <ul className="persona-list">
          {settings?.personas.map((persona) => {
            const outcome = traces[persona.id]?.status !== undefined ? traces[persona.id].status : results[persona.id]?.passed;
            const queued = running && Boolean(traces[persona.id]) && traces[persona.id].status === undefined;
            const recent = traces[persona.id]?.turns.at(-1) ?? results[persona.id]?.transcript.at(-1);
            const StatusIcon = outcome === true ? Check : outcome === false || outcome === null ? AlertCircle : Circle;
            return <li key={persona.id}><button type="button" aria-pressed={selected === persona.id} onClick={() => setSelected(persona.id)}>
              <span className="avatar" aria-hidden="true">{persona.name[0]}</span>
              <span className="persona-name"><strong>{persona.title}</strong><small>{persona.name}{recent?.words ? " · " + recent.words + " words" : ""}</small>
              {recent && <span className="persona-latest">{recent.text}</span>}</span>
              {queued ? <Spin /> : <span className={"status-tag " + (outcome === true ? "pass" : outcome === false ? "fail" : "")}>
                <StatusIcon size={12} aria-hidden="true" />{outcome === true ? "Pass" : outcome === false ? "Fail" : outcome === null ? "Error" : "Ready"}
              </span>}
              <ChevronRight size={14} aria-hidden="true" className="persona-chevron" />
            </button></li>;
          })}
        </ul>
      </Panel>
      <Panel title={selectedPersona?.title ?? "Scenario evidence"} label={selectedPersona?.name.toUpperCase()}>
        {selectedPersona && <p className="scenario-summary">{selectedPersona.description}</p>}
        {(stored?.error || trace?.error) && <Notice error>{stored?.error ?? trace?.error}</Notice>}
        {firstFailed && <div className="failure-banner">
          <AlertCircle size={15} aria-hidden="true" />
          <div><strong>{firstFailed.root_cause ?? firstFailed.category}</strong><p>Turn {firstFailed.turn} · {firstFailed.detail}</p></div>
          <button type="button" className="button secondary small" disabled={!stored || running || dirty || patchBusy || pending.length > 0}
            onClick={propose}>{patchBusy ? <Spin /> : <FileDiff size={14} aria-hidden="true" />} Propose edit</button>
        </div>}
        {trace?.interrupted && <p className="interruption mono"><GitBranch size={13} aria-hidden="true" /> Shopper interrupted the greeting.</p>}
        {turns.length ? <Transcript turns={turns} failed={checks.filter((check) => !check.passed).map((check) => check.turn)}
          shopper={selectedPersona?.name} /> : <Empty icon="arrow">Run QA to inspect this conversation and its assertions.</Empty>}
        {checks.length > 0 && <details className="qa-details"><summary>Assertions ({checks.length})</summary>
          <ul className="assertions">{checks.map((check, index) => <li key={check.label + index}>
            {check.passed ? <Check size={14} className="good" aria-hidden="true" /> : <AlertCircle size={14} className="warn" aria-hidden="true" />}
            <div><strong>{check.label}</strong><p>{check.detail}</p></div>
          </li>)}</ul>
        </details>}
        {tools.length > 0 && <details className="qa-details"><summary>Mock tool outcomes ({tools.length})</summary><ToolEvents tools={tools} /></details>}
      </Panel>
    </div>
    <dialog className="patch-dialog" ref={review} aria-label="Review proposed prompt edit" onCancel={() => setPatch(null)}>
    {proposal && <Panel title="Proposed prompt edit" label="UNIFIED DIFF" actions={
      <><button type="button" className="button secondary small" onClick={() => setPatch(null)}>Close</button>
      <button type="button" className="button secondary small" disabled={patchBusy || running} onClick={() => apply(false)}>Apply to session</button>
      <button type="button" className="button primary small" disabled={patchBusy || running} onClick={() => apply(true)}>
        {patchBusy ? <Spin /> : <ArrowRight size={14} aria-hidden="true" />} Apply and rerun failed
      </button></>
    }>
      <p className="scenario-summary">{proposal.reason}</p>
      <pre className="diff" aria-label="Unified prompt diff">{proposal.diff.split("\n").map((line, index) =>
        <span key={index} className={line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-remove"
          : line.startsWith("@") ? "diff-location" : ""}>{line || " "}</span>)}</pre>
    </Panel>}
    </dialog>
  </div>;
}
