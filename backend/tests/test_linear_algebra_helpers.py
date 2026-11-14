"""linear_algebra:输入校验辅助函数(脏输入必须返回 None,不能让异常冒到接口层)。

这些函数是线性代数端点与图解生成的第一道闸。缺的 18 行全是"形状不对 / 不是数字 /
超范围"的分支 —— 写错的后果是用户填错一格就 500,而不是拿到一句可读的 400。
"""
from __future__ import annotations

import linear_algebra as la


def test_num_rejects_non_numeric_and_out_of_range():
    assert la._num("1.5") == 1.5
    assert la._num("abc") is None
    assert la._num(None) is None
    assert la._num(float("inf")) is None
    assert la._num(10 ** 5) is None            # 超过 1e4 上限
    assert la._num("nan") is None


def test_vec_requires_exact_shape_and_numbers():
    assert la._vec([1, 2], 2) == [1.0, 2.0]
    assert la._vec([1], 2) is None             # 长度不符
    assert la._vec("12", 2) is None            # 不是序列
    assert la._vec([1, "x"], 2) is None        # 有非数字


def test_vectors_checks_container_items_and_count():
    assert la._vectors([[1, 2], [3, 4]], 2) == [[1.0, 2.0], [3.0, 4.0]]
    assert la._vectors([[1, 2]], 2, count=2) is None   # 数量不符
    assert la._vectors("nope", 2) is None
    assert la._vectors([[1, 2], [3]], 2) is None       # 其中一行形状不对


def test_matrix_requires_square_shape():
    assert la._matrix([[1, 2], [3, 4]], 2) == [[1.0, 2.0], [3.0, 4.0]]
    assert la._matrix([[1, 2]], 2) is None
    assert la._matrix([[1, 2], [3]], 2) is None


def test_complex_requires_pair_of_finite_numbers():
    assert la._complex([1, -2]) == complex(1, -2)
    assert la._complex([1]) is None
    assert la._complex([1, "x"]) is None


def test_cvec_and_cmatrix_validate_each_element():
    assert la._cvec([[1, 0], [0, 1]], 2) == [complex(1, 0), complex(0, 1)]
    assert la._cvec([[1, 0]], 2) is None
    assert la._cvec([[1, 0], "bad"], 2) is None
    assert la._cmatrix([[[1, 0], [0, 1]], [[1, 0], [0, 1]]], 2) is not None
    assert la._cmatrix([[[1, 0], [0, 1]], "bad"], 2) is None


def test_cabs_and_cmatvec():
    assert la._cabs(complex(3, 4)) == 5.0
    assert la._cmatvec([[1 + 0j, 0j], [0j, 1 + 0j]], [2 + 0j, 3 + 0j]) == [
        (2 + 0j), (3 + 0j)]


def test_symplectic_check_rejects_wrong_shape_and_non_symplectic():
    # J 本身是辛矩阵;单位矩阵也是(辛群包含 I)
    assert la._is_symplectic(la._j_matrix(1), 1) is True
    assert la._is_symplectic([[1.0, 0.0], [0.0, 1.0]], 1) is True
    # 维度不符
    assert la._is_symplectic([[1.0, 0.0]], 1) is False
    # 形状对但不满足 MᵀJM = J(缩放破坏了辛结构)
    assert la._is_symplectic([[2.0, 0.0], [0.0, 1.0]], 1) is False


def test_unitary_check():
    identity = [[1 + 0j, 0j], [0j, 1 + 0j]]
    assert la._is_unitary(identity) is True
    assert la._is_unitary([[1 + 0j, 1 + 0j], [0j, 1 + 0j]]) is False


def test_project_complex_variants():
    vector = [complex(1, 2), complex(3, 4)]
    assert la._project_complex(vector, "r4_to_3d") == [1.0, 2.0, 3.0]
    assert la._project_complex(vector, "r4_to_2d") == [1.0, 2.0]
    assert la._project_complex(vector, "r4") == [1.0, 2.0, 3.0, 4.0]
