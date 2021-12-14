# Copyright 2021 Xanadu Quantum Technologies Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from functools import partial
from itertools import product
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union, List

from networkx import MultiDiGraph, weakly_connected_components

from pennylane.operation import AnyWires, Operation, Operator, Tensor, Expectation
from pennylane.tape import QuantumTape, stop_recording
from pennylane.transforms import batch_transform
from pennylane.measure import MeasurementProcess
from pennylane.wires import Wires
from pennylane import apply, PauliX, PauliY, PauliZ, Identity, Hadamard, S, expval
from pennylane import math
import numpy as np


class PlaceholderNode(Operation):
    num_wires = AnyWires
    grad_method = None

    def __init__(self, *params, wires: Wires, do_queue: Optional[bool] = True, id: Optional[str] = None):
        self._terms = params[0] if len(params) > 0 else None
        super().__init__(*params, wires=wires, do_queue=do_queue, id=id)

    @property
    def terms(self) -> List[Callable]:
        return self._terms


class MeasureNode(PlaceholderNode):
    ...


class PrepareNode(PlaceholderNode):
    ...


class WireCut(Operation):
    num_wires = AnyWires
    grad_method = None

    def __init__(self, *params, wires: Wires, do_queue: Optional[bool] = True, id: Optional[str] = None):
        self._custom_expansion = params[0] if len(params) > 0 else None
        super().__init__(*params, wires=wires, do_queue=do_queue, id=id)

    def expand(self) -> QuantumTape:
        with QuantumTape() as tape:
            ...
        return tape

    def expand_cut(self) -> QuantumTape:
        if self._custom_expansion is not None:
            return self._custom_expansion(self)

        with QuantumTape() as tape:
            for wire in self.wires:
                SimpleMeasureNode(wires=wire)
                SimplePrepareNode(wires=wire)

        return tape


@batch_transform
def cut_circuit(
    tape: QuantumTape, method: Optional[Union[str, Callable]] = None, **kwargs
) -> Tuple[Tuple[QuantumTape], Callable]:
    """Main transform"""
    g = tape_to_graph(tape)
    remove_wire_cut_nodes(g)

    if method is not None:
        find_and_place_cuts(g, method=method, **kwargs)

    fragments, communication_graph = fragment_graph(g)
    fragment_tapes = [graph_to_tape(f) for f in fragments]

    expanded = [expand_fragment_tapes(t) for t in fragment_tapes]

    configurations = []
    prepare_nodes = []
    measure_nodes = []

    for tapes, p, m in expanded:
        configurations.append(tapes)
        prepare_nodes.append(p)
        measure_nodes.append(m)

    shapes = [len(c) for c in configurations]

    tapes = tuple(tape for c in configurations for tape in c)

    return tapes, partial(
        contract,
        shapes=shapes,
        communication_graph=communication_graph,
        prepare_nodes=prepare_nodes,
        measure_nodes=measure_nodes,
    )


def tape_to_graph(tape: QuantumTape) -> MultiDiGraph:
    """Converts a quantum tape to a directed multigraph."""
    graph = MultiDiGraph()

    wire_latest_node = {w: None for w in tape.wires}

    for order, op in enumerate(tape.operations):
        graph.add_node(op, order=order)
        for wire in op.wires:
            if wire_latest_node[wire] is not None:
                parent_op = wire_latest_node[wire]
                graph.add_edge(parent_op, op, wire=wire)
            wire_latest_node[wire] = op

    order += 1

    for m in tape.measurements:
        obs = getattr(m, "obs", None)
        if obs is not None and isinstance(obs, Tensor):
            for o in obs.obs:
                m_ = MeasurementProcess(m.return_type, obs=o)

                graph.add_node(m_, order=order)
                order += 1
                for wire in o.wires:
                    parent_op = wire_latest_node[wire]
                    graph.add_edge(parent_op, m_, wire=wire)
        else:
            graph.add_node(m, order=order)
            order += 1

            for wire in m.wires:
                parent_op = wire_latest_node[wire]
                graph.add_edge(parent_op, m, wire=wire)

    return graph


