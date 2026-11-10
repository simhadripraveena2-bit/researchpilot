import { useEffect, useState } from "react";
import { subscribeToRun } from "./client";
import type { RunEvent } from "./types";

export function useRunEvents(runId: string | undefined): RunEvent[] {
  const [events, setEvents] = useState<RunEvent[]>([]);
  useEffect(() => {
    if (!runId) return undefined;
    setEvents([]);
    return subscribeToRun(runId, (event) =>
      setEvents((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event])),
    );
  }, [runId]);
  return events;
}
