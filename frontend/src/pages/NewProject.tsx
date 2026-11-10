import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ExpertiseLevel, ProjectGoal } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { GOAL_LABELS, LEVEL_LABELS } from "./labels";

export function NewProject() {
  const [topic, setTopic] = useState("");
  const [level, setLevel] = useState<ExpertiseLevel>("beginner");
  const [goal, setGoal] = useState<ProjectGoal>("learn_field");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createProject({ topic, expertise_level: level, goal }),
    onSuccess: async ({ id }) => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${id}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <form onSubmit={submit} className="max-w-xl space-y-6">
      <h1 className="text-2xl font-semibold">Start a research project</h1>
      <label className="block space-y-1">
        <span className="font-medium">What do you want to research?</span>
        <textarea
          required
          minLength={3}
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          rows={3}
          className="w-full rounded-md border p-2 dark:bg-slate-900"
          placeholder="e.g. graph neural networks for drug discovery"
        />
      </label>
      <fieldset className="space-y-1">
        <legend className="font-medium">Your experience with this topic</legend>
        {(Object.keys(LEVEL_LABELS) as ExpertiseLevel[]).map((value) => (
          <label key={value} className="mr-4 inline-flex items-center gap-2">
            <input
              type="radio"
              name="level"
              checked={level === value}
              onChange={() => setLevel(value)}
            />
            {LEVEL_LABELS[value]}
          </label>
        ))}
      </fieldset>
      <label className="block space-y-1">
        <span className="font-medium">Your objective</span>
        <select
          value={goal}
          onChange={(e) => setGoal(e.target.value as ProjectGoal)}
          className="w-full rounded-md border p-2 dark:bg-slate-900"
        >
          {(Object.keys(GOAL_LABELS) as ProjectGoal[]).map((value) => (
            <option key={value} value={value}>
              {GOAL_LABELS[value]}
            </option>
          ))}
        </select>
      </label>
      {create.isError && <ErrorNotice error={create.error} />}
      <button
        type="submit"
        disabled={create.isPending}
        className="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white disabled:opacity-60"
      >
        {create.isPending ? "Creating…" : "Start"}
      </button>
    </form>
  );
}