def remove_wire_cut_node(node: WireCut, graph: MultiDiGraph):
    """Removes a WireCut node from the graph"""
    predecessors = graph.pred[node]
    successors = graph.succ[node]

    expanded_node = node.expand_cut()
    ops_on_wire = expanded_node.graph._grid

    predecessor_on_wire = {}
    for op, data in predecessors.items():
        for d in data.values():
            wire = d["wire"]
            predecessor_on_wire[wire] = op

    successor_on_wire = {}
    for op, data in successors.items():
        for d in data.values():
            wire = d["wire"]
            successor_on_wire[wire] = op

    order = graph.nodes[node]["order"]
    graph.remove_node(node)

    added_nodes = set()

    for wire in node.wires:
        predecessor = predecessor_on_wire.get(wire, None)
        successor = successor_on_wire.get(wire, None)

        meas, prep = ops_on_wire[expanded_node.wires.index(wire)]

        if meas not in added_nodes:
            graph.add_node(meas, order=order)
            added_nodes |= {meas}

        if prep not in added_nodes:
            graph.add_node(prep, order=order + 0.5)
            added_nodes |= {prep}

        graph.add_edge(meas, prep, wire=wire)

        if predecessor is not None:
            graph.add_edge(predecessor, meas, wire=wire)
        if successor is not None:
            graph.add_edge(prep, successor, wire=wire)


def remove_wire_cut_nodes(graph: MultiDiGraph):
    """Remove all WireCuts from the graph"""
    for op in list(graph.nodes):
        if isinstance(op, WireCut):
            remove_wire_cut_node(op, graph)


def find_and_place_cuts(graph: MultiDiGraph, method: Union[str, Callable], **kwargs):
    """Automatically find additional cuts and place them in the graph. A ``method`` can be
    explicitly passed as a callable, or built-in ones can be used by specifying the corresponding
    string."""
    ...  # calls ``method`` (see ``example_method``) and ``place_cuts``


def example_method(
    graph: MultiDiGraph,
    max_wires: Optional[int],
    max_gates: Optional[int],
    num_partitions: Optional[int],
    **kwargs
) -> Tuple[Tuple[Tuple[Operator, Operator, Any]], Dict[str, Any]]:
    """Example method passed to ``find_cuts``. Returns a tuple of wire cuts of the form
    ``Tuple[Tuple[Operator, Operator, Any]]`` specifying the wire to cut between two operators. An
    additional results dictionary is also returned that can contain optional optimization results.
    """
    ...


def place_cuts(graph: MultiDiGraph, wires: Tuple[Tuple[Operator, Operator, Any]]):
    """Places wire cuts in ``graph`` according to ``wires`` which contains pairs of operators along
    with the wire passing between them to be cut."""
    ...


def fragment_graph(graph: MultiDiGraph) -> Tuple[Tuple[MultiDiGraph], MultiDiGraph]:
    """Fragments a cut graph into a collection of subgraphs as well as returning the
    communication/quotient graph."""
    edges = list(graph.edges)
    cut_edges = []

    for node1, node2, _ in edges:
        if isinstance(node1, MeasureNode):
            assert isinstance(node2, PrepareNode)
            cut_edges.append((node1, node2))
            graph.remove_edge(node1, node2)

    subgraph_nodes = weakly_connected_components(graph)
    subgraphs = tuple(graph.subgraph(n) for n in subgraph_nodes)

    communication_graph = MultiDiGraph()
    communication_graph.add_nodes_from(range(len(subgraphs)))

    for node1, node2 in cut_edges:
        for i, subgraph in enumerate(subgraphs):
            if subgraph.has_node(node1):
                start_fragment = i
            if subgraph.has_node(node2):
                end_fragment = i

        communication_graph.add_edge(start_fragment, end_fragment, pair=(node1, node2))

    return subgraphs, communication_graph


