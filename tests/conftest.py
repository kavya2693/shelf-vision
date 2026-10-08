import pytest

from shelf_vision.data import SEQ, generate, load_truth
from shelf_vision.planogram import load_catalog, load_planogram


@pytest.fixture(scope="session")
def dataset():
    """The deployment sequences and ground truth (generated once if missing; the training set
    is not needed for the tests)."""
    if not (SEQ / "ground_truth.json").exists():
        generate(training=False)
    plan = load_planogram()
    catalog = {s.sku: s for s in load_catalog()}
    return plan, catalog, load_truth()


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("shelf_vision.graph.get_llm", lambda: None)
