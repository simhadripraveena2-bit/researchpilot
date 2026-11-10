import { ApiError } from "../api/client";

export function ErrorNotice({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.message
      : "Something went wrong. Please try again in a moment.";
  return (
    <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
      {message}
    </p>
  );
}
