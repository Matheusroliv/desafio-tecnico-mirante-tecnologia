from langgraph.graph import END, START, StateGraph

from modernize.env import load_local_env
from modernize.generation.llm import OpenAIGenerator
from modernize.graph.state import PipelineState
from modernize.nodes.analyze import analyze_node
from modernize.nodes.generate import generate_node
from modernize.nodes.parse import parse_node
from modernize.nodes.persist import persist_node
from modernize.nodes.validate import validate_node
from modernize.persistence.history import PsycopgHistory


def build_graph(repo, llm):
    graph = StateGraph(PipelineState)
    graph.add_node("parse", parse_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("generate", lambda state: generate_node(state, llm))
    graph.add_node("validate", validate_node)
    graph.add_node("persist", lambda state: persist_node(state, repo))
    graph.add_edge(START, "parse")
    graph.add_conditional_edges(
        "parse",
        lambda state: "analyze" if state["report"]["parsing"]["ok"] else "persist",
        ["analyze", "persist"],
    )
    graph.add_conditional_edges(
        "analyze",
        lambda state: (
            "persist"
            if state.get("status") == "falha" or not state["report"]["semantic_analysis"]["ok"]
            else "generate"
        ),
        ["generate", "persist"],
    )
    graph.add_conditional_edges(
        "generate",
        lambda state: "validate" if state["report"]["generation"]["ok"] else "persist",
        ["validate", "persist"],
    )
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


load_local_env()
graph = build_graph(PsycopgHistory(), OpenAIGenerator())
