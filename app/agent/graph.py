"""LangGraph state-graph definition for the review pipeline."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    aggregate_and_rank,
    build_context,
    correctness_review,
    format_output,
    scalability_review,
    security_review,
    style_review,
)
from app.agent.schemas import ReviewState

LENS_NODES = (security_review, scalability_review, style_review, correctness_review)


def build_review_graph():
    """Assemble the review workflow nodes into a compiled ``CompiledGraph``.

    Flow: build_context -> {security_review, scalability_review, style_review,
    correctness_review} (parallel) -> aggregate_and_rank -> format_output.
    """
    graph = StateGraph(ReviewState)

    graph.add_node("build_context", build_context)
    graph.add_node("aggregate_and_rank", aggregate_and_rank)
    graph.add_node("format_output", format_output)

    graph.add_edge(START, "build_context")
    for lens in LENS_NODES:
        graph.add_node(lens.__name__, lens)
        graph.add_edge("build_context", lens.__name__)
        graph.add_edge(lens.__name__, "aggregate_and_rank")

    graph.add_edge("aggregate_and_rank", "format_output")
    graph.add_edge("format_output", END)

    return graph.compile()
