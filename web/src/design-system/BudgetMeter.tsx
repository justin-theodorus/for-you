// Today's LLM spend against today's hard caps (plan.md §8). This is the honest cost panel:
// the numbers come from `budget_ledger`, the same rows the trigger reads before it decides
// whether it may generate anything at all.

import type { BudgetStatus } from "../api/types";
import styles from "./BudgetMeter.module.css";
import { Meter } from "./primitives";

const WARN_AT = 0.8;

function barColor(fraction: number): string {
  if (fraction >= 1) return "var(--penalty)";
  if (fraction >= WARN_AT) return "var(--warn)";
  return "var(--positive)";
}

export function BudgetMeter({ budget }: { budget: BudgetStatus | null }) {
  if (!budget) {
    return <p className={styles.empty}>Budget unavailable.</p>;
  }

  const tokenFraction = budget.tokens_used / Math.max(1, budget.tokens_cap);
  const reactionFraction = budget.reactions_used / Math.max(1, budget.reactions_cap);

  return (
    <div className={styles.wrap}>
      <Meter
        label="Tokens"
        value={tokenFraction}
        fraction={tokenFraction}
        color={barColor(tokenFraction)}
        display={`${budget.tokens_used.toLocaleString()} / ${budget.tokens_cap.toLocaleString()}`}
      />
      <Meter
        label="Reactions"
        value={reactionFraction}
        fraction={reactionFraction}
        color={barColor(reactionFraction)}
        display={`${budget.reactions_used} / ${budget.reactions_cap}`}
      />
      <p className={styles.foot}>
        {budget.exhausted ? (
          <span className={styles.exhausted}>
            Spent for today — the trigger will refuse to generate.
          </span>
        ) : (
          <>
            Resets daily · counting real spend on {budget.day}
          </>
        )}
      </p>
    </div>
  );
}
