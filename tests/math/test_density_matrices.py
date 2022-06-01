# Copyright 2022 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Unit tests for density matrices functions.
"""

import numpy as onp
import pytest

from pennylane import numpy as np
from pennylane import math as fn

pytestmark = pytest.mark.all_interfaces

tf = pytest.importorskip("tensorflow", minversion="2.1")
torch = pytest.importorskip("torch")
jax = pytest.importorskip("jax")
jnp = pytest.importorskip("jax.numpy")

state_00 = [1, 0, 0, 0]
state_01 = [0, 1, 0, 0]
state_10 = [0, 0, 1, 0]
state_11 = [0, 0, 0, 1]

state_00_10 = [1, 0, 1, 0] / onp.sqrt(2)
state_01_11 = [0, 1, 0, 1] / onp.sqrt(2)

mat_00 = onp.zeros((4, 4))
mat_00[0, 0] = 1

mat_01 = onp.zeros((4, 4))
mat_01[1, 1] = 1

mat_10 = onp.zeros((4, 4))
mat_10[2, 2] = 1

mat_11 = onp.zeros((4, 4))
mat_11[3, 3] = 1

mat_0 = onp.zeros((2, 2))
mat_0[0, 0] = 1

mat_1 = onp.zeros((2, 2))
mat_1[1, 1] = 1

mat_00_10 = onp.zeros((4, 4))
mat_00_10[0, 0] = 0.5
mat_00_10[2, 2] = 0.5
mat_00_10[0, 2] = 0.5
mat_00_10[2, 0] = 0.5

mat_01_11 = onp.zeros((4, 4))
mat_01_11[1, 1] = 0.5
mat_01_11[3, 3] = 0.5
mat_01_11[1, 3] = 0.5
mat_01_11[3, 1] = 0.5

mat_0_1 = [[0.5, 0.5], [0.5, 0.5]]

# fmt: off
state_vectors = [
    (state_00, (mat_0, mat_0, mat_00)),
    (state_01, (mat_0, mat_1, mat_01)),
    (state_10, (mat_1, mat_0, mat_10)),
    (state_11, (mat_1, mat_1, mat_11)),
    (state_00_10, (mat_0_1, mat_0, mat_00_10)),
    (state_01_11, (mat_0_1, mat_1, mat_01_11))]

array_funcs = [lambda x: x, onp.array, np.array, jnp.array, torch.tensor, tf.Variable, tf.constant]

single_wires_list = [
    [0],
    [1],
]

multiple_wires_list = [
    [0, 1]
]
# fmt: on


class TestDensityMatrixFromStateVectors:
    """Tests for creating a density matrix from state vectors."""

    @pytest.mark.parametrize("array_func", array_funcs)
    @pytest.mark.parametrize("state_vector, expected_density_matrix", state_vectors)
    @pytest.mark.parametrize("wires", single_wires_list)
    def test_density_matrix_from_state_vector_single_wires(
        self, state_vector, wires, expected_density_matrix, array_func
    ):
        """Test the density matrix from state vectors for single wires."""
        state_vector = array_func(state_vector)
        density_matrix = fn.quantum._density_matrix_from_state_vector(state_vector, indices=wires)
        assert np.allclose(density_matrix, expected_density_matrix[wires[0]])

    @pytest.mark.parametrize("array_func", array_funcs)
    @pytest.mark.parametrize("state_vector, expected_density_matrix", state_vectors)
    @pytest.mark.parametrize("wires", multiple_wires_list)
    def test_density_matrix_from_state_vector_full_wires(
        self, state_vector, wires, expected_density_matrix, array_func
    ):
        """Test the density matrix from state vectors for full wires."""
        state_vector = array_func(state_vector)
        density_matrix = fn.quantum._density_matrix_from_state_vector(state_vector, indices=wires)
        assert np.allclose(density_matrix, expected_density_matrix[2])

    @pytest.mark.parametrize("array_func", array_funcs)
    @pytest.mark.parametrize("state_vector, expected_density_matrix", state_vectors)
    @pytest.mark.parametrize("wires", single_wires_list)
    def test_to_density_matrix_with_state_vector_single_wires(
        self, state_vector, wires, expected_density_matrix, array_func
    ):
        """Test the to_density_matrix with state vectors for single wires."""
        state_vector = array_func(state_vector)
        density_matrix = fn.to_density_matrix(state_vector, indices=wires)
        assert np.allclose(density_matrix, expected_density_matrix[wires[0]])

    @pytest.mark.parametrize("array_func", array_funcs)
    @pytest.mark.parametrize("state_vector, expected_density_matrix", state_vectors)
    @pytest.mark.parametrize("wires", multiple_wires_list)
    def test_to_density_matrix_with_state_vector_full_wires(
        self, state_vector, wires, expected_density_matrix, array_func
    ):
        """Test the to_density_matrix with state vectors for full wires."""
        state_vector = array_func(state_vector)
        density_matrix = fn.to_density_matrix(state_vector, indices=wires)
        assert np.allclose(density_matrix, expected_density_matrix[2])

    @pytest.mark.parametrize("array_func", array_funcs)
    @pytest.mark.parametrize("state_vector, expected_density_matrix", state_vectors)
    @pytest.mark.parametrize("wires", multiple_wires_list)
    def test_density_matrix_from_state_vector_check_state(
        self, state_vector, wires, expected_density_matrix, array_func
    ):
        """Test the density matrix from state vectors for single wires with state checking"""
        state_vector = array_func(state_vector)
        density_matrix = fn.quantum._density_matrix_from_state_vector(
            state_vector, indices=wires, check_state=True
        )
        assert np.allclose(density_matrix, expected_density_matrix[2])

    def test_state_vector_wrong_shape(self):
        """Test that wrong shaped state vector raises an error with check_state=True"""
        state_vector = [1, 0, 0]

        with pytest.raises(ValueError, match="State vector must be"):
            fn.quantum._density_matrix_from_state_vector(
                state_vector, indices=[0], check_state=True
            )

    def test_state_vector_wrong_norm(self):
        """Test that state vector with wrong norm raises an error with check_state=True"""
        state_vector = [0.1, 0, 0, 0]

        with pytest.raises(ValueError, match="Sum of amplitudes-squared does not equal one."):
            fn.quantum._density_matrix_from_state_vector(
                state_vector, indices=[0], check_state=True
            )

    def test_density_matrix_from_state_vector_jax_jit(self):
        """Test jitting the density matrix from state vector function."""
        from jax import jit
        import jax.numpy as jnp

        state_vector = jnp.array([1, 0, 0, 0])

        jitted_dens_matrix_func = jit(
            fn.quantum._density_matrix_from_state_vector, static_argnums=[1, 2]
        )

        density_matrix = jitted_dens_matrix_func(state_vector, indices=(0, 1), check_state=True)
        assert np.allclose(density_matrix, [[1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])

    def test_wrong_shape_jax_jit(self):
        """Test jitting the density matrix from state vector with wrong shape."""
        from jax import jit
        import jax.numpy as jnp

        state_vector = jnp.array([1, 0, 0])

        jitted_dens_matrix_func = jit(
            fn.quantum._density_matrix_from_state_vector, static_argnums=[1, 2]
        )

        with pytest.raises(ValueError, match="State vector must be"):
            jitted_dens_matrix_func(state_vector, indices=(0, 1), check_state=True)

    def test_density_matrix_tf_jit(self):
        """Test jitting the density matrix from state vector function with Tf."""
        import tensorflow as tf
        from functools import partial

        state_vector = tf.Variable([1, 0, 0, 0], dtype=tf.complex128)
        density_matrix = partial(fn.to_density_matrix, indices=[0])

        density_matrix = tf.function(
            density_matrix,
            jit_compile=True,
            input_signature=(tf.TensorSpec(shape=(4,), dtype=tf.complex128),),
        )
        density_matrix = density_matrix(state_vector)
        assert np.allclose(density_matrix, [[1, 0], [0, 0]])
