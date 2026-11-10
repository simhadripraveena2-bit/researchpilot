import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { GOAL_LABELS } from "./labels";

export function Dashboard() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
  if (projects.isError) return <ErrorNotice error={projects.error} />;
  if (projects.isPending) return <p>Loading your projects…</p>;
  if (projects.data.length === 0)
    return (
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold">Welcome</h1>
        <p>Start with a research topic, and ResearchPilot will guide you from there.</p>
        <Link to="/projects/new" className="text-indigo-700 underline">
          Create your first project
        </Link>
      </section>
    );
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Your projects</h1>
      <ul className="divide-y rounded-md border bg-white dark:bg-slate-900">
        {projects.data.map((p) => (
          <li key={p.id} className="p-4">
            <Link to={`/projects/${p.id}`} className="font-medium text-indigo-700 underline">
              {p.title}
            </Link>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {GOAL_LABELS[p.goal]}
              {p.status === "archived" ? " · archived" : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
