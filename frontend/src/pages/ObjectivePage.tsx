import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { ObjectiveContent, ObjectiveVersion } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";

// Basic objective editor (M1a): the core fields as plain text, one item per line. Every save
// creates a new version; earlier versions stay available below.

type ListField =
  | "subdomains"
  | "target_tasks"
  | "problem_areas"
  | "focus_concepts"
  | "keywords"
  | "exclusions"
  | "expected_outcomes";

const LIST_FIELDS: { field: ListField; label: string; hint: string }[] = [
  { field: "target_tasks", label: "Tasks", hint: "e.g. molecular property prediction" },
  { field: "problem_areas", label: "Problems you care about", hint: "e.g. small datasets" },
  { field: "keywords", label: "Keywords", hint: "words papers would use" },
  { field: "focus_concepts", label: "Related concepts to cover", hint: "" },
  { field: "subdomains", label: "Subfields", hint: "" },
  { field: "exclusions", label: "Out of scope", hint: "topics or methods to leave out" },
  { field: "expected_outcomes", label: "What you hope to get", hint: "e.g. a reading list" },
];

const EMPTY: ObjectiveContent = {
  core_question: "",
  sub_questions: [],
  domain: null,
  subdomains: [],
  target_tasks: [],
  problem_areas: [],
  focus_concepts: [],
  keywords: [],
  synonyms: {},
  exclusions: [],
  constraints: {},
  expected_outcomes: [],
  user_context: null,
  notes: null,
};

/** Only the editable fields: the API rejects anything else. */
function toContent(v: ObjectiveVersion): ObjectiveContent {
  const content = { ...EMPTY };
  for (const key of Object.keys(EMPTY) as (keyof ObjectiveContent)[]) {
    if (key !== "sub_questions") Object.assign(content, { [key]: v[key] });
  }
  content.sub_questions = v.sub_questions.map((s) => ({ key: s.key, text: s.text }));
  return content;
}

const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

