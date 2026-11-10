import chat


def test_retrieval_preserves_direction_commands_when_removing_delimiter_sizes():
    assert chat._normalize_query(r"x\rightarrow 0") == r"x\rightarrow 0"
    assert chat._normalize_query(r"x\leftarrow 0") == r"x\leftarrow 0"
    assert chat._normalize_query(r"\left(x+1\right)") == "(x+1)"
    assert chat._normalize_query(r"\left\{x\right\}") == r"\{x\}"
