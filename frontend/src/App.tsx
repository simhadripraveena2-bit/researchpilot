import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { NewProject } from "./pages/NewProject";
import { ObjectivePage } from "./pages/ObjectivePage";
import { ProjectOverview } from "./pages/ProjectOverview";
import { RunView } from "./pages/RunView";

export const routes = [
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/projects/new", element: <NewProject /> },
      { path: "/projects/:projectId", element: <ProjectOverview /> },
      { path: "/projects/:projectId/objective", element: <ObjectivePage /> },
      { path: "/projects/:projectId/runs/:runId", element: <RunView /> },
    ],
  },
];

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });
const router = createBrowserRouter(routes);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
