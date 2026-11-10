import type { Journey, StageState } from "../api/types";

const MARK: Record<StageState, string> = {
  done: "✓",
  in_progress: "●",
  ready: "○",
  not_ready: "◌",
};

const LABEL: Record<StageState, string> = {
  done: "done",
  in_progress: "in progress",
  ready: "ready",
  not_ready: "not ready yet",
};

export function JourneyBar({ journey }: { journey: Journey }) {
  return (
    <nav aria-label="Research journey" className="space-y-3">
      <ol className="flex flex-wrap gap-2">
        {journey.stages.map((stage) => (
          <li
            key={stage.key}
            title={stage.needs ?? LABEL[stage.state]}
            className={
              "rounded-full border px-3 py-1 text-sm " +
              (stage.key === journey.next_step.stage
                ? "border-indigo-500 bg-indigo-50 font-medium dark:bg-indigo-950"
                : "border-slate-300 dark:border-slate-700")
            }
          >
            <span aria-hidden="true">{MARK[stage.state]} </span>
            {stage.title}
            <span className="sr-only">: {LABEL[stage.state]}</span>
          </li>
        ))}
      </ol>
      <p className="text-sm">
        <span className="font-medium">Next step: </span>
        {journey.next_step.action}
      </p>
    </nav>
  );
}
