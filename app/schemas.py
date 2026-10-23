"""Run input: which comunas to check, in which Wikipedia languages, with which limits."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Scope(BaseModel):
    cuts: list[str] | None = Field(None, description="INE comuna codes, e.g. ['09203']")
    region: str | None = Field(None, description="a region name, e.g. 'Aysén'")
    comunas: list[str] | None = Field(None, description="comuna names, resolved against INE's list")

    @model_validator(mode="after")
    def exactly_one(self):
        given = [name for name in ("cuts", "region", "comunas") if getattr(self, name)]
        if len(given) != 1:
            raise ValueError("scope needs exactly one of: cuts, region, comunas")
        if self.cuts:
            self.cuts = [str(c).strip().zfill(5) for c in self.cuts]
        return self


class Options(BaseModel):
    max_critic_rounds: int = Field(2, ge=0, le=3)
    use_llm: bool = True


RUN_ID = r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}$"  # also a folder name: no leading dot, so never '.' or '..'


class RunInput(BaseModel):
    run_id: str | None = Field(None, pattern=RUN_ID)
    scope: Scope
    languages: list[Literal["es", "en"]] = ["es", "en"]
    options: Options = Options()
