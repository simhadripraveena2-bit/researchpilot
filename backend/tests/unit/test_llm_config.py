"""Task configuration is provisional and provider-independent (D1, R0-8)."""

from researchpilot.core.settings import BACKEND_ROOT, Settings
from researchpilot.llm.adapters.fake import FakeProviderAdapter
from researchpilot.llm.config import load_llm_config
from researchpilot.llm.factory import build_gateway

CONFIG = BACKEND_ROOT / "config" / "llm_tasks.yaml"


def test_config_is_marked_provisional_and_every_task_resolves() -> None:
    config = load_llm_config(CONFIG)
    assert config.provisional is True
    for task in config.tasks:
        resolved = config.for_task(task)
        assert resolved.provider and resolved.model
    assert config.for_task("red_team").parameters["effort"] == "high"
    assert config.for_task("planner").parameters["effort"] == "medium"  # inherited default


def test_manifest_records_provider_model_and_provisional_flag() -> None:
    manifest = load_llm_config(CONFIG).manifest()
    assert manifest["provisional"] is True
    assert manifest["tasks"]["dummy_echo"] == {"provider": "anthropic", "model": "claude-opus-5-5"}


def test_swapping_every_task_to_the_fake_provider_needs_no_code_change() -> None:
    config = load_llm_config(CONFIG).with_provider("fake")
    fake = FakeProviderAdapter()
    gateway = build_gateway(Settings(_env_file=None), config=config, adapters={"fake": fake})
    assert {gateway.config.for_task(t).provider for t in config.tasks} == {"fake"}
    assert gateway.capabilities("planner").structured_output is True
