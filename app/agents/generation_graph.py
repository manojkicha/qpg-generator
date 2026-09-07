"""LangGraph generation pipeline — orchestrator that chains agent nodes.

Based on SDD Section 5.2.2:
- Agentic generation pipeline modeled as explicit graph of agent nodes
- Flow: Plan → Retrieve → Generate → Validate → Compile
- Each step's output validated before moving to next

Supports Ollama, OpenAI, and Azure OpenAI via LLM_PROVIDER config.
"""

import logging
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.agents.nodes.compiler_node import CompilerNode
from app.agents.nodes.generator_node import GeneratorNode
from app.agents.nodes.planner_node import PlannerNode
from app.agents.nodes.validator_node import ValidatorNode
from app.core.llm_client import get_chat_model

logger = logging.getLogger(__name__)


class GenerationState(TypedDict, total=False):
    """State passed between agent nodes in the LangGraph."""

    job_id: str
    tenant_id: str
    specification: dict
    context_chunks: list

    # Intermediate
    generation_plan: dict
    task_assignment: dict
    generated_question: dict
    questions: list
    validation_passed: bool
    validation_flags: list
    retry_indices: list

    # Final outputs
    question_paper: dict
    answer_key: dict
    validation_summary: dict
    agent_trace: list


def _get_llm():
    """Get the configured LLM via the unified client."""
    return get_chat_model()


async def create_generation_graph() -> "GenerationPipeline":
    """Create the LangGraph generation pipeline."""
    llm = _get_llm()

    planner = PlannerNode(llm)
    generator = GeneratorNode(llm)
    validator = ValidatorNode(llm)
    compiler = CompilerNode(llm)

    graph = StateGraph(GenerationState)

    # Add nodes
    graph.add_node("planner", planner.execute)
    graph.add_node("generator", generator.execute)
    graph.add_node("validator", validator.execute)
    graph.add_node("compiler", compiler.execute)

    # Define edges
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "generator")
    graph.add_edge("generator", "validator")

    # Conditional: if validation fails and retries available, go back to generator
    def should_retry(state: GenerationState) -> str:
        retry_indices = state.get("retry_indices", [])
        if not retry_indices:
            return "compiler"
        return END  # Simplification: stop here, retries handled elsewhere

    graph.add_conditional_edges("validator", should_retry, {
        "compiler": "compiler",
        END: END,
    })

    graph.add_edge("compiler", END)

    compiled = graph.compile()
    return GenerationPipeline(compiled)


class GenerationPipeline:
    """Wrapper around the compiled LangGraph."""

    def __init__(self, compiled_graph: Any) -> None:
        self._graph = compiled_graph

    async def ainvoke(self, input_state: dict) -> dict:
        """Run the pipeline with the given input state."""
        logger.info("Invoking generation pipeline for job: %s", input_state.get("job_id"))
        result = await self._graph.ainvoke(input_state)
        return result

    def invoke(self, input_state: dict) -> dict:
        """Synchronous invoke (for testing)."""
        return self._graph.invoke(input_state)