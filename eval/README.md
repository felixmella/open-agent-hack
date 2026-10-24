# What the agents add: evaluation

FactSync's agents have two ways of working. Every step has a deterministic path (the matcher, sentence patterns, the rule-based Critic, templates, discovery by cues), and some steps can also use the model, Nemotron 3.5 Lightning through Meterless Nightshift. This evaluation measures what the model changes.

## Method

1. **One input.** `scripts/evaluate.py record` records the rows of the Zetaris views for the comunas in `scope.json` into `snapshot/`, once. Both runs read these rows, so any difference comes from the agents, not from an article edited between runs.
2. **Two runs.** `scripts/evaluate.py run` runs the same scope twice from the snapshot, each on a fresh World Model:
   - **rules**: every agent on its deterministic path, no model calls;
   - **model**: the agents ask the model where they can (the Extractor reads sentences, the Analyst classifies what the matcher can't settle, the Critic judges class fit and faithfulness, the Planner chooses sources, the Editor writes the wording), and fall back to code when a call fails.

   Both runs, with their traces, review queues and World Model audit logs, are in `runs/`.
3. **Every difference.** `scripts/evaluate.py diff` lists every claim the two runs judged differently (`differences.md`, `differences.json`):
   - *extraction*: a figure in the article text that one run kept as a claim about the comuna's population and the other didn't;
   - *verdict*: the same figure, classified differently;
   - *follow-on*: a finding that exists in one run because of an extraction difference (an infobox contradicted by a sentence only one run kept, for example);
   - *critic flag*: a verdict the Critic's model doubted (class doesn't fit, or explanation unfaithful).
4. **Adjudication.** Each difference is judged against its evidence (the sentence as written, the infobox field, INE's figures) in `adjudication.json`: `rules`, `model`, `both` or `neither` was right, with a note. Critic flags are judged `flag right` or `flag wrong`. **These judgments were made by Claude (the AI coding assistant that built FactSync), not by an independent annotator.** Every one lists its evidence in `differences.md`, so anyone can check it.
5. **Score.** `scripts/evaluate.py score` counts the adjudicated outcomes into `results.json`; `results.md` reads them.

## How a figure is judged

- **Is it the comuna's population?** A sentence about the town, a locality, men or women, households, voters, people registered with FONASA, or the urban area is not a claim about the comuna's population. Keeping it is an extraction error; dropping it is right.
- **Is the year right?** The year a claim states is the year the sentence gives that figure, not another year in the sentence.
- **Is the class right?** The classes are defined in `app/knowledge/taxonomy.py`. A figure that equals an official figure under another definition (an INE projection, an urban population) is *different definition*; a real count under the wrong year is *mislabelled vintage*; one digit off a count is a *likely error* only when nothing else explains it; a figure nothing explains is an *unexplained mismatch*, and saying so is right when no source read explains it.

## Limits

One recorded input, a few comunas chosen because they are rich in hard cases (and two plain ones), one model run. The model's output varies between runs, so this measures one run of it, not its average. The numbers say what the model changed here, not FactSync's accuracy over the country.
