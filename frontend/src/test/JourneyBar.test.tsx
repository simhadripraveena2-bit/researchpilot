import { render, screen } from "@testing-library/react";
import { JourneyBar } from "../components/JourneyBar";
import type { Journey } from "../api/types";

const journey: Journey = {
  stages: ["Discover", "Learn", "Understand", "Filter", "Compare", "Investigate", "Validate",
    "Experiment", "Propose"].map((title, i) => ({
    key: title.toLowerCase(),
    title,
    state: i === 0 ? "ready" : "not_ready",
    needs: i === 0 ? null : "Find papers first",
    available_from: "R1",
  })),
  next_step: { stage: "discover", action: "Find papers for your topic" },
};

test("shows all nine stages and one next step", () => {
  render(<JourneyBar journey={journey} />);
  expect(screen.getAllByRole("listitem")).toHaveLength(9);
  expect(screen.getByText("Find papers for your topic")).toBeInTheDocument();
  expect(screen.getByText(/Discover/).closest("li")).toHaveTextContent("ready");
});
