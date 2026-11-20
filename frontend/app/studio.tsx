import { useEffect, useRef, useState } from "react";
import { PhoneOff, Play, Send } from "lucide-react";
import { API, errorMessage, sessionFields } from "./api";
import type { Mode, Session, Settings, StudioEvent, ToolOutcome, Turn } from "./api";
import { Empty, Notice, Panel, Select, ToolEvents, Transcript } from "./components";

import { playRecordedCall } from "./reference-call";
import { WhatsAppPhone } from "./phone";
import { Waveform } from "./waveform";

const modes = [
  { id: "live", label: "Live call" },
  { id: "recorded", label: "Recorded call" },
  { id: "text", label: "Text demo" },
  { id: "replay", label: "Scripted call" },
] as const;

type Connection = {
  socket?: WebSocket;
  audio?: AudioContext;
  mic?: MediaStream;
  worklet?: AudioWorkletNode;
  playback: Set<AudioBufferSourceNode>;
  nextTime: number;
  timer?: ReturnType<typeof setTimeout>;
  stopRecording?: () => void;
  started: number;
  firstAudio: boolean;
  ready: boolean;
  closed: boolean;
};

function flush(connection: Connection) {
  for (const source of connection.playback) {
    try { source.stop(); } catch { /* The source may have just ended. */ }
    source.disconnect();
  }
  connection.playback.clear();
  connection.nextTime = 0;
}

function release(connection: Connection) {
  if (connection.closed) return;
  connection.closed = true;
  clearTimeout(connection.timer);
  connection.stopRecording?.();
  flush(connection);
  if (connection.worklet) {
    connection.worklet.port.onmessage = null;
    connection.worklet.disconnect();
  }
  connection.mic?.getTracks().forEach((track) => track.stop());
  if (connection.audio && connection.audio.state !== "closed") void connection.audio.close().catch(() => undefined);
  window.speechSynthesis?.cancel();
  const ws = connection.socket;
  if (ws && ws.readyState < WebSocket.CLOSING) {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "stop" }));
    ws.close();
  }
}

function playPcm(connection: Connection, bytes: ArrayBuffer) {
  const output = connection.audio;
  if (!output || bytes.byteLength < 2 || connection.closed) return;
  const pcm = new DataView(bytes);
  const buffer = output.createBuffer(1, Math.floor(bytes.byteLength / 2), 24000);
  const samples = buffer.getChannelData(0);
  for (let index = 0; index < samples.length; index++) samples[index] = pcm.getInt16(index * 2, true) / 32768;
  const source = output.createBufferSource();
  source.buffer = buffer;
  source.connect(output.destination);
  connection.playback.add(source);
  source.onended = () => {
    connection.playback.delete(source);
    source.disconnect();
  };
  const start = Math.max(output.currentTime + 0.018, connection.nextTime);
  source.start(start);
  connection.nextTime = start + buffer.duration;
}

