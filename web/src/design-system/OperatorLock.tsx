// The locked state of the Operator composer. Replaces the composer only — the budget,
// trends and reactions rails stay visible, because the bounded-cost machinery is the point
// of the tab even for a visitor who can't spend it.

import { useState } from "react";

import styles from "./OperatorLock.module.css";

interface OperatorLockProps {
  onUnlock: (secret: string) => void;
  unlocking: boolean;
  error: string | null;
}

export function OperatorLock({ onUnlock, unlocking, error }: OperatorLockProps) {
  const [value, setValue] = useState("");
  const canSubmit = value.trim().length > 0 && !unlocking;

  return (
    <form
      className={styles.lock}
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) onUnlock(value);
      }}
    >
      <p className={styles.lede}>
        Writing to the world calls a language model, so this demo keeps the composer behind a
        shared secret. Reader and Analyst are open to everyone.
      </p>

      <div className={styles.row}>
        <input
          className={styles.input}
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Operator secret"
          autoComplete="off"
          disabled={unlocking}
        />
        <button className={styles.unlock} type="submit" disabled={!canSubmit}>
          {unlocking ? "Checking…" : "Unlock"}
        </button>
      </div>

      {error && <p className={styles.error}>{error}</p>}

      <p className={styles.note}>
        The password only keeps passers-by from spending the key — the browser holds it, so
        it's a speed bump, not a security boundary. What actually bounds the cost is the
        daily token and reaction cap in the meter on the right, which applies to everyone.
      </p>
    </form>
  );
}
