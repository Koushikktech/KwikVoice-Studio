import { ArrowUpRight, BatteryFull, CheckCheck, MessageCircle, Signal, X } from "lucide-react";
import { useRef } from "react";
import { money, type ToolOutcome } from "./api";
import styles from "./phone.module.css";

export function WhatsAppPhone({ merchant, tools }: { merchant: string; tools: ToolOutcome[] }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const approved = tools.filter((event) => event.ok && event.card);
  const checkout = approved.findLast((event) => event.card?.kind === "checkout")?.card;

  return <div className={styles.stage}>
    <div className={styles.phone} aria-label="WhatsApp preview">
      <div className={styles.status}><span>WhatsApp</span><i /><span><Signal size={12} /><BatteryFull size={16} /></span></div>
      <div className={styles.header}><span className={styles.avatar}>{merchant.slice(0, 1)}</span>
        <div><strong>{merchant}</strong><small>Demo business account</small></div>
      </div>
      <div className={styles.chat} aria-live="polite">
        {!approved.length && <div className={styles.wait}><MessageCircle size={22} strokeWidth={1.3} /><span>Waiting for a checkout or order update</span></div>}
        {approved.map(({ card, name }, index) => <article className={styles.bubble} key={name + index}>
          {card?.kind === "checkout" ? <>
            <small>KwikCheckout · UPI</small><strong>{money(card.amount!)}</strong>
            <span>{merchant} cart · Save {money(card.savings!)}</span>
            <button onClick={() => dialog.current?.showModal()}>Open mock checkout <ArrowUpRight size={14} /></button>
          </> : <><small>Order update</small><strong>{card?.kind === "cod" ? "COD confirmed" : "Callback queued"}</strong></>}
          <div className={styles.receipt}>Demo message <CheckCheck size={13} /></div>
        </article>)}
      </div>
      <div className={styles.home} />
    </div>
    <dialog ref={dialog} className={styles.dialog} onClick={(e) => { if (e.target === dialog.current) dialog.current?.close(); }}>
      <div><button aria-label="Close mock checkout" onClick={() => dialog.current?.close()}><X size={16} /></button>
        <small>KwikCheckout preview</small><h2>{merchant} cart</h2>
        {checkout && <><strong>{money(checkout.amount!)}</strong><p>Pay via UPI · {money(checkout.savings!)} saved</p>
          <code>{checkout.cart_id}</code><p>This local preview uses a synthetic order.</p></>}
      </div>
    </dialog>
  </div>;
}
