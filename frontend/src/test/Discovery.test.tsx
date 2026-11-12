// Finding papers: start from the project page; the run page shows the objective version, the
// search plan question, and afterwards what was found per source (with a retry for failures).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../App";

class SilentEventSource {
  addEventListener() {}
  close() {}
}

const run = {
  id: "r1", project_id: "p1", workflow: "discovery", status: "partially_succeeded",
  objective_version: 2, created_at: "2026-11-12T10:00:00Z", started_at: null, finished_at: null,
};
const summary = {
  run_id: "r1", status: "partially_succeeded", objective_version: 2,
  searches: { planned: 16, succeeded: 9 },
  sources: [
    { source: "arxiv_api", state: "ok", queries: 4, succeeded: 4 },
    { source: "openalex", state: "budget_exhausted", queries: 4, succeeded: 0 },
  ],
  papers: { total: 12, added: 11, already_in_project: 1, flagged: 0 },
  version_matching: { merges: 1, possible_matches_awaiting_review: 2 },
  excluded_terms: [],
};

type Call = { method: string; path: string };

function mockFetch(handler: (c: Call) => [number, unknown]) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const call = { method: init?.method ?? "GET", path: String(url) };
    calls.push(call);
    const [status, body] = handler(call);
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch;
  return calls;
}

function renderAt(path: string) {
  globalThis.EventSource = SilentEventSource as unknown as typeof EventSource;
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

test("a finished discovery run shows what was found and offers a retry", async () => {
  const calls = mockFetch((c) => {
    if (c.path.endsWith("/discovery/summary")) return [200, summary];
    if (c.path.endsWith("/checkpoints")) return [200, []];
    if (c.path.endsWith("/retry")) return [202, { status: "queued" }];
    return [200, run];
  });
  renderAt("/projects/p1/runs/r1");
  expect(await screen.findByText("Finding papers")).toBeInTheDocument();
  expect(screen.getByText("Using version 2 of your research objective")).toBeInTheDocument();
  expect(await screen.findByText(/12 papers \(11 new to your project\)/)).toBeInTheDocument();
  expect(screen.getByText(/9 of 16 searches/)).toBeInTheDocument();
  expect(screen.getByText("OpenAlex: daily limit reached")).toBeInTheDocument();
  expect(screen.getByText(/2 pairs may be versions of the same paper/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Try the failed searches again"));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/v1/runs/r1/retry")).toBe(true),
  );
});

test("finding papers starts a discovery run and opens it", async () => {
  const project = {
    id: "p1", title: "GNNs", topic: "gnn", expertise_level: "beginner", goal: "learn_field",
    status: "active", created_at: "2026-11-10T10:00:00Z", updated_at: "2026-11-10T10:00:00Z",
  };
  const calls = mockFetch((c) => {
    if (c.method === "POST" && c.path.endsWith("/discovery-runs")) {
      return [202, { id: "r9", objective_version: 1 }];
    }
    if (c.path.endsWith("/journey")) {
      return [200, {
        stages: [{ key: "discover", title: "Discover", state: "ready", needs: null, available_from: "R1" }],
        next_step: { stage: "discover", action: "Find papers for your topic" },
      }];
    }
    if (c.path.endsWith("/runs")) return [200, []];
    if (c.path.includes("/runs/r9")) return [200, { ...run, id: "r9", status: "running" }];
    if (c.path.endsWith("/checkpoints")) return [200, []];
    return [200, project];
  });
  const router = renderAt("/projects/p1");
  fireEvent.click(await screen.findByText("Find papers", { selector: "button" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/projects/p1/runs/r9"));
  expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/discovery-runs"))).toBe(true);
});
