// A collection's Share page: who's in it, and inviting editors.
//
// The owner invites by email (with that editor's daily limits here: the
// owner pays for everything made in the collection), changes limits,
// removes editors, and cancels invites. Editors see the same lists, their
// own limits and use, and can leave.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, unwrap } from "../api/client";
import type { EditorLimits, Invite, Member } from "../api/types";
import { useAuth } from "../auth";
import { errorText, useT, type T } from "../i18n";
import { homeHref } from "../router";
import type { CollectionView } from "./HomePage";

const KINDS = ["image", "video", "text"] as const;
const NO_LIMITS: EditorLimits = { text: null, image: null, video: null };

export function Share({ view }: { view: CollectionView }) {
  const t = useT();
  const { collection } = view;
  const owner = collection.your_role === "owner";
  const auth = useAuth((s) => s.state);
  const myEmail = auth.status === "signed_in" ? auth.email.toLowerCase() : "";
  const [members, setMembers] = useState<Member[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [error, setError] = useState("");

  const path = { params: { path: { collection_id: collection.id } } };
  const load = useCallback(async () => {
    try {
      const [people, waiting] = await Promise.all([
        api.GET("/api/collections/{collection_id}/members", path).then(unwrap),
        api.GET("/api/collections/{collection_id}/invites", path).then(unwrap),
      ]);
      setMembers(people);
      setInvites(waiting);
      setError("");
    } catch (e) {
      setError(errorText(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collection.id]);
  useEffect(() => void load(), [load]);

  const act = async (work: () => Promise<unknown>) => {
    try {
      await work();
      setError("");
    } catch (e) {
      setError(errorText(e));
    }
    await load();
  };

  const remove = (member: Member) => {
    const mine = member.email.toLowerCase() === myEmail;
    const ok = window.confirm(
      mine
        ? t("share_leave_confirm", { name: collection.name })
        : t("share_remove_confirm", { email: member.email }),
    );
    if (!ok) return;
    void act(async () => {
      unwrap(
        await api.DELETE("/api/collections/{collection_id}/members/{user_id}", {
          params: { path: { collection_id: collection.id, user_id: member.user_id } },
        }),
      );
      if (mine) location.hash = homeHref;
    });
  };

  return (
    <main className="home__page">
      <div className="home__inner">
        <h1 className="home__title">{t("share_title")}</h1>
        <p className="home__help">
          {owner ? t("share_help_owner") : t("share_help_editor", { email: collection.owner_email })}
        </p>
        {error && (
          <p className="home__error" role="alert">
            {error}
          </p>
        )}

        <section className="share__section">
          <h2 className="settings__label">{t("share_members")}</h2>
          {members === null ? (
            <p className="home__help">{t("loading")}</p>
          ) : (
            <ul className="share__list">
              {members.map((member) => (
                <MemberRow
                  key={member.user_id}
                  member={member}
                  you={member.email.toLowerCase() === myEmail}
                  canManage={owner}
                  onSaveLimits={(limits) =>
                    void act(async () =>
                      unwrap(
                        await api.PATCH("/api/collections/{collection_id}/members/{user_id}", {
                          params: {
                            path: { collection_id: collection.id, user_id: member.user_id },
                          },
                          body: { limits },
                        }),
                      ),
                    )
                  }
                  onRemove={() => remove(member)}
                />
              ))}
            </ul>
          )}
        </section>

        {owner && (
          <section className="share__section">
            <h2 className="settings__label">{t("share_invite")}</h2>
            <InviteForm
              onInvite={(email, limits) =>
                act(async () =>
                  unwrap(
                    await api.POST("/api/collections/{collection_id}/invites", {
                      ...path,
                      body: { email, limits },
                    }),
                  ),
                )
              }
            />
          </section>
        )}

        {invites.length > 0 && (
          <section className="share__section">
            <h2 className="settings__label">{t("share_pending")}</h2>
            <ul className="share__list">
              {invites.map((invite) => (
                <li key={invite.id} className="share__row">
                  <div className="share__who">
                    <strong>{invite.email}</strong>
                    <small>
                      {t("share_invited", {
                        when: new Date(invite.created_at).toLocaleDateString(),
                        until: new Date(invite.expires_at).toLocaleDateString(),
                      })}
                      {" · "}
                      {limitsText(invite.limits, t)}
                    </small>
                  </div>
                  {owner && (
                    <button
                      className="button button--small"
                      onClick={() =>
                        void act(async () =>
                          unwrap(
                            await api.DELETE(
                              "/api/collections/{collection_id}/invites/{invite_id}",
                              {
                                params: {
                                  path: { collection_id: collection.id, invite_id: invite.id },
                                },
                              },
                            ),
                          ),
                        )
                      }
                    >
                      {t("share_cancel_invite")}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </main>
  );
}

function MemberRow({
  member,
  you,
  canManage,
  onSaveLimits,
  onRemove,
}: {
  member: Member;
  you: boolean;
  canManage: boolean;
  onSaveLimits: (limits: EditorLimits) => void;
  onRemove: () => void;
}) {
  const t = useT();
  const [limits, setLimits] = useState(member.limits);
  useEffect(() => setLimits(member.limits), [member.limits]);
  const changed = KINDS.some((k) => limits[k] !== member.limits[k]);
  const isOwner = member.role === "owner";
  const used = member.used_today;

  return (
    <li className="share__row">
      <div className="share__who">
        <strong>
          {member.email}
          {you && <span className="share__you"> {t("share_you")}</span>}
        </strong>
        <small>
          <span className="role-pill role-pill--inline">
            {isOwner ? t("role_owner") : t("role_editor")}
          </span>{" "}
          {t("share_used", { image: used.image, video: used.video, text: used.text })}
        </small>
      </div>
      {isOwner ? (
        <small className="share__note">{t("share_owner_pays")}</small>
      ) : canManage ? (
        <div className="share__limits">
          <LimitsEditor value={limits} onChange={setLimits} />
          {changed && (
            <button className="button button--primary button--small" onClick={() => onSaveLimits(limits)}>
              {t("share_save_limits")}
            </button>
          )}
        </div>
      ) : (
        <small className="share__note">{limitsText(member.limits, t)}</small>
      )}
      {!isOwner && (canManage || you) && (
        <button className="button button--small" onClick={onRemove}>
          {you ? t("share_leave") : t("share_remove")}
        </button>
      )}
    </li>
  );
}

/** Three daily limits; blank means "no limit of their own". */
function LimitsEditor({
  value,
  onChange,
}: {
  value: EditorLimits;
  onChange: (limits: EditorLimits) => void;
}) {
  const t = useT();
  return (
    <div className="limits-editor">
      {KINDS.map((kind) => (
        <label key={kind} className="limits-editor__field">
          <span>{t(`limit_${kind}`)}</span>
          <input
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            placeholder={t("limit_none")}
            value={value[kind] ?? ""}
            onChange={(e) => {
              const raw = e.target.value.trim();
              const n = raw === "" ? null : Math.max(0, Math.floor(Number(raw)));
              onChange({ ...value, [kind]: Number.isFinite(n) ? n : null });
            }}
          />
        </label>
      ))}
    </div>
  );
}

function InviteForm({
  onInvite,
}: {
  onInvite: (email: string, limits: EditorLimits) => Promise<void>;
}) {
  const t = useT();
  const [email, setEmail] = useState("");
  const [limits, setLimits] = useState<EditorLimits>(NO_LIMITS);
  const [busy, setBusy] = useState(false);
  const valid = /^[^@\s]+@[^@\s]+$/.test(email.trim());

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    await onInvite(email.trim(), limits);
    setBusy(false);
    setEmail("");
    setLimits(NO_LIMITS);
  };

  return (
    <form className="invite-form" onSubmit={(e) => void submit(e)}>
      <label className="designer__field designer__field--grow">
        <span>{t("share_email")}</span>
        <input
          type="email"
          value={email}
          placeholder="name@example.com"
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <LimitsEditor value={limits} onChange={setLimits} />
      <button className="button button--primary" type="submit" disabled={busy || !valid}>
        {t("share_send_invite")}
      </button>
      <p className="home__help invite-form__help">{t("share_invite_help")}</p>
    </form>
  );
}

function limitsText(limits: EditorLimits, t: T): string {
  const parts = KINDS.map((kind) => {
    const n = limits[kind];
    return `${t(`limit_${kind}`)}: ${n === null ? t("limit_none") : n}`;
  });
  return t("share_limits", { limits: parts.join(", ") });
}
