import math
import random
from typing import Any

def pick_ucb1(nodes: list[dict], params: dict, metric: str, outcomes: dict, rng: random.Random) -> list[dict]:
    # Import from frontier_strategies inside the function to avoid circular imports.
    from evo.frontier_strategies import _score_of, _node_summary
    from evo.core import repo_root, load_graph

    c = float(params.get("c", 1.0))
    k = int(params.get("k", 5))

    try:
        root = repo_root()
        graph = load_graph(root)
    except Exception:
        graph = {"nodes": {}}

    graph_nodes = graph.get("nodes", {})
    N = max(1, len(graph_nodes) - 1)

    scored_nodes = []
    for node in nodes:
        node_id = node["id"]
        score = _score_of(node, metric)

        # Get number of children from graph
        graph_node = graph_nodes.get(node_id, {})
        children = graph_node.get("children", [])
        n_i = len(children)

        # Calculate UCB1 score
        if score == float("-inf"):
            ucb = float("-inf")
        else:
            # UCB1 = score + c * sqrt(ln(N) / (n_i + 1))
            ucb = score + c * math.sqrt(math.log(N) / (n_i + 1))

        scored_nodes.append((ucb, node))

    # Sort descending by UCB1 score, break ties randomly using rng.random()
    scored_nodes.sort(key=lambda x: (-x[0], rng.random()))

    # Return top K
    selected = [item[1] for item in scored_nodes[:k]]
    return [_node_summary(n, i + 1) for i, n in enumerate(selected)]
