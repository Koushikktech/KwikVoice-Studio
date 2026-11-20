import { useEffect, useRef, type RefObject } from "react";

export function Waveform({ level, active }: { level: RefObject<number>; active: boolean }) {
  const element = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = element.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const history = new Array<number>(48).fill(0);
    const paint = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      history.shift();
      history.push(active ? Math.min(1, level.current * 4) : 0);
      level.current *= 0.82;
      ctx.fillStyle = active ? "#6ad3ab" : "#55635f";
      history.forEach((value, i) => {
        const h = Math.max(2, value * (canvas.height - 2));
        ctx.fillRect(i * 4, (canvas.height - h) / 2, 2, h);
      });
    };
    paint();
    if (!active) return;
    const id = window.setInterval(paint, 36);
    return () => window.clearInterval(id);
  }, [active, level]);
  return <canvas ref={element} width={192} height={30} aria-label="Audio level history" style={{width:"min(15vw, 135px)", height:24, flexShrink:1}} />;
}
