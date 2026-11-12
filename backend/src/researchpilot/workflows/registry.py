"""Workflow name -> spec. New workflows register here (R1: discovery, assessment, ...)."""

from __future__ import annotations

from researchpilot.domain.enums import Workflow
from researchpilot.workflows import discovery, dummy
from researchpilot.workflows.base import WorkflowSpec

WORKFLOWS: dict[Workflow, WorkflowSpec] = {
    Workflow.DUMMY: dummy.SPEC,
    Workflow.DISCOVERY: discovery.SPEC,
}