export function ObjectivePage() {
  const { projectId = "" } = useParams();
  const client = useQueryClient();
  const [viewing, setViewing] = useState<number | undefined>(undefined);
  const objective = useQuery({
    queryKey: ["objective", projectId, viewing],
    queryFn: () => api.getObjective(projectId, viewing),
    retry: false,
  });
  const versions = useQuery({
    queryKey: ["objective-versions", projectId],
    queryFn: () => api.objectiveVersions(projectId),
    retry: false,
  });
  const refresh = () => {
    setViewing(undefined);
    return client.invalidateQueries({ queryKey: ["objective", projectId] }).then(() =>
      client.invalidateQueries({ queryKey: ["objective-versions", projectId] }),
    );
  };
  const activate = useMutation({
    mutationFn: (version: number) => api.activateObjective(projectId, version),
    onSuccess: refresh,
  });

  const notFound =
    objective.isError && objective.error instanceof ApiError && objective.error.problem.status === 404;
  if (objective.isPending) return <p>Loading…</p>;
  if (objective.isError && !notFound) return <ErrorNotice error={objective.error} />;
  const current = objective.data;

  return (
    <section className="space-y-8">
      <div>
        <Link to={`/projects/${projectId}`} className="text-sm text-indigo-700 underline">
          Back to project
        </Link>
        <h1 className="text-2xl font-semibold">Research objective</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          What you want to find out. Each change is saved as a new version; earlier versions are
          kept, and past searches stay linked to the version they used.
        </p>
      </div>

      {current && !current.is_active && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          You are looking at version {current.version}, which is not in use.{" "}
          <button className="underline" onClick={() => activate.mutate(current.version)}>
            Use this version
          </button>{" "}
          ·{" "}
          <button className="underline" onClick={() => setViewing(undefined)}>
            Back to the version in use
          </button>
        </div>
      )}
      {activate.isError && <ErrorNotice error={activate.error} />}

      {current && <CompletenessNotice objective={current} />}

      <ObjectiveForm
        key={current ? `${current.id}` : "new"}
        projectId={projectId}
        current={current && current.is_active ? current : undefined}
        readOnly={Boolean(current && !current.is_active)}
        initial={current ? toContent(current) : EMPTY}
        onSaved={refresh}
      />

      {versions.data && versions.data.length > 0 && (
        <div>
          <h2 className="mb-2 font-medium">Versions</h2>
          <ul className="space-y-1 text-sm">
            {versions.data.map((v) => (
              <li key={v.id}>
                <button className="text-indigo-700 underline" onClick={() => setViewing(v.version)}>
                  Version {v.version}
                </button>{" "}
                {v.is_active && <span className="font-medium">(in use)</span>} ·{" "}
                {new Date(v.created_at).toLocaleString()}
                {v.change_summary && <> · {v.change_summary}</>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function CompletenessNotice({ objective }: { objective: ObjectiveVersion }) {
  const { complete, missing } = objective.completeness;
  if (complete) return <p className="text-sm text-green-800">This objective is complete.</p>;
  return (
    <div className="rounded-md border bg-white p-3 text-sm dark:bg-slate-900">
      <p className="font-medium">To get better results:</p>
      <ul className="list-disc pl-5">
        {missing.map((m) => (
          <li key={m.field}>{m.message}</li>
        ))}
      </ul>
    </div>
  );
}

function ObjectiveForm({
  projectId,
  current,
  readOnly,
  initial,
  onSaved,
}: {
  projectId: string;
  current: ObjectiveVersion | undefined;
  readOnly: boolean;
  initial: ObjectiveContent;
  onSaved: () => Promise<unknown>;
}) {
  const [question, setQuestion] = useState(initial.core_question);
  const [domain, setDomain] = useState(initial.domain ?? "");
  const [subQuestions, setSubQuestions] = useState(initial.sub_questions);
  const [lists, setLists] = useState<Record<ListField, string>>(() =>
    Object.fromEntries(LIST_FIELDS.map(({ field }) => [field, initial[field].join("\n")])) as Record<
      ListField,
      string
    >,
  );
  const [context, setContext] = useState(initial.user_context ?? "");
  const [notes, setNotes] = useState(initial.notes ?? "");

  const save = useMutation({
    mutationFn: () => {
      const body: ObjectiveContent = {
        ...initial, // keeps synonyms and constraints, which this page does not edit yet
        core_question: question,
        domain: domain.trim() || null,
        sub_questions: subQuestions.filter((s) => s.text.trim()),
        ...(Object.fromEntries(LIST_FIELDS.map(({ field }) => [field, lines(lists[field])])) as Record<
          ListField,
          string[]
        >),
        user_context: context.trim() || null,
        notes: notes.trim() || null,
      };
      return current
        ? api.updateObjective(projectId, { ...body, base_version: current.version })
        : api.createObjective(projectId, body);
    },
    onSuccess: onSaved,
  });
  const conflict =
    save.isError && save.error instanceof ApiError && save.error.problem.status === 409;

  const input = "w-full rounded-md border p-2 dark:bg-slate-900";
  return (
    <form
      className="max-w-2xl space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <fieldset disabled={readOnly || save.isPending} className="space-y-5">
        <label className="block space-y-1">
          <span className="font-medium">Main research question</span>
          <textarea required rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} className={input} />
        </label>
        <div className="space-y-2">
          <span className="font-medium">Sub-questions</span>
          {subQuestions.map((s, i) => (
            <div key={s.key ?? `new-${i}`} className="flex items-center gap-2">
              <span className="w-10 text-sm text-slate-500">{s.key ?? "new"}</span>
              <input
                aria-label={`Sub-question ${i + 1}`}
                value={s.text}
                onChange={(e) =>
                  setSubQuestions(subQuestions.map((q, j) => (j === i ? { ...q, text: e.target.value } : q)))
                }
                className={input}
              />
              {!readOnly && (
                <button
                  type="button"
                  className="text-sm text-red-700 underline"
                  onClick={() => setSubQuestions(subQuestions.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          {!readOnly && subQuestions.length < 6 && (
            <button
              type="button"
              className="text-sm text-indigo-700 underline"
              onClick={() => setSubQuestions([...subQuestions, { text: "" }])}
            >
              Add a sub-question
            </button>
          )}
        </div>
        <label className="block space-y-1">
          <span className="font-medium">Research area</span>
          <input value={domain} onChange={(e) => setDomain(e.target.value)} className={input} />
        </label>
        {LIST_FIELDS.map(({ field, label, hint }) => (
          <label key={field} className="block space-y-1">
            <span className="font-medium">{label}</span>{" "}
            <span className="text-sm text-slate-500">one per line{hint && `; ${hint}`}</span>
            <textarea
              rows={2}
              value={lists[field]}
              onChange={(e) => setLists({ ...lists, [field]: e.target.value })}
              className={input}
            />
          </label>
        ))}
        <label className="block space-y-1">
          <span className="font-medium">About you and your situation</span>
          <textarea rows={2} value={context} onChange={(e) => setContext(e.target.value)} className={input} />
        </label>
        <label className="block space-y-1">
          <span className="font-medium">Notes</span>
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} className={input} />
        </label>
      </fieldset>
      {conflict ? (
        <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          Someone else changed this objective while you were editing. Your changes were not saved.{" "}
          <button type="button" className="underline" onClick={() => void onSaved()}>
            Load the latest version
          </button>
        </p>
      ) : (
        save.isError && <ErrorNotice error={save.error} />
      )}
      {!readOnly && (
        <button
          type="submit"
          disabled={save.isPending}
          className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {current ? "Save as a new version" : "Save objective"}
        </button>
      )}
    </form>
  );
}
