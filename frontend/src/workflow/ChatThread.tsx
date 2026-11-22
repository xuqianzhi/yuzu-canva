// A text node's chat with the model: ask for changes; an answer may carry a
// complete new version, which becomes a take when applied.
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ChatMessage } from "../api/types";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";

export function ChatThread({ nodeId }: { nodeId: string }) {
  const t = useT();
  const messages = useCanvas((s) => s.chats[nodeId]);
  const sending = useCanvas((s) => Boolean(s.chatSending[nodeId]));
  const loadChat = useCanvas((s) => s.loadChat);
  const sendChat = useCanvas((s) => s.sendChat);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const list = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (messages === undefined) void loadChat(nodeId);
  }, [messages, nodeId, loadChat]);

  // Follow the conversation.
  useEffect(() => {
    list.current?.lastElementChild?.scrollIntoView({ block: "nearest" });
  }, [messages?.length, sending]);

  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setError("");
    try {
      await sendChat(nodeId, text);
      setDraft("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="chat" aria-label={t("chat_title")}>
      <h3 className="step-panel__subhead">{t("chat_title")}</h3>
      {messages && messages.length > 0 ? (
        <ol className="chat__list" ref={list}>
          {messages.map((m) => (
            <Message key={m.id} message={m} nodeId={nodeId} />
          ))}
          {sending && (
            <li className="chat__msg chat__msg--assistant chat__msg--pending">
              <span className="spinner" /> {t("chat_thinking")}
            </li>
          )}
        </ol>
      ) : (
        <p className="step-panel__muted">
          {sending ? t("chat_thinking") : t("chat_empty")}
        </p>
      )}
      {error && (
        <p className="step-panel__error" role="alert">
          {error}
        </p>
      )}
      <form className="chat__form" onSubmit={(e) => void send(e)}>
        <textarea
          className="chat__input"
          rows={2}
          value={draft}
          placeholder={t("chat_placeholder")}
          aria-label={t("message_aria")}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button className="button button--primary" type="submit" disabled={!draft.trim() || sending}>
          {t("send")}
        </button>
      </form>
    </section>
  );
}

function Message({ message, nodeId }: { message: ChatMessage; nodeId: string}) {
  const t = useT();
  const applyProposal = useCanvas((s) => s.applyProposal);
  const [applying, setApplying] = useState(false);
  return (
    <li className={`chat__msg chat__msg--${message.role}`}>
      <p className="chat__text">{message.text}</p>
      {message.proposal && (
        <details className="chat__proposal" open={!message.applied_output_id}>
          <summary>{t("suggested_version")}</summary>
          <div className="chat__proposal-body">
            <p className="take__text">{message.proposal}</p>
          </div>
          {message.applied_output_id ? (
            <span className="chat__applied">{t("applied")}</span>
          ) : (
            <button
              className="button button--small"
              disabled={applying}
              onClick={async () => {
                setApplying(true);
                await applyProposal(nodeId, message.id);
                setApplying(false);
              }}
            >
              {t("apply")}
            </button>
          )}
        </details>
      )}
    </li>
  );
}
