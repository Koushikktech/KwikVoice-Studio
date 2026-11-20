import type { StudioEvent } from "./api";
import recording from "../public/recordings/dermpure-call.json";

type Cue = { at: number; event: StudioEvent };

const cues: Cue[] = [];
let turn = 0;
for (const line of recording.lines) {
  const speaker = line.speaker === "Agent" ? "agent" : "shopper";
  if (speaker === "shopper") turn += 1;
  cues.push({
    at: line.start,
    event: {
      type: "transcript", speaker, turn, text: line.text, final: true,
      ...(speaker === "agent" ? { words: line.text.split(/\s+/u).length } : {}),
    },
  });
}
for (const tool of recording.events) {
  cues.push({
    at: tool.start,
    event: {
      type: "tool", turn: 2, name: tool.name, ok: tool.ok, message: tool.message,
      args: tool.args, card: { ...tool.card, kind: "checkout" },
    },
  });
}
cues.sort((a, b) => a.at - b.at);

export function playRecordedCall(emit: (event: StudioEvent) => void, onLevel: (value: number) => void): () => void {
  const audio = new Audio("/recordings/dermpure-call.mp3");
  let next = 0;
  let stopped = false;
  const meter = window.setInterval(() => onLevel(recording.levels[Math.floor(audio.currentTime / recording.levelInterval)] ?? 0), 80);

  function advance() {
    while (!stopped && next < cues.length && cues[next].at <= audio.currentTime) {
      emit(cues[next++].event);
    }
  }
  function stop() {
    stopped = true;
    window.clearInterval(meter);
    audio.pause();
    audio.onended = audio.ontimeupdate = audio.onplaying = audio.onerror = null;
    audio.removeAttribute("src");
    audio.load();
  }
  function fail() {
    if (stopped) return;
    stop();
    emit({ type: "error", message: "The recording could not play. Choose the fixture replay to continue." });
  }
  audio.onplaying = advance;
  audio.ontimeupdate = advance;
  audio.onerror = fail;
  audio.onended = () => {
    advance();
    stop();
    emit({ type: "done" });
  };
  void audio.play().catch(fail);
  return stop;
}
