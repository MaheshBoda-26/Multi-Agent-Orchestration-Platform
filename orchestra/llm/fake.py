import asyncio
import json
import os
import signal
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel
from .provider import LLMProvider, LLMResponse

T = TypeVar("T", bound=BaseModel)


def _default_plan() -> str:
    return json.dumps({
        "tasks": [
            {
                "id": "t1",
                "description": "Gather information for the request",
                "specialist": "researcher",
                "dependencies": [],
            },
            {
                "id": "t2",
                "description": "Write up the final answer",
                "specialist": "writer",
                "dependencies": ["t1"],
            },
        ],
        "reasoning": "Research first, then write the answer.",
        "confidence": 0.9,
    })


DEFAULT_RESPONSES: Dict[str, str] = {
    # Supervisor planning prompt
    "Orchestra Supervisor": _default_plan(),
    # Reviewer prompt
    "quality reviewer evaluating": json.dumps({
        "scores": {"correctness": 0.9, "completeness": 0.9, "format": 0.9, "sources": 0.8},
        "feedback": "Output is accurate and complete.",
        "decision": "accept",
        "retry_instructions": "",
    }),
    # Memory extraction prompt
    "memory extraction agent": json.dumps({
        "approach": "Researched the topic, then wrote a summary.",
        "tools_used": ["web_search"],
        "outcome": "Success",
        "facts": ["Default fake fact for tests."],
        "preferences": [],
    }),
    # Memory retrieval prompt
    "past experiences for the user": json.dumps({
        "relevant_past_tasks": [],
        "suggested_approach": "No relevant past tasks found. Proceed with standard planning.",
        "known_constraints": [],
    }),
    # Specialist tool loop: answer directly, no tools needed.
    "Role:": json.dumps({
        "thought": "I can answer this directly.",
        "final_answer": "This is a fake response from the FakeProvider.",
    }),
}


class FakeProvider(LLMProvider):
    """A deterministic provider for testing that returns scripted outputs."""

    # Test hooks for the durability kill/resume test. Class-level so the counter
    # survives across provider instances inside one worker process.
    _calls = 0

    def __init__(self) -> None:
        self.scripted_responses: Dict[str, str] = {}
        self.default_responses: Dict[str, str] = dict(DEFAULT_RESPONSES)
        self.default_response = "This is a fake response from the FakeProvider."
        # Read by RecordingLLMProvider after complete_structured calls.
        self.last_usage: Optional[LLMResponse] = None

    async def _before_call(self, prompt: str) -> None:
        """Optional test hooks driven by env vars.

        - FAKE_COMPLETION_LOG: append the subtask line of every prompt, so a
          kill/resume test can assert completed steps are not repeated.
        - FAKE_KILL_AFTER_CALLS: SIGKILL this process on the Nth provider call,
          simulating a worker crash mid-run.
        - FAKE_DELAY_SECONDS: slow every call down for parallelism tests.
        """
        log_path = os.getenv("FAKE_COMPLETION_LOG")
        if log_path:
            first_task_line = next(
                (line for line in prompt.splitlines() if line.startswith("Task: ")),
                prompt.splitlines()[0] if prompt.splitlines() else "prompt",
            )
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(first_task_line[:120] + "\n")

        kill_after = os.getenv("FAKE_KILL_AFTER_CALLS")
        if kill_after:
            FakeProvider._calls += 1
            if FakeProvider._calls >= int(kill_after):
                os.kill(os.getpid(), signal.SIGKILL)

        delay = float(os.getenv("FAKE_DELAY_SECONDS", "0") or "0")
        if delay > 0:
            await asyncio.sleep(delay)

    def set_scripted_response(self, prompt_key: str, response: str) -> None:
        """Set a scripted response. The key can be a substring of the actual prompt."""
        self.scripted_responses[prompt_key] = response

    def _find_matching_response(self, prompt: str) -> str:
        """User-scripted responses win; built-in defaults keep demo runs working."""
        for key, response in self.scripted_responses.items():
            if key in prompt:
                return response
        for key, response in self.default_responses.items():
            if key in prompt:
                return response
        return self.default_response

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        await self._before_call(prompt)
        content = self._find_matching_response(prompt)
        response = LLMResponse(
            content=content,
            tokens_prompt=len(prompt) // 4,
            tokens_completion=len(content) // 4,
            cost=0.0,
            model="fake-model-v1",
        )
        self.last_usage = response
        return response

    async def complete_structured(self, prompt: str, response_model: Type[T], **kwargs: Any) -> T:
        await self._before_call(prompt)
        response_text = self._find_matching_response(prompt)
        self.last_usage = LLMResponse(
            content=response_text,
            tokens_prompt=len(prompt) // 4,
            tokens_completion=len(response_text) // 4,
            cost=0.0,
            model="fake-model-v1",
        )
        try:
            return response_model.model_validate_json(response_text)
        except Exception:
            # Fallback: Create a dummy instance using model_construct (bypasses validation)
            # This is acceptable for a FAKE provider used in testing
            return response_model.model_construct()

    def get_cost_per_token(self, model: str, token_type: str) -> float:
        return 0.0