export function Studio({ session, settings, dirty }: {
  session: Session | null; settings: Settings | null; dirty: boolean;
}) {
  const [mode, setMode] = useState<Mode | "recorded">(settings?.gemini.available ? "live" : "recorded");
  const [status, setStatus] = useState<"idle" | "connecting" | "ready" | "ended">("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [tools, setTools] = useState<ToolOutcome[]>([]);
  const [text, setText] = useState("");
  const [firstAudio, setFirstAudio] = useState<number>();
  const [interruptions, setInterruptions] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const connection = useRef<Connection | null>(null);
  const level = useRef(0);
  const tail = useRef<HTMLDivElement>(null);
  const transcriptBox = useRef<HTMLDivElement>(null);
  const locked = status === "connecting" || status === "ready";
  const latestAgent = turns.findLast((turn) => turn.speaker === "agent");
  const actionCount = tools.filter((tool) => tool.ok).length;

  useEffect(() => () => {
    if (connection.current) release(connection.current);
  }, [session?.revision]);

  useEffect(() => {
    if (transcriptBox.current && tail.current) transcriptBox.current.scrollTop = tail.current.offsetTop;
  }, [turns]);

  function end() {
    if (connection.current) release(connection.current);
    setStatus("ended");
  }

  function speak(replay: Connection, line: string) {
    const advance = () => {
      clearTimeout(replay.timer);
      if (!replay.closed && replay.socket?.readyState === WebSocket.OPEN) {
        replay.socket.send(JSON.stringify({ type: "next" }));
      }
    };
    if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") {
      setNotice("Browser speech is unavailable. Replay continues with the transcript.");
      replay.timer = setTimeout(advance, 1000);
      return;
    }
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      advance();
    };
    const speech = new SpeechSynthesisUtterance(line);
    speech.lang = "en-IN";
    speech.rate = 0.97;
    speech.onstart = () => {
      if (!replay.closed && !replay.firstAudio) {
        replay.firstAudio = true;
        setFirstAudio(Math.round(performance.now() - replay.started));
      }
    };
    speech.onend = finish;
    speech.onerror = () => {
      if (!replay.closed) setNotice("Browser speech is unavailable. Replay continues with the transcript.");
      clearTimeout(replay.timer);
      replay.timer = setTimeout(finish, 1000);
    };
    replay.timer = setTimeout(() => {
      finish();
      window.speechSynthesis.cancel();
    }, 12000);
    window.speechSynthesis.speak(speech);
  }

  async function start() {
    if (!session || dirty || locked) return;
    setTurns([]);
    setTools([]);
    setText("");
    setNotice("");
    setError("");
    setFirstAudio(undefined);
    setInterruptions(0);
    setStatus("connecting");
    const active: Connection = {
      playback: new Set(), nextTime: 0, started: performance.now(), firstAudio: false, ready: false, closed: false,
    };
    connection.current = active;
    const fail = (message: string) => {
      if (active.closed) return;
      setError(message);
      end();
    };
    const handle = (event: StudioEvent) => {
        if (active.closed) return;
        if (event.type === "ready") {
          active.ready = true;
          setStatus("ready");
          if (mode === "replay") active.socket?.send(JSON.stringify({ type: "next" }));
        } else if (event.type === "transcript") {
          setTurns((existing) => {
            const index = existing.findIndex((turn) => turn.speaker === event.speaker && turn.turn === event.turn);
            return index < 0 ? [...existing, event] : existing.map((turn, position) => position === index ? event : turn);
          });
          if (mode === "replay" && event.speaker === "agent") speak(active, event.text);
        } else if (event.type === "tool") {
          setTools((existing) => [...existing, event]);
          if (event.ok && active.audio?.state === "running") {
            const output = active.audio;
            const ping = output.createOscillator();
            const gain = output.createGain();
            gain.gain.setValueAtTime(0.045, output.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, output.currentTime + 0.14);
            ping.frequency.value = 940;
            ping.connect(gain).connect(output.destination);
            ping.start();
            ping.stop(output.currentTime + 0.15);
          }
        } else if (event.type === "first_audio") {
          setFirstAudio(event.ms);
        } else if (event.type === "interrupted") {
          flush(active);
          setInterruptions((count) => count + 1);
        } else if (event.type === "notice") {
          setNotice(event.message);
        } else if (event.type === "error") {
          fail(event.message);
        } else if (event.type === "done") {
          end();
        }
      };
    try {
      if (mode !== "live" && window.AudioContext) {
        active.audio = new AudioContext();
        void active.audio.resume().catch(() => undefined);
      }
      if (mode === "recorded") {
        active.ready = true;
        setStatus("ready");
        active.stopRecording = playRecordedCall(handle, (value) => { level.current = value; });
        return;
      }
      if (mode === "live") {
        if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
          throw new Error("Microphone capture is unavailable here. Open localhost or choose replay or text.");
        }
        const audio = new AudioContext();
        active.audio = audio;
        await audio.resume();
        const mic = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        if (active.closed) {
          mic.getTracks().forEach((track) => track.stop());
          return;
        }
        active.mic = mic;
        await audio.audioWorklet.addModule("/pcm-worklet.js");
        if (active.closed) return;
        const capture = new AudioWorkletNode(audio, "pcm-capture");
        active.worklet = capture;
        const silence = audio.createGain();
        silence.gain.value = 0;
        audio.createMediaStreamSource(mic).connect(capture);
        capture.connect(silence).connect(audio.destination);
        capture.port.onmessage = (event: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) => {
          level.current = Math.max(level.current, event.data.rms);
          if (active.ready && active.socket?.readyState === WebSocket.OPEN && active.socket.bufferedAmount < 32000) {
            active.socket.send(event.data.pcm);
          }
        };
      }
      const endpoint = new URL(API + "/ws/live-call");
      endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
      endpoint.search = new URLSearchParams({ ...sessionFields(session), mode }).toString();
      const socket = new WebSocket(endpoint);
      active.socket = socket;
      socket.binaryType = "arraybuffer";
      socket.onmessage = (message: MessageEvent<string | ArrayBuffer>) => {
        if (active.closed) return;
        if (message.data instanceof ArrayBuffer) {
          const samples = new Int16Array(message.data);
          let sum = 0;
          for (let i = 0; i < samples.length; i += 8) sum += (samples[i] / 32768) ** 2;
          level.current = Math.max(level.current, Math.sqrt(sum / Math.max(1, Math.ceil(samples.length / 8))));
          playPcm(active, message.data);
          return;
        }
        handle(JSON.parse(message.data) as StudioEvent);
      };
      socket.onerror = () => fail("The studio could not connect. Check that the backend is running.");
      socket.onclose = () => {
        if (!active.closed) fail("The studio connection closed. Start another call or choose a local mode.");
      };
    } catch (error) {
      const denied = error instanceof DOMException && error.name === "NotAllowedError";
      fail(denied ? "Allow microphone access or choose Text demo." : errorMessage(error));
    }
  }

  function send(message = text) {
    const socket = connection.current?.socket;
    if (!message.trim() || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "text", text: message.trim() }));
    setText("");
  }

  return <div className="view-content">
    {dirty && <Notice>Save your changes under Merchant and prompt to start a call.</Notice>}
    {error && <Notice error>{error}</Notice>}
    {notice && <Notice>{notice}</Notice>}
    <div className="transport">
      <Select label="Call mode" value={mode} disabled={locked} onChange={(event) => {
        setMode(event.target.value as typeof mode);
        setNotice(""); setError(""); setStatus("idle"); setTurns([]); setTools([]); setFirstAudio(undefined); setInterruptions(0);
      }}>
        {modes.map((item) => <option key={item.id} value={item.id} disabled={item.id === "live" && !settings?.gemini.available}>
          {item.label}{item.id === "live" && !settings?.gemini.available ? " (requires Gemini key)" : ""}
        </option>)}
      </Select>
      <span className="mode-note">{mode === "live" ? "Speak in your preferred language." : mode === "recorded" ? "DermPure sample call" : mode === "text" ? "Scripted replies in English" : "Hinglish script with browser audio"}</span>
      <Waveform level={level} active={locked && mode !== "text"} />
      <span className="transport-status mono" role="status"><span className={status === "ready" ? "active-dot" : "idle-dot"} />
        {status === "ready" ? "Connected" : status === "connecting" ? "Connecting" : status === "ended" ? "Ended" : "Ready"}</span>
      {locked ? <button type="button" className="button secondary" onClick={end}>
        <PhoneOff size={15} aria-hidden="true" /> End call
      </button> : <button type="button" className="button primary" disabled={!session || dirty} onClick={start}>
        <Play size={15} aria-hidden="true" />
        {mode === "recorded" ? "Play recorded call" : mode === "replay" ? "Play mock call" : mode === "text" ? "Start text call" : "Start live call"}
      </button>}
    </div>
    <div className={tools.length ? "studio-grid" : "call-only"}>
      <Panel title="Conversation">
        <div className="studio-transcript" ref={transcriptBox}>
          {turns.length ? <Transcript turns={turns} /> : <Empty icon="arrow">
            {status === "ready" && mode === "live" ? "Speak into your microphone to begin."
              : status === "ready" && mode === "text" ? "Ask about COD, UPI or a product detail."
              : "Start a call to see the conversation here."}
          </Empty>}
          <div ref={tail} />
        </div>
        {mode === "text" && status === "ready" && <div className="text-presets" aria-label="Shopper quick replies">
          {[["Ask about COD", "Yaar, COD fee extra kyun hai?"], ["Accept UPI link", "Haan, UPI link bhej do."],
            ["Ask for callback", "Please call me back."]].map(([label, message]) =>
              <button key={label} type="button" className="button small" onClick={() => send(message)}>{label}</button>)}
        </div>}
        {mode === "text" && <form className="text-composer" onSubmit={(event) => { event.preventDefault(); send(); }}>
          <label className="sr-only" htmlFor="caller-text">Caller message</label>
          <input id="caller-text" placeholder="For example, what is my UPI total?" maxLength={500}
            value={text} onChange={(event) => setText(event.target.value)} disabled={status !== "ready"} />
          <button type="submit" className="button primary" disabled={status !== "ready" || !text.trim()}>
            <Send size={14} aria-hidden="true" /> Send
          </button>
        </form>}
      </Panel>
      {tools.length > 0 && <Panel title="Demo order updates">
        <WhatsAppPhone merchant={mode === "recorded" ? "DermPure" : session?.context.merchant_name ?? "Merchant"} tools={tools} />
        {tools.length > 0 && <details className="webhook-inspector"><summary>Webhook inspector ({tools.length})</summary><ToolEvents tools={tools} /></details>}
      </Panel>}
    </div>
    {(locked || status === "ended") && <details className="call-details"><summary>Call details</summary>
    <div className="studio-metrics">
      <div><span>First audio</span><strong>{firstAudio === undefined ? "–" : firstAudio + " ms"}</strong></div>
      <div><span>Latest agent turn</span><strong className={latestAgent?.words && latestAgent.words > 18 ? "warn" : undefined}>{latestAgent?.words === undefined ? "–" : latestAgent.words + " words"}</strong></div>
      <div><span>Interruptions</span><strong>{interruptions}</strong></div>
      <div><span>Mock actions</span><strong>{actionCount}</strong></div>
    </div>
    </details>}
  </div>;
}
