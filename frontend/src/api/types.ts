// Mirrors the backend API schemas (backend/src/researchpilot/api/schemas.py).
// R1 replaces this file with types generated from the OpenAPI document.

export type ExpertiseLevel = "beginner" | "intermediate" | "advanced";
export type ProjectGoal =
  | "learn_field"
  | "review_literature"
  | "find_gap"
  | "plan_experiment"
  | "write_proposal"
  | "track_field";
export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "succeeded"
  | "partially_succeeded"
  | "failed"
  | "cancelled";
export type StageState = "done" | "in_progress" | "ready" | "not_ready";

export interface Project {
  id: string;
  title: string;
  topic: string;
  expertise_level: ExpertiseLevel;
  goal: ProjectGoal;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface StageView {
  key: string;
  title: string;
  state: StageState;
  needs: string | null;
  available_from: string;
}

export interface Journey {
  stages: StageView[];
  next_step: { stage: string; action: string };
}

export interface Run {
  id: string;
  project_id: string;
  workflow: string;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunEvent {
  id: number;
  ts: string;
  level: string;
  type: string;
  message: string;
  data: Record<string, unknown>;
}

export interface Checkpoint {
  id: string;
  run_id: string;
  name: string;
  payload: { question?: string } & Record<string, unknown>;
  status: "pending" | "approved" | "modified" | "rejected";
}

export interface Problem {
  title: string;
  status: number;
  code: string;
  detail?: string;
}