def graph_to_tape(graph: MultiDiGraph) -> QuantumTape:
    """Converts a circuit graph to the corresponding quantum tape."""
    wires = Wires.all_wires([n.wires for n in graph.nodes])

    ordered_ops = sorted([(order, op) for op, order in graph.nodes(data="order")], key=lambda x: x[0])
    wire_map = {w: w for w in wires}

    with QuantumTape() as tape:
        for _, op in ordered_ops:
            new_wires = [wire_map[w] for w in op.wires]
            op._wires = Wires(new_wires)  # TODO: find a better way to update operation wires
            apply(op)

            if isinstance(op, MeasureNode):
                measured_wire = op.wires[0]
                new_wire = _find_new_wire(wires)
                wires += new_wire
                wire_map[measured_wire] = new_wire

    return tape


def _find_new_wire(wires: Wires) -> int:
    """Finds a new wire label that is not in ``wires``."""
    ctr = 0
    while ctr in wires:
        ctr += 1
    return ctr


def _prep_zero_state(wire):
    Identity(wire)


def _prep_one_state(wire):
    PauliX(wire)


def _prep_plus_state(wire):
    Hadamard(wire)


def _prep_iplus_state(wire):
    Hadamard(wire)
    S(wires=wire)


PREPARE_SETTINGS = [_prep_zero_state, _prep_one_state, _prep_plus_state, _prep_iplus_state]
MEASURE_SETTINGS = [Identity, PauliX, PauliY, PauliZ]


class SimpleMeasureNode(MeasureNode):

    def __init__(self, *params, wires: Wires, do_queue: Optional[bool] = True, id: Optional[str] = None):
        assert len(Wires(wires)) == 1
        assert len(params) == 0
        super().__init__(*params, wires=wires, do_queue=do_queue, id=id)

    @property
    def terms(self) -> List[Callable]:
        return MEASURE_SETTINGS


class SimplePrepareNode(PrepareNode):

    def __init__(self, *params, wires: Wires, do_queue: Optional[bool] = True,
                 id: Optional[str] = None):
        assert len(Wires(wires)) == 1
        assert len(params) == 0
        super().__init__(*params, wires=wires, do_queue=do_queue, id=id)

    @property
    def terms(self) -> List[Callable]:
        return PREPARE_SETTINGS


def expand_fragment_tapes(
    tape: QuantumTape,
) -> Tuple[List[QuantumTape], List[PrepareNode], List[MeasureNode]]:
    """Expands a fragment tape into a tape for each configuration."""

    prepare_nodes = [o for o in tape.operations if isinstance(o, PrepareNode)]
    measure_nodes = [o for o in tape.operations if isinstance(o, MeasureNode)]

    prepare_nodes_terms = [p.terms for p in prepare_nodes]
    measure_nodes_terms = [m.terms for m in measure_nodes]

    prepare_combinations = product(*prepare_nodes_terms)
    measure_combinations = product(*measure_nodes_terms)

    tapes = []

    for prepare_settings, measure_settings in product(prepare_combinations, measure_combinations):
        prepare_mapping = {n: s for n, s in zip(prepare_nodes, prepare_settings)}
        measure_mapping = {n: s for n, s in zip(measure_nodes, measure_settings)}

        meas = []

        with QuantumTape() as tape_:
            for op in tape.operations:
                if isinstance(op, PrepareNode):
                    w = op.wires
                    prepare_mapping[op](w)
                elif isinstance(op, MeasureNode):
                    meas.append(op)
                else:
                    apply(op)

            with stop_recording():
                op_tensor = Tensor(*[measure_mapping[op](op.wires) for op in meas])

            if len(tape.measurements) > 0:
                for m in tape.measurements:
                    if m.return_type is not Expectation:
                        raise ValueError("Only expectation values supported for now")
                    with stop_recording():
                        m_obs = m.obs
                        if isinstance(m_obs, Tensor):
                            terms = m_obs.obs
                            for t in terms:
                                if not isinstance(t, (Identity, PauliX, PauliY, PauliY)):
                                    raise ValueError("Only tensor products of Paulis for now")
                            op_tensor_wires = [(t.wires.tolist()[0], t) for t in op_tensor.obs]
                            m_obs_wires = [(t.wires.tolist()[0], t) for t in terms]
                            all_wires = sorted(op_tensor_wires + m_obs_wires)
                            all_terms = [t[1] for t in all_wires]
                            full_tensor = Tensor(*all_terms)
                        else:
                            if not isinstance(m_obs, (Identity, PauliX, PauliY, PauliZ)):
                                raise ValueError("Only tensor products of Paulis for now")

                            op_tensor_wires = [(t.wires.tolist()[0], t) for t in op_tensor.obs]
                            m_obs_wires = [(m_obs.wires.tolist()[0], m_obs)]
                            all_wires = sorted(op_tensor_wires + m_obs_wires)
                            all_terms = [t[1] for t in all_wires]
                            full_tensor = Tensor(*all_terms)

                    expval(full_tensor)
            elif len(op_tensor.name) > 0:
                expval(op_tensor)
            else:
                expval(Identity(tape.wires[0]))

        tapes.append(tape_)

    return tapes, prepare_nodes, measure_nodes


