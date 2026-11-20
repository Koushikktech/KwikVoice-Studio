"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioLines } from "lucide-react";
import { errorMessage, getSettings, post } from "./api";
import type { Flow, Preset, Session, Settings } from "./api";
import { Notice, Select, Spin } from "./components";
import { Pipeline, type Draft } from "./pipeline";
import { Studio } from "./studio";
import { Swarm } from "./swarm";

const emptyDraft: Draft = { cart: "", merchant: "", prompt: null };

function presetDraft(preset: Preset): Draft {
  return { cart: JSON.stringify(preset.cart, null, 2), merchant: JSON.stringify(preset.merchant, null, 2), prompt: null };
}

export default function Workbench() {
  const settingsPanel = useRef<HTMLDetailsElement>(null);
  const testsPanel = useRef<HTMLDetailsElement>(null);
  const [presetId, setPresetId] = useState("");
  const [flow, setFlow] = useState<Flow>("cart-recovery");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const sessionId = useRef<string>(undefined);

  const compile = useCallback(async (input: Draft, selectedFlow: Flow) => {
    setBusy(true);
    setError("");
    try {
      const payload = {
        cart: JSON.parse(input.cart),
        merchant: JSON.parse(input.merchant),
        flow: selectedFlow,
        prompt: input.prompt,
      };
      let value: Session;
      try {
        value = await post<Session>("/api/compile", { ...payload, session_id: sessionId.current });
      } catch (error) {
        if (!(error instanceof Error) || error.cause !== 404 || !sessionId.current) throw error;
        value = await post<Session>("/api/compile", payload);
      }
      sessionId.current = value.session_id;
      setSession(value);
      setDraft({ ...input, prompt: input.prompt === null ? null : value.prompt });
      setDirty(false);
    } catch (error) {
      setError(error instanceof SyntaxError ? "Check the cart and brand JSON for a missing quote, brace or comma." : errorMessage(error));
      setDirty(true);
    } finally {
      setBusy(false);
    }
  }, []);

  const load = useCallback(async () => {
    setError("");
    setBusy(true);
    try {
      const value = await getSettings();
      setSettings(value);
      const first = value.presets[0];
      if (!first) throw new Error("The backend returned no merchant presets.");
      setPresetId(first.merchant.id);
      const input = presetDraft(first);
      setDraft(input);
      await compile(input, "cart-recovery");
    } catch (error) {
      setError(errorMessage(error));
      setBusy(false);
    }
  }, [compile]);

  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const view = new URLSearchParams(window.location.search).get("view");
    const panel = view === "swarm" ? testsPanel.current : view === "pipeline" ? settingsPanel.current : null;
    if (panel) {
      panel.open = true;
      panel.scrollIntoView();
    }
    void load();
  }, [load]);

  function changePreset(id: string) {
    const chosen = settings?.presets.find((preset) => preset.merchant.id === id);
    if (!chosen) return;
    setPresetId(id);
    const input = presetDraft(chosen);
    setDraft(input);
    setDirty(true);
    void compile(input, flow);
  }

  function changeFlow(value: Flow) {
    setFlow(value);
    const input = { ...draft, prompt: null };
    setDraft(input);
    setDirty(true);
    void compile(input, value);
  }

  function updateSession(value: Session, appliedEdit?: "base" | "rendered") {
    setSession(value);
    if (appliedEdit) {
      setDraft((previous) => ({
        ...previous,
        prompt: appliedEdit === "base" && previous.prompt === null ? null : value.prompt,
      }));
    }
  }

  return <div className="call-workspace">
    <a className="skip-link" href="#workbench">Skip to workbench</a>
    <main id="workbench" tabIndex={-1}>
      <header className="call-header">
        <AudioLines size={26} aria-hidden="true" />
        <h1>KwikVoice</h1>
        {session && <span>{session.context.merchant_name}</span>}
      </header>
      {error && !session && <div className="initial-error">
        <Notice error>{error}</Notice><button type="button" className="button secondary" onClick={load}>Retry connection</button>
      </div>}
      {busy && !session && <div className="initial-loading"><Spin /> Loading call</div>}
      {session && <Studio key={session.revision} session={session} settings={settings} dirty={dirty || busy} />}
      <details className="workspace-section" ref={settingsPanel}>
        <summary>Merchant and prompt{dirty ? " · Unsaved edits" : ""}</summary>
        <div className="scope">
            <Select label="Merchant" value={presetId} onChange={(event) => changePreset(event.target.value)} disabled={busy || !settings}>
              {!settings && <option value="">Loading presets</option>}
              {settings?.presets.map((preset) => <option key={preset.merchant.id} value={preset.merchant.id}>{preset.merchant.name}</option>)}
            </Select>
            <Select label="Flow" value={flow} onChange={(event) => changeFlow(event.target.value as Flow)} disabled={busy || !session}>
              <option value="cart-recovery">Cart recovery</option>
              <option value="cod-confirmation">COD confirmation</option>
            </Select>

        </div>
        <Pipeline draft={draft} session={session} dirty={dirty} busy={busy} error={session ? error : ""}
          onDraft={(value) => { setDraft(value); setDirty(true); }} onCompile={(value) => { void compile(value, flow); }} />
      </details>
      <details className="workspace-section" ref={testsPanel}>
        <summary>Test conversations</summary>
        <Swarm session={session} settings={settings} dirty={dirty || busy} onSession={updateSession} />
      </details>
    </main>
  </div>;
}
