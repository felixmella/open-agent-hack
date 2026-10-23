"""Structured errors. Everything a run or the API reports as an error has a code, a message, the stage it happened in,
and whether trying again can succeed (`recoverable`). The API answers with `status`."""


class RunError(Exception):
    def __init__(self, code, message, *, stage, recoverable, status=500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.recoverable = recoverable
        self.status = status
        self.result = None  # the error result the run wrote, if it got that far

    def to_dict(self):
        return {"code": self.code, "message": self.message, "stage": self.stage, "recoverable": self.recoverable}


def error_body(error, run_id=None):
    """The JSON body for an error: the same shape from the CLI and the API."""
    return {"run_id": run_id, "status": "error", "error": error.to_dict()}


def invalid_input(validation_error):
    """A RunError for input that fails validation (a pydantic ValidationError), naming each field and problem."""
    problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in validation_error.errors())
    return RunError("invalid_input", problems, stage="input", recoverable=False, status=422)