CHANGE_OF_BASIS_MAT = np.array([[1, 1, 0, 0], [-1, -1, 2, 0], [-1, -1, 0, 2], [1, -1, 0, 0]])


def _get_tensors(
    results: Sequence,
    shapes: Sequence[int],
    prepare_nodes: Sequence[PrepareNode],
    measure_nodes: Sequence[MeasureNode],
) -> List:

    ctr = 0
    tensors = []

    for s, p, m in zip(shapes, prepare_nodes, measure_nodes):
        n_prep = len(p)
        n_meas = len(m)
        target_shape = (4,) * (n_prep + n_meas)

        fragment_results = math.stack(results[ctr : s + ctr]).reshape(target_shape)

        fragment_results *= np.power(2, -(n_meas + n_prep) / 2)
        ctr += s

        for i in range(n_prep):
            fragment_results = math.tensordot(CHANGE_OF_BASIS_MAT, fragment_results, axes=[1, i])

        tensors.append(fragment_results)

    return tensors


def _contract_tensors(
    tensors: Sequence,
    communication_graph: MultiDiGraph,
    prepare_nodes: Sequence[PrepareNode],
    measure_nodes: Sequence[MeasureNode],
):
    import opt_einsum as oe

    ctr = 0
    tensor_indxs = [""] * len(communication_graph.nodes)

    meas_map = {}

    for i, (node, prep) in enumerate(zip(communication_graph.nodes, prepare_nodes)):
        predecessors = communication_graph.pred[node]

        for pred_node, pred_edges in predecessors.items():
            for pred_edge in pred_edges.values():
                meas_op, prep_op = pred_edge["pair"]
                for p in prep:
                    if p is prep_op:
                        symb = oe.get_symbol(ctr)
                        ctr += 1
                        tensor_indxs[i] += symb
                        meas_map[meas_op] = symb

    for i, (node, meas) in enumerate(zip(communication_graph.nodes, measure_nodes)):
        successors = communication_graph.succ[node]

        for succ_node, succ_edges in successors.items():
            for succ_edge in succ_edges.values():
                meas_op, prep_op = succ_edge["pair"]

                for m in meas:
                    if m is meas_op:
                        symb = meas_map[meas_op]
                        tensor_indxs[i] += symb

    eqn = ",".join(tensor_indxs)

    return oe.contract(eqn, *tensors)


def contract(
    results: Sequence,
    shapes: Sequence[int],
    communication_graph: MultiDiGraph,
    prepare_nodes: Sequence[PrepareNode],
    measure_nodes: Sequence[MeasureNode],
):
    """Returns the result of contracting the tensor network."""
    if len(results[0]) > 1:
        raise ValueError("Only supporting returning a single expectation for now")

    tensors = _get_tensors(results, shapes, prepare_nodes, measure_nodes)
    result = _contract_tensors(tensors, communication_graph, prepare_nodes, measure_nodes)

    return result
