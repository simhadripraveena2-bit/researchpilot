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

export interface SubQuestion {
  id: string;
  key: string;
  text: string;
  ordinal: number;
}

export interface Issue {
  field: string;
  code: string;
  message: string;
}

export interface Completeness {
  complete: boolean;
  errors: Issue[];
  missing: Issue[];
}

/** Fields the user edits; one version of the research objective holds all of them. */
export interface ObjectiveContent {
  core_question: string;
  sub_questions: { key?: string | null; text: string }[];
  domain: string | null;
  subdomains: string[];
  target_tasks: string[];
  problem_areas: string[];
  focus_concepts: string[];
  keywords: string[];
  synonyms: Record<string, string[]>;
  exclusions: string[];
  constraints: Record<string, unknown>;
  expected_outcomes: string[];
  user_context: string | null;
  notes: string | null;
}

export interface ObjectiveVersion extends Omit<ObjectiveContent, "sub_questions"> {
  id: string;
  project_id: string;
  version: number;
  is_active: boolean;
  sub_questions: SubQuestion[];
  expertise_level: ExpertiseLevel;
  goal: ProjectGoal;
  source: "planner" | "user_edit" | "feedback_suggestion";
  based_on_version: number | null;
  change_summary: string | null;
  created_at: string;
  completeness: Completeness;
}

export interface ObjectiveVersionSummary {
  id: string;
  version: number;
  is_active: boolean;
  core_question: string;
  based_on_version: number | null;
  change_summary: string | null;
  created_at: string;
}
