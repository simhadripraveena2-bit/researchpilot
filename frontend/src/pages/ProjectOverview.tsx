import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { JourneyBar } from "../components/JourneyBar";
import { GOAL_LABELS, LEVEL_LABELS } from "./labels";

export function ProjectOverview() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.getProject(projectId) });
  const journey = useQuery({ queryKey: ["journey", projectId], queryFn: () => api.journey(projectId) });
  const runs = useQuery({ queryKey: ["runs", projectId], queryFn: () => api.listRuns(projectId) });
  const check = useMutation({
    mutationFn: () => api.startSystemCheck(projectId),
    onSuccess: ({ id }) => navigate(`/projects/${projectId}/runs/${id}`),
  });

  if (project.isError) return <ErrorNotice error={project.error} />;
  if (project.isPending) return <p>Loading…</p>;
  const p = project.data;

  return (
    <section className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">{p.title}</h1>
        <p className="text-slate-600 dark:text-slate-400">
          {GOAL_LABELS[p.goal]} · {LEVEL_LABELS[p.expertise_level]}
        </p>
      </div>
      {journey.data && <JourneyBar journey={journey.data} />}
      <div className="rounded-md border bg-white p-4 dark:bg-slate-900">
        <h2 className="font-medium">System check</h2>
        <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
          Paper search arrives in the next release. Meanwhile you can run a short check that
          everything works, including a step where you are asked to confirm.
        </p>
        {check.isError && <ErrorNotice error={check.error} />}
        <button
          onClick={() => check.mutate()}
          disabled={check.isPending}
          className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          Run a system check
        </button>
      </div>
      {runs.data && runs.data.length > 0 && (
        <div>
          <h2 className="mb-2 font-medium">History</h2>
          <ul className="space-y-1 text-sm">
            {runs.data.map((r) => (
              <li key={r.id}>
                <Link to={`/projects/${projectId}/runs/${r.id}`} className="text-indigo-700 underline">
                  {new Date(r.created_at).toLocaleString()}
                </Link>{" "}
                · {r.status.replaceAll("_", " ")}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
