import os
from functools import partial

from langgraph.graph import END, START, StateGraph

from modernize.env import load_local_env
from modernize.evaluation.equivalence import legacy_dsn
from modernize.generation.llm import Generator, OpenAIGenerator
from modernize.graph.state import PipelineState
from modernize.nodes.analyze import analyze_node
from modernize.nodes.generate import generate_node
from modernize.nodes.parse import parse_node
from modernize.nodes.persist import persist_node
from modernize.nodes.validate import validate_node
from modernize.persistence.history import HistoryRepository, PsycopgHistory

DEFAULT_MAX_REPAIRS = 1


def max_repair_attempts() -> int:
    raw = os.environ.get("MAX_REPAIR_ATTEMPTS", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_MAX_REPAIRS
    except ValueError:
        return DEFAULT_MAX_REPAIRS


def route_after_parse(state: PipelineState) -> str:
    return "analyze" if state["report"]["parsing"]["ok"] else "persist"


def route_after_analyze(state: PipelineState) -> str:
    if state.get("status") == "falha" or not state["report"]["semantic_analysis"]["ok"]:
        return "persist"
    return "generate"


def route_after_generate(state: PipelineState) -> str:
    return "validate" if state["report"]["generation"]["ok"] else "persist"


def route_after_validate(state: PipelineState, max_repairs: int) -> str:
    """Fluxo de decisao: volta ao LLM com os achados enquanto houver tentativa."""
    if state.get("status") == "sucesso":
        return "persist"
    if state.get("attempts", 0) > max_repairs:
        return "persist"
    return "generate"


def build_graph(
    repo: HistoryRepository,
    llm: Generator,
    max_repairs: int | None = None,
    behavioral_dsn: str | None = None,
):
    """``behavioral_dsn`` liga a validacao dinamica (database legacy) no no validate."""
    repairs = max_repair_attempts() if max_repairs is None else max_repairs
    graph = StateGraph(PipelineState)
    graph.add_node("parse", parse_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("generate", partial(generate_node, llm=llm))
    graph.add_node("validate", partial(validate_node, behavioral_dsn=behavioral_dsn))
    graph.add_node("persist", partial(persist_node, repo=repo))
    graph.add_edge(START, "parse")
    graph.add_conditional_edges("parse", route_after_parse, ["analyze", "persist"])
    graph.add_conditional_edges("analyze", route_after_analyze, ["generate", "persist"])
    graph.add_conditional_edges("generate", route_after_generate, ["validate", "persist"])
    graph.add_conditional_edges("validate", partial(route_after_validate, max_repairs=repairs), ["generate", "persist"])
    graph.add_edge("persist", END)
    return graph.compile()


load_local_env()
graph = build_graph(PsycopgHistory(), OpenAIGenerator(), behavioral_dsn=legacy_dsn())
