"""Run state: what the orchestrator knows about each comuna while the agents work on it, and the caps that keep every
loop finite (Critic rounds, discovery steps, draft revisions, model calls)."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Caps:
    max_critic_rounds: int = 2      # fixes the Critic may send back per comuna before what still fails is escalated
    max_discoveries: int = 3        # sources the Planner may add to a run (from the catalog)
    max_draft_revisions: int = 1    # revisions the Editor gets per draft
    max_llm_calls: int = 60         # model requests per run; past it every agent takes its deterministic path

    @classmethod
    def for_run(cls, options, comunas):
        return cls(max_critic_rounds=options.max_critic_rounds, max_llm_calls=min(200, 12 + 14 * comunas))


@dataclass
class ComunaState:
    cut: str
    name: str
    status: str = "pending"         # pending, then approved, partial (some findings escalated) or escalated
    findings: list = field(default_factory=list)       # the Analyst's latest findings
    checks: list = field(default_factory=list)         # claims found consistent, or that can't be checked
    reviews: list = field(default_factory=list)        # the Critic's review of each round
    approved: dict = field(default_factory=dict)       # finding id -> signature the Critic approved
    llm_verdicts: dict = field(default_factory=dict)   # the Analyst's model verdicts, reused while the facts hold
    drafts: dict = field(default_factory=dict)
    draft_reviews: list = field(default_factory=list)
    escalations: list = field(default_factory=list)

    @property
    def entity_id(self):
        return f"comuna:cut:{self.cut}"


@dataclass
class RunState:
    run_id: str
    caps: Caps
    comunas: dict                                      # cut -> ComunaState
    observed: set = field(default_factory=set)         # ids of the observations this run read or extracted
    declined: dict = field(default_factory=dict)       # sources the Planner considered and didn't add -> reason
    discoveries: list = field(default_factory=list)
    escalations: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def pending(self):
        return [c for c in self.comunas.values() if c.status == "pending"]
