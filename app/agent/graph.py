"""LangGraph state-graph definition for the review pipeline."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    aggregate_and_rank,
    build_context,
    format_output,
    scalability_review,
    security_review,
)
from app.agent.schemas import ReviewState


def build_review_graph():
    """Assemble the review workflow nodes into a compiled ``CompiledGraph``.

    Flow: build_context -> {security_review, scalability_review} (parallel)
    -> aggregate_and_rank -> format_output.
    """
    graph = StateGraph(ReviewState)

    graph.add_node("build_context", build_context)
    graph.add_node("security_review", security_review)
    graph.add_node("scalability_review", scalability_review)
    graph.add_node("aggregate_and_rank", aggregate_and_rank)
    graph.add_node("format_output", format_output)

    graph.add_edge(START, "build_context")
    graph.add_edge("build_context", "security_review")
    graph.add_edge("build_context", "scalability_review")
    graph.add_edge("security_review", "aggregate_and_rank")
    graph.add_edge("scalability_review", "aggregate_and_rank")
    graph.add_edge("aggregate_and_rank", "format_output")
    graph.add_edge("format_output", END)

    return graph.compile()
