// The objective page: create, edit as a new version (only editable fields are sent),
// version history, and the "someone else changed it" message on 409.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../App";

const v1 = {
  id: "o1", project_id: "p1", version: 1, is_active: true,
  core_question: "Which GNNs work best?",
  sub_questions: [{ id: "s1", key: "SQ1", text: "Which benchmarks?", ordinal: 1 }],
  domain: "machine learning", subdomains: [], target_tasks: ["property prediction"],
  problem_areas: [], focus_concepts: [], keywords: ["GNN"], synonyms: { GNN: ["graph network"] },
  exclusions: [], constraints: { compute: { gpu_hours: 10 } }, expected_outcomes: [],
  user_context: null, notes: null, expertise_level: "beginner", goal: "find_gap",
  source: "user_edit", based_on_version: null, change_summary: null,
  created_at: "2026-11-10T10:00:00Z",
  completeness: {
    complete: false, errors: [],
    missing: [{ field: "sub_questions", code: "missing", message: "add at least 2 sub-questions" }],
  },
};

type Call = { method: string; path: string; body?: unknown };

function mockFetch(handler: (call: Call) => [number, unknown]) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const call = {
      method: init?.method ?? "GET",
      path: String(url),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const [status, body] = handler(call);
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch;
  return calls;
}

function renderPage() {
  const router = createMemoryRouter(routes, { initialEntries: ["/projects/p1/objective"] });
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const notFound = [404, { title: "Not found", status: 404, code: "not_found", detail: "none" }] as [number, unknown];

test("creates the first version", async () => {
  let created = false;
  const calls = mockFetch((c) => {
    if (c.method === "POST") {
      created = true;
      return [201, v1];
    }
    if (c.path.endsWith("/versions")) return created ? [200, [v1]] : notFound;
    return created ? [200, v1] : notFound;
  });
  renderPage();
  const question = await screen.findByLabelText("Main research question");
  fireEvent.change(question, { target: { value: "Which GNNs work best?" } });
  fireEvent.click(screen.getByText("Add a sub-question"));
  fireEvent.change(screen.getByLabelText("Sub-question 1"), { target: { value: "Which benchmarks?" } });
  fireEvent.click(screen.getByText("Save objective"));
  await screen.findByText("Save as a new version");
  const post = calls.find((c) => c.method === "POST");
  expect(post?.path).toBe("/api/v1/projects/p1/objective");
  expect(post?.body).toMatchObject({
    core_question: "Which GNNs work best?",
    sub_questions: [{ text: "Which benchmarks?" }],
  });
  expect(screen.getByText("add at least 2 sub-questions")).toBeInTheDocument();
});

test("edits create a new version based on the active one and keep unedited fields", async () => {
  const calls = mockFetch((c) => {
    if (c.method === "PUT") return [201, { ...v1, version: 2 }];
    if (c.path.endsWith("/versions")) return [200, [v1]];
    return [200, v1];
  });
  renderPage();
  const question = await screen.findByLabelText("Main research question");
  fireEvent.change(question, { target: { value: "Which GNNs work best on small data?" } });
  fireEvent.click(screen.getByText("Save as a new version"));
  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
  const body = calls.find((c) => c.method === "PUT")?.body as Record<string, unknown>;
  expect(body.base_version).toBe(1);
  expect(body.core_question).toBe("Which GNNs work best on small data?");
  expect(body.sub_questions).toEqual([{ key: "SQ1", text: "Which benchmarks?" }]);
  expect(body.constraints).toEqual({ compute: { gpu_hours: 10 } });
  expect(body.synonyms).toEqual({ GNN: ["graph network"] });
  for (const field of ["id", "version", "is_active", "completeness", "created_at", "source"]) {
    expect(body).not.toHaveProperty(field);
  }
});

test("a conflicting edit is reported and not silently overwritten", async () => {
  mockFetch((c) => {
    if (c.method === "PUT") return [409, { title: "Conflict", status: 409, code: "conflict" }];
    if (c.path.endsWith("/versions")) return [200, [v1]];
    return [200, v1];
  });
  renderPage();
  fireEvent.click(await screen.findByText("Save as a new version"));
  expect(await screen.findByText(/Someone else changed this objective/)).toBeInTheDocument();
});

test("an earlier version is read-only until it is put back in use", async () => {
  const v2 = { ...v1, id: "o2", version: 2, change_summary: "narrowed" };
  const calls = mockFetch((c) => {
    if (c.method === "POST") return [200, { ...v1 }];
    if (c.path.endsWith("/versions")) return [200, [v2, { ...v1, is_active: false }]];
    if (c.path.includes("version=1")) return [200, { ...v1, is_active: false }];
    return [200, v2];
  });
  renderPage();
  fireEvent.click(await screen.findByText("Version 1"));
  await screen.findByText(/which is not in use/);
  expect(screen.queryByText("Save as a new version")).not.toBeInTheDocument();
  expect(screen.queryByText("Remove")).not.toBeInTheDocument();
  expect(screen.queryByText("Add a sub-question")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Use this version"));
  await waitFor(() =>
    expect(calls.find((c) => c.method === "POST")).toMatchObject({
      path: "/api/v1/projects/p1/objective/active",
      body: { version: 1 },
    }),
  );
});
