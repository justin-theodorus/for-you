// The one place a real user writes to the world (plan.md §8). Posting may trigger a few
// budget-capped persona reactions; the 280-char bound is the same one the personas get.

import styles from "./Composer.module.css";

const MAX_CHARS = 280;

interface ComposerProps {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  react: boolean;
  onReactChange: (next: boolean) => void;
  viewer: string | null;
  posting: boolean;
  /** Budget is spent — publishing still works, but no persona will reply. */
  exhausted?: boolean;
}

export function Composer({
  value,
  onChange,
  onSubmit,
  react,
  onReactChange,
  viewer,
  posting,
  exhausted,
}: ComposerProps) {
  const remaining = MAX_CHARS - value.length;
  const overflow = remaining < 0;
  const canPost = Boolean(viewer) && value.trim().length > 0 && !overflow && !posting;

  return (
    <div className={styles.composer}>
      <textarea
        className={styles.input}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={
          viewer ? `Post something as @${viewer}…` : "Loading the world…"
        }
        rows={3}
        disabled={!viewer || posting}
      />

      <div className={styles.footer}>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={react}
            onChange={(event) => onReactChange(event.target.checked)}
            disabled={posting}
          />
          <span>Let personas react</span>
        </label>

        <div className={styles.actions}>
          <span
            className={`mono ${styles.counter} ${overflow ? styles.counterOver : ""}`}
          >
            {remaining}
          </span>
          <button className={styles.post} onClick={onSubmit} disabled={!canPost}>
            {posting ? "Posting…" : "Post"}
          </button>
        </div>
      </div>

      {react && exhausted && (
        <p className={styles.note}>
          Today’s reaction budget is spent — this will publish, but no persona will reply.
        </p>
      )}
    </div>
  );
}
