import evidence from "./evidence.js";

const audio = document.querySelector("#call");
const play = document.querySelector("#play");
const transcript = document.querySelector("#transcript");
const playbackState = document.querySelector("#playback-state");
const checkout = document.querySelector("#checkout");

const lines = evidence.recording.lines.map(({ speaker, text }) => {
  const item = document.createElement("li");
  const label = document.createElement("small");
  const words = document.createElement("p");
  label.textContent = speaker;
  words.textContent = text;
  item.append(label, words);
  transcript.append(item);
  return item;
});

const checkoutEvent = evidence.recording.events.find((event) => event.ok && event.card.kind === "checkout");
const rupees = (amount) => new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 0,
}).format(Number(amount));
const price = document.createElement("strong");
const savings = document.createElement("span");
price.textContent = `${rupees(checkoutEvent.card.amount)} mock UPI checkout`;
savings.textContent = `${rupees(checkoutEvent.card.savings)} saved compared with cash on delivery`;
checkout.append(price, savings);

play.onclick = async () => {
  if (!audio.paused) {
    audio.pause();
    return;
  }
  try {
    await audio.play();
  } catch {
    playbackState.textContent = "Playback unavailable";
  }
};
audio.addEventListener("play", () => {
  play.textContent = "Pause the call";
  playbackState.textContent = "Playing";
});
audio.addEventListener("pause", () => {
  play.textContent = "Play the call";
  playbackState.textContent = "Recording";
});
audio.addEventListener("timeupdate", () => {
  const active = evidence.recording.lines.findLastIndex((line) => line.start <= audio.currentTime);
  lines.forEach((line, index) => {
    if (index === active) line.setAttribute("aria-current", "true");
    else line.removeAttribute("aria-current");
  });
});

const before = document.querySelector("#before");
const after = document.querySelector("#after");

function showResult(which) {
  const result = evidence.fixture[which];
  before.setAttribute("aria-pressed", String(which === "before"));
  after.setAttribute("aria-pressed", String(which === "after"));
  document.querySelector("#qa-score").textContent = `${result.passed} of ${evidence.fixture.total} passed`;
  document.querySelector("#qa-reply").textContent = result.reply;
  document.querySelector("#qa-result").textContent = which === "before"
    ? "Interruption check failed. 26 words." : "Interruption check passed. 10 words.";
}

before.onclick = () => showResult("before");
after.onclick = () => showResult("after");
showResult("before");
