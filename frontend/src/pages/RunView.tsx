import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useRunEvents } from "../api/useRunEvents";
import { ErrorNotice } from "../components/ErrorNotice";

const TERMINAL = new Set(["succeeded", "partially_succeeded", "failed", "cancelled"]);

export function RunView() {
  const { runId = "" } = useParams();
  const queryClient = useQueryClient();
  const events = useRunEvents(runId);
  const lastType = events.at(-1)?.type ?? "";
  // Refresh run status and checkpoints whenever a new progress event arrives.
  const run = useQuery({ queryKey: ["run", runId, events.length], queryFn: () => api.getRun(runId) });
  const checkpoints = useQuery({
    queryKey: ["checkpoints", runId, lastType, events.length],
    queryFn: () => api.checkpoints(runId),
  });
  const decide = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "approved" | "rejected" }) =>
      api.decide(id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["checkpoints", runId] }),
  });
  const pending = checkpoints.data?.find((c) => c.status === "pending");

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">System check</h1>
      {run.data && (
        <p aria-live="polite">
          Status: <strong>{run.data.status.replaceAll("_", " ")}</strong>
        </p>
      )}
      <ol className="space-y-2 border-l pl-4" aria-label="Progress">
        {events.map((e) => (
          <li key={e.id} className={e.level === "error" ? "text-red-700" : undefined}>
            <time className="mr-2 text-xs text-slate-500">
              {new Date(e.ts).toLocaleTimeString()}
            </time>
            {e.message}
          </li>
        ))}
        {events.length === 0 && <li>Connecting…</li>}
      </ol>
      {pending && (
        <div className="rounded-md border border-indigo-300 bg-indigo-50 p-4 dark:bg-indigo-950">
          <p className="mb-3 font-medium">{pending.payload.question ?? "Continue?"}</p>
          {decide.isError && <ErrorNotice error={decide.error} />}
          <div className="flex gap-2">
            <button
              onClick={() => decide.mutate({ id: pending.id, status: "approved" })}
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white"
            >
              Continue
            </button>
            <button
              onClick={() => decide.mutate({ id: pending.id, status: "rejected" })}
              className="rounded-md border px-3 py-2 text-sm"
            >
              Stop
            </button>
          </div>
        </div>
      )}
      {run.data && TERMINAL.has(run.data.status) && <p>This check has finished.</p>}
    </section>
  );
}
