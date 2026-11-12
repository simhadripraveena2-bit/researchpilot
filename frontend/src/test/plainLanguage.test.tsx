// UX-4: default screens never show internal jargon.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../App";

const BANNED = [/\bagents?\b/i, /\bembeddings?\b/i, /\bvectors?\b/i, /langgraph/i, /\bLLM\b/,
  /\btokens?\b/i, /\bprompts?\b/i, /api key/i, /\bsignals?\b/i, /stage [ab]\b/i];

const project = {
  id: "p1", title: "GNNs for drug discovery", topic: "graph neural networks",
  expertise_level: "beginner", goal: "learn_field", status: "active",
  created_at: "2026-11-10T10:00:00Z", updated_at: "2026-11-10T10:00:00Z",
};
const journey = {
  stages: [{ key: "discover", title: "Discover", state: "ready", needs: null, available_from: "R1" }],
  next_step: { stage: "discover", action: "Find papers for your topic" },
};

function mockFetch() {
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const path = String(url);
    if (path.includes("/objective")) {
      // A new project has no objective yet.
      const problem = { title: "Not found", status: 404, code: "not_found" };
      return new Response(JSON.stringify(problem), { status: 404 });
    }
    const body = path.endsWith("/journey") ? journey
      : path.endsWith("/runs") ? []
      : path.endsWith("/projects") ? [project]
      : project;
    return new Response(JSON.stringify(body), { status: 200 });
  }) as typeof fetch;
}

test.each(["/", "/projects/new", "/projects/p1", "/projects/p1/objective"])("no internal jargon on %s", async (path) => {
  mockFetch();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(container.textContent).not.toMatch(/Loading/));
  expect(container.textContent).not.toMatch(/Unexpected Application Error|Something went wrong/);
  for (const pattern of BANNED) expect(container.textContent).not.toMatch(pattern);
});
