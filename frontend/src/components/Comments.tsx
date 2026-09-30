import { type FormEvent, useEffect, useRef, useState } from "react";

import { useAddComment, useComments, useDeleteComment, useEditComment, useMe } from "../api/hooks";
import type { Comment } from "../api/types";
import { formatDate } from "../lib/format";
import { PencilIcon, TrashIcon } from "./icons";
import { Avatar } from "./ui";

/**
 * Тред комментариев анкеты (ТЗ: «под каждой анкетой — тред: автор, текст, время»).
 * `card` — колонка на странице кандидата, `inline` — раскрывается прямо под анкетой в ленте.
 */
export function Comments({
  candidateId,
  variant = "card",
  autoFocus = false,
}: {
  candidateId: number;
  variant?: "card" | "inline";
  autoFocus?: boolean;
}) {
  const { data: comments = [], isPending } = useComments(candidateId);
  const inline = variant === "inline";

  const list = (
    <CommentList
      comments={comments}
      empty={isPending ? "Загрузка…" : inline ? "Тред пуст — напишите первым" : "Пока нет комментариев"}
      className={inline ? "max-h-80 px-4 pt-3" : "max-h-[55vh] flex-1 p-4"}
    />
  );
  const form = <CommentForm candidateId={candidateId} compact={inline} autoFocus={autoFocus} />;

  if (inline) {
    return (
      <section aria-label="Тред" className="enter border-t border-black/10 bg-black/[0.02]" style={{ animationDuration: "0.2s" }}>
        {list}
        {form}
      </section>
    );
  }
  return (
    <section className="card flex flex-col overflow-hidden">
      <div className="flex items-baseline justify-between border-b border-black px-4 py-3">
        <h2 className="section-title">Комментарии</h2>
        <span className="nums text-[12px] text-black/50">{comments.length}</span>
      </div>
      {list}
      <div className="border-t border-black">{form}</div>
    </section>
  );
}

function CommentList({ comments, empty, className }: { comments: Comment[]; empty: string; className: string }) {
  const { data: me } = useMe();
  const box = useRef<HTMLDivElement>(null);
  // новый комментарий (свой или пришедший по WebSocket) — прокручиваем список к нему, но не страницу
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [comments.length]);

  return (
    <div ref={box} className={`scroll-slim overflow-y-auto ${className}`}>
      {comments.length === 0 && <p className="py-4 text-center text-[13px] text-black/50">{empty}</p>}
      <ul className="space-y-3">
        {comments.map((c) => (
          <CommentItem key={c.id} comment={c} mine={me != null && c.author?.id === me.id} />
        ))}
      </ul>
    </div>
  );
}

/** Свой комментарий можно поправить или удалить (ТЗ: «статус и комментарий можно изменить прямо на сайте»). */
function CommentItem({ comment: c, mine }: { comment: Comment; mine: boolean }) {
  const edit = useEditComment(c.candidate_id);
  const remove = useDeleteComment(c.candidate_id);
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const [text, setText] = useState(c.text);

  const startEdit = () => {
    setText(c.text);
    setMode("edit");
  };
  const save = (e: FormEvent) => {
    e.preventDefault();
    const value = text.trim();
    if (!value) return;
    if (value === c.text) return setMode("view");
    // новый текст придёт в тред из WS-события comment.updated
    edit.mutate({ id: c.id, text: value }, { onSuccess: () => setMode("view") });
  };
  const error = edit.error ?? remove.error;

  return (
    <li className="group/comment enter flex gap-2.5" style={{ animationDuration: "0.25s" }}>
      <Avatar name={c.author?.name ?? null} size={28} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-2 text-[12px]">
          <strong className="font-semibold">{c.author?.name ?? "удалён"}</strong>
          <time className="nums text-black/50">{formatDate(c.created_at)}</time>
          {c.edited_at && (
            <span className="text-black/40" title={`Изменён ${formatDate(c.edited_at)}`}>
              изменён
            </span>
          )}
          {mine && mode === "view" && (
            <span className="ml-auto flex gap-0.5 opacity-60 transition-opacity group-hover/comment:opacity-100 focus-within:opacity-100">
              <button type="button" className="btn-ghost btn p-1" aria-label="Изменить комментарий" onClick={startEdit}>
                <PencilIcon className="size-3.5" />
              </button>
              <button
                type="button"
                className="btn-ghost btn p-1"
                aria-label="Удалить комментарий"
                onClick={() => setMode("delete")}
              >
                <TrashIcon className="size-3.5" />
              </button>
            </span>
          )}
        </div>
        {mode === "edit" ? (
          <form onSubmit={save}>
            <textarea
              className="field resize-none text-[13px]"
              aria-label="Текст комментария"
              value={text}
              rows={Math.min(6, Math.max(2, text.split("\n").length))}
              autoFocus
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setMode("view");
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save(e);
              }}
            />
            <div className="mt-1.5 flex justify-end gap-1.5">
              <button type="button" className="btn-ghost btn px-2 py-1 text-[12px]" onClick={() => setMode("view")}>
                Отмена
              </button>
              <button type="submit" className="btn btn-primary px-2.5 py-1 text-[12px]" disabled={edit.isPending || !text.trim()}>
                Сохранить
              </button>
            </div>
          </form>
        ) : (
          <p
            className={`w-fit max-w-full rounded-2xl rounded-tl-md px-3 py-2 text-[13px] break-words whitespace-pre-line ${
              mine ? "bg-black text-white" : "border border-black/50 bg-white"
            } ${mode === "delete" ? "opacity-50" : ""}`}
          >
            {c.text}
          </p>
        )}
        {mode === "delete" && (
          <div className="mt-1.5 flex items-center gap-1.5 text-[12px]">
            <span className="font-medium">Удалить для всех?</span>
            {/* сам комментарий исчезнет из треда по WS-событию comment.deleted */}
            <button
              type="button"
              className="btn btn-primary px-2.5 py-1 text-[12px]"
              disabled={remove.isPending}
              onClick={() => remove.mutate(c.id)}
            >
              Удалить
            </button>
            <button type="button" className="btn-ghost btn px-2 py-1 text-[12px]" onClick={() => setMode("view")}>
              Отмена
            </button>
          </div>
        )}
        {error && (
          <p role="alert" className="mt-1 text-[12px] font-medium">
            {error.message}
          </p>
        )}
      </div>
    </li>
  );
}

function CommentForm({ candidateId, compact, autoFocus }: { candidateId: number; compact: boolean; autoFocus: boolean }) {
  const add = useAddComment(candidateId);
  const [text, setText] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    // сам комментарий появится в списке из WS-события comment.created
    add.mutate(text, { onSuccess: () => setText("") });
  };

  const textarea = (
    <textarea
      className="field resize-none"
      value={text}
      autoFocus={autoFocus}
      onChange={(e) => setText(e.target.value)}
      placeholder="Комментарий для команды…"
      rows={compact ? 2 : 3}
      onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && submit(e)}
    />
  );
  const send = (
    <button type="submit" className="btn btn-primary" disabled={add.isPending || !text.trim()}>
      Отправить
    </button>
  );

  return compact ? (
    <form className="flex items-end gap-2 p-3 px-4" onSubmit={submit}>
      {textarea}
      {send}
    </form>
  ) : (
    <form className="p-3" onSubmit={submit}>
      {textarea}
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-black/40">Ctrl + Enter — отправить</span>
        {send}
      </div>
    </form>
  );
}
