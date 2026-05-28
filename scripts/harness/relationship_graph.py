"""Build a read-only relationship graph from harness task artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from artifact_io import atomic_write_json, atomic_write_text

from decision_registry import load_decision_registry
from phase_contract import (
    contract_acceptance_commands,
    contract_allowed_paths,
    contract_required_outputs,
    contract_required_repo_outputs,
    parse_phase_contract,
)


RUNTIME_PROOF_SUFFIXES = [
    "contract.json",
    "checklist.md",
    "evidence.json",
    "gate.json",
    "reconciliation.json",
    "result.json",
]


@dataclass
class GraphBuilder:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    _edge_keys: set[tuple[str, str, str]] = field(default_factory=set)

    def add_node(self, node_id: str, node_type: str, label: str, **metadata: Any) -> None:
        existing = self.nodes.get(node_id)
        payload = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "metadata": {key: value for key, value in metadata.items() if value not in (None, [], {})},
        }
        if existing:
            existing["metadata"].update(payload["metadata"])
            return
        self.nodes[node_id] = payload

    def add_edge(self, source: str, target: str, relation: str, **metadata: Any) -> None:
        key = (source, target, relation)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "metadata": {key: value for key, value in metadata.items() if value not in (None, [], {})},
            }
        )

    def payload(self) -> dict[str, Any]:
        return {
            "nodes": sorted(self.nodes.values(), key=lambda node: node["id"]),
            "edges": sorted(self.edges, key=lambda edge: (edge["source"], edge["target"], edge["relation"])),
        }


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def relationship_graph_output_paths(task_path: Path) -> dict[str, Path]:
    runtime_dir = task_path / "context-pack" / "runtime"
    return {
        "json": runtime_dir / "relationship-graph.json",
        "mermaid": runtime_dir / "relationship-graph.mmd",
        "warning": runtime_dir / "relationship-graph-warning.json",
    }


def output_rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def write_relationship_graph_outputs(root: Path, task_path: Path) -> dict[str, Any]:
    paths = relationship_graph_output_paths(task_path)
    try:
        paths["json"].parent.mkdir(parents=True, exist_ok=True)
        graph = graph_from_task(root, task_path)
        atomic_write_json(paths["json"], graph)
        atomic_write_text(paths["mermaid"], to_mermaid(graph))
        paths["warning"].unlink(missing_ok=True)
        return {
            "status": "generated",
            "json": output_rel(root, paths["json"]),
            "mermaid": output_rel(root, paths["mermaid"]),
            "warning": None,
        }
    except Exception as exc:  # noqa: BLE001 - graph export is non-blocking by design.
        for output_path in (paths["json"], paths["mermaid"]):
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        warning = {
            "status": "warning",
            "reason": "Relationship graph generation failed. This does not change task status.",
            "error": str(exc),
        }
        warning_path: str | None = None
        try:
            paths["warning"].parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths["warning"], warning)
            warning_path = output_rel(root, paths["warning"])
        except OSError as warning_exc:
            warning["warning_error"] = str(warning_exc)
        return {
            "status": "warning",
            "json": None,
            "mermaid": None,
            "warning": warning_path,
            "error": str(exc),
            "warning_error": warning.get("warning_error"),
        }


def task_rel(task_path: Path, path: Path) -> str:
    try:
        return path.relative_to(task_path).as_posix()
    except ValueError:
        return path.as_posix()


def graph_from_task(root: Path, task_path: Path) -> dict[str, Any]:
    task_index = read_json(task_path / "index.json")
    builder = GraphBuilder()

    task_name = str(task_index.get("task") or task_path.name)
    task_id = f"task:{task_path.name}"
    builder.add_node(task_id, "task", task_name, path=output_rel(root, task_path))

    for raw_path in task_index.get("common_docs") or []:
        add_document(builder, task_id, "reads_common_doc", raw_path)
    for raw_path in task_index.get("docs") or []:
        add_document(builder, task_id, "reads_task_doc", raw_path)

    add_static_context(builder, root, task_path, task_id)
    add_decision_registry(builder, task_path, task_id)
    add_phases(builder, root, task_path, task_index, task_id)
    return builder.payload()


def add_document(builder: GraphBuilder, owner_id: str, relation: str, raw_path: str) -> None:
    node_id = f"doc:{raw_path}"
    builder.add_node(node_id, "document", Path(raw_path).name, path=raw_path)
    builder.add_edge(owner_id, node_id, relation)


def add_static_context(builder: GraphBuilder, root: Path, task_path: Path, task_id: str) -> None:
    static_dir = task_path / "context-pack" / "static"
    if not static_dir.exists():
        return
    for path in sorted(static_dir.iterdir()):
        if not path.is_file():
            continue
        raw_path = output_rel(root, path)
        node_id = f"static:{task_rel(task_path, path)}"
        builder.add_node(node_id, "static_context", path.name, path=raw_path)
        builder.add_edge(task_id, node_id, "has_static_context")

    approval = read_json(static_dir / "design-approval.json")
    approved_doc = approval.get("approved_doc")
    if isinstance(approved_doc, str) and approved_doc:
        approval_id = "static:context-pack/static/design-approval.json"
        doc_id = f"doc:{approved_doc}"
        builder.add_node(doc_id, "document", Path(approved_doc).name, path=approved_doc)
        builder.add_edge(approval_id, doc_id, "approves_doc", sha256=approval.get("approved_doc_sha256"))


def add_decision_registry(builder: GraphBuilder, task_path: Path, task_id: str) -> None:
    registry, errors = load_decision_registry(task_path)
    if errors:
        for index, error in enumerate(errors):
            node_id = f"registry-error:{index}"
            builder.add_node(node_id, "registry_error", error)
            builder.add_edge(task_id, node_id, "has_registry_error")
        return

    for item in registry_items(registry.get("decisions"), "decisions"):
        decision_id = str(item.get("id"))
        node_id = f"decision:{decision_id}"
        builder.add_node(
            node_id,
            "decision",
            decision_id,
            status=item.get("status"),
            summary=item.get("summary"),
            rationale=item.get("rationale"),
        )
        builder.add_edge(task_id, node_id, "has_decision")

    for item in registry_items(registry.get("open_decisions"), "decisions"):
        decision_id = str(item.get("id"))
        node_id = f"open-decision:{decision_id}"
        builder.add_node(
            node_id,
            "open_decision",
            decision_id,
            status=item.get("status"),
            blocking_stage=item.get("blocking_stage"),
            question=item.get("question"),
        )
        relation = "blocked_by" if item.get("status", "open") == "open" else "has_open_decision"
        builder.add_edge(task_id, node_id, relation)

    architecture = registry.get("architecture")
    for item in registry_items(architecture, "nodes"):
        node_id = f"architecture:{item.get('id')}"
        builder.add_node(
            node_id,
            "architecture_node",
            str(item.get("name") or item.get("id")),
            responsibility=item.get("responsibility"),
        )
        builder.add_edge(task_id, node_id, "has_architecture_node")

    for item in registry_items(architecture, "decisions"):
        arch_id = str(item.get("id"))
        node_id = f"architecture-ref:{arch_id}"
        builder.add_node(node_id, "architecture_ref", arch_id, summary=item.get("summary"))
        builder.add_edge(task_id, node_id, "has_architecture_ref")

    for index, item in enumerate(registry_items(architecture, "allowed_edges")):
        source = str(item.get("from") or "")
        target = str(item.get("to") or "")
        edge_id = str(item.get("id") or f"allowed-edge-{index}")
        source_id = f"architecture:{source}"
        target_id = f"architecture:{target}"
        if source and target:
            builder.add_node(source_id, "architecture_node", source)
            builder.add_node(target_id, "architecture_node", target)
            builder.add_edge(source_id, target_id, "allows_dependency", ref=edge_id, reason=item.get("reason"))
        edge_ref_id = f"architecture-ref:{edge_id}"
        builder.add_node(edge_ref_id, "architecture_ref", edge_id, reason=item.get("reason"))
        builder.add_edge(task_id, edge_ref_id, "has_architecture_ref")


def registry_items(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    raw_items = value.get(field)
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def add_phases(builder: GraphBuilder, root: Path, task_path: Path, task_index: dict[str, Any], task_id: str) -> None:
    for phase in task_index.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        phase_number = phase.get("phase")
        if not isinstance(phase_number, int):
            continue
        phase_id = f"phase:{phase_number}"
        builder.add_node(
            phase_id,
            "phase",
            f"phase{phase_number}: {phase.get('name') or ''}".strip(),
            status=phase.get("status"),
            name=phase.get("name"),
        )
        builder.add_edge(task_id, phase_id, "has_phase")
        add_phase_file(builder, root, task_path, phase_number, phase_id)
        add_runtime_proof(builder, root, task_path, phase_number, phase_id)


def add_phase_file(builder: GraphBuilder, root: Path, task_path: Path, phase_number: int, phase_id: str) -> None:
    path = task_path / "phases" / f"phase{phase_number}.md"
    if not path.exists():
        path = task_path / f"phase{phase_number}.md"
    if not path.exists():
        builder.add_node(f"missing-phase-file:{phase_number}", "missing_file", f"phase{phase_number}.md")
        builder.add_edge(phase_id, f"missing-phase-file:{phase_number}", "missing_phase_file")
        return

    raw_path = output_rel(root, path)
    phase_file_id = f"phase-file:{phase_number}"
    builder.add_node(phase_file_id, "phase_file", path.name, path=raw_path)
    builder.add_edge(phase_id, phase_file_id, "defined_by")

    contract, errors = parse_phase_contract(path.read_text(encoding="utf-8"))
    for index, error in enumerate(errors):
        error_id = f"phase-contract-error:{phase_number}:{index}"
        builder.add_node(error_id, "contract_error", error)
        builder.add_edge(phase_id, error_id, "has_contract_error")
    if contract is None:
        return

    add_contract_refs(builder, phase_id, contract)


def add_contract_refs(builder: GraphBuilder, phase_id: str, contract: dict[str, Any]) -> None:
    for ref in contract.get("decision_refs") or []:
        if isinstance(ref, str):
            node_id = f"decision:{ref}"
            builder.add_node(node_id, "decision", ref)
            builder.add_edge(phase_id, node_id, "requires_decision")

    for ref in contract.get("architecture_refs") or []:
        if isinstance(ref, str):
            node_id = f"architecture-ref:{ref}"
            builder.add_node(node_id, "architecture_ref", ref)
            builder.add_edge(phase_id, node_id, "requires_architecture")

    for raw_path in contract_allowed_paths(contract):
        node_id = f"path:{raw_path}"
        builder.add_node(node_id, "allowed_path", raw_path, path=raw_path)
        builder.add_edge(phase_id, node_id, "may_edit")

    for raw_path in contract_required_outputs(contract):
        node_id = f"output:{raw_path}"
        builder.add_node(node_id, "required_output", raw_path, path=raw_path)
        builder.add_edge(phase_id, node_id, "requires_output")

    for raw_path in contract_required_repo_outputs(contract):
        node_id = f"repo-output:{raw_path}"
        builder.add_node(node_id, "required_repo_output", raw_path, path=raw_path)
        builder.add_edge(phase_id, node_id, "requires_repo_output")

    for index, command in enumerate(contract_acceptance_commands(contract)):
        command_id = f"command:{phase_id}:{index}"
        builder.add_node(command_id, "acceptance_command", command)
        builder.add_edge(phase_id, command_id, "verified_by")


def add_runtime_proof(builder: GraphBuilder, root: Path, task_path: Path, phase_number: int, phase_id: str) -> None:
    runtime_dir = task_path / "context-pack" / "runtime"
    for suffix in RUNTIME_PROOF_SUFFIXES:
        path = runtime_dir / f"phase{phase_number}-{suffix}"
        if not path.exists():
            continue
        raw_path = output_rel(root, path)
        proof_id = f"runtime:{task_rel(task_path, path)}"
        builder.add_node(proof_id, "runtime_proof", path.name, path=raw_path)
        builder.add_edge(phase_id, proof_id, "has_runtime_proof")

    handoff = task_path / "context-pack" / "handoffs" / f"phase{phase_number}.md"
    if handoff.exists():
        raw_path = output_rel(root, handoff)
        handoff_id = f"handoff:phase{phase_number}"
        builder.add_node(handoff_id, "handoff", handoff.name, path=raw_path)
        builder.add_edge(phase_id, handoff_id, "writes_handoff")


def to_mermaid(graph: dict[str, Any]) -> str:
    lines = ["flowchart LR"]
    ids = {node["id"]: f"n{index}" for index, node in enumerate(graph.get("nodes", []))}
    for node in graph.get("nodes", []):
        lines.append(f'  {ids[node["id"]]}["{escape_mermaid(str(node["label"]))}"]')
    for edge in graph.get("edges", []):
        source = ids.get(edge["source"])
        target = ids.get(edge["target"])
        if source and target:
            lines.append(f'  {source} -->|"{escape_mermaid(edge["relation"])}"| {target}')
    return "\n".join(lines) + "\n"


def escape_mermaid(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
