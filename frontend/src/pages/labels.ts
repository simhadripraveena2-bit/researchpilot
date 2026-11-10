import type { ExpertiseLevel, ProjectGoal } from "../api/types";

export const LEVEL_LABELS: Record<ExpertiseLevel, string> = {
  beginner: "New to it",
  intermediate: "Some background",
  advanced: "Expert",
};

export const GOAL_LABELS: Record<ProjectGoal, string> = {
  learn_field: "Learn the field",
  review_literature: "Review the literature",
  find_gap: "Find a research gap",
  plan_experiment: "Plan an experiment",
  write_proposal: "Write a proposal",
  track_field: "Keep up with the field",
};
