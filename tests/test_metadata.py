"""metadata.json names real things: every path exists, every agent is a class in its module, every view the agents
read is created by the Zetaris setup scripts, and the engine's tests exist."""
import importlib
import json
import re

from app.config import ROOT

METADATA = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
SETUP_SQL = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "zetaris").glob("*.sql"))


def test_every_agent_is_a_class_in_the_module_named():
    for agent in METADATA["agents"]:
        assert (ROOT / agent["path"]).exists()
        module = importlib.import_module(agent["path"][:-3].replace("/", "."))
        assert getattr(module, agent["name"]).name == agent["name"]


def test_every_view_named_is_created_by_the_setup_scripts():
    created = set(re.findall(r"VIEW\s+(\w+)\s+WITH CONTAINER factsync", SETUP_SQL))
    zetaris = METADATA["zetaris"]
    for view in zetaris["views_read_by_agents"] + zetaris["other_views"]:
        assert view.split(".", 1)[1] in created, view


def test_the_engine_and_its_tests_exist():
    meterless = METADATA["meterless"]
    assert (ROOT / meterless["path"] / "world.py").exists()
    assert all((ROOT / path).exists() for path in meterless["tests"])
    for path in (METADATA["nightshift"]["adapter"], METADATA["orchestration"]["path"]):
        assert (ROOT / path).exists()


def test_each_fact_names_real_code_and_examples():
    for fact in METADATA["facts"].values():
        assert all((ROOT / path).exists() for path in fact["knowledge"] + fact.get("tests", []) + [fact["example"]])
    assert (ROOT / METADATA["facts"]["mayor"]["agents"]).exists()
