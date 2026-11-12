import type {
  Checkpoint,
  Journey,
  ObjectiveContent,
  ObjectiveVersion,
  ObjectiveVersionSummary,
  Problem,
  Project,
  Run,
  RunEvent,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(public problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const problem = (await resp.json().catch(() => ({
      title: resp.statusText,
      status: resp.status,
      code: "http_error",
    }))) as Problem;
    throw new ApiError(problem);
  }
  return (resp.status === 204 ? undefined : await resp.json()) as T;
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (body: Pick<Project, "topic" | "expertise_level" | "goal">) =>
    request<{ id: string }>("/projects", { method: "POST", body: JSON.stringify(body) }),
  journey: (id: string) => request<Journey>(`/projects/${id}/journey`),
  listRuns: (projectId: string) => request<Run[]>(`/projects/${projectId}/runs`),
  startSystemCheck: (projectId: string) =>
    request<{ id: string }>(`/projects/${projectId}/runs`, {
      method: "POST",
      body: JSON.stringify({ workflow: "dummy" }),
    }),
  getRun: (id: string) => request<Run>(`/runs/${id}`),
  checkpoints: (runId: string) => request<Checkpoint[]>(`/runs/${runId}/checkpoints`),
  decide: (checkpointId: string, status: "approved" | "rejected") =>
    request<{ status: string }>(`/checkpoints/${checkpointId}/decision`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  getObjective: (projectId: string, version?: number) =>
    request<ObjectiveVersion>(
      `/projects/${projectId}/objective${version ? `?version=${version}` : ""}`,
    ),
  objectiveVersions: (projectId: string) =>
    request<ObjectiveVersionSummary[]>(`/projects/${projectId}/objective/versions`),
  createObjective: (projectId: string, body: ObjectiveContent) =>
    request<ObjectiveVersion>(`/projects/${projectId}/objective`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** Saves an edit as a new version; 409 if another edit came first. */
  updateObjective: (
    projectId: string,
    body: ObjectiveContent & { base_version: number; change_summary?: string },
  ) =>
    request<ObjectiveVersion>(`/projects/${projectId}/objective`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  activateObjective: (projectId: string, version: number) =>
    request<ObjectiveVersion>(`/projects/${projectId}/objective/active`, {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
};

/** Subscribe to a run's progress (Server-Sent Events). Returns an unsubscribe function. */
export function subscribeToRun(runId: string, onEvent: (event: RunEvent) => void): () => void {
  const source = new EventSource(`${BASE}/runs/${runId}/events`);
  source.addEventListener("run_event", (msg) => {
    onEvent(JSON.parse((msg as MessageEvent<string>).data) as RunEvent);
  });
  return () => source.close();
}
