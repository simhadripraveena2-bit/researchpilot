import { Link, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <header className="mb-8 flex items-center justify-between">
        <Link to="/" className="text-xl font-semibold">
          ResearchPilot
        </Link>
        <Link
          to="/projects/new"
          className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          New project
        </Link>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
