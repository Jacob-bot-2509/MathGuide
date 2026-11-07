"""Kuttler 导入器:证明题、是非题、不可抽取答案的题。"""
from __future__ import annotations

from exercises.importers import kuttler

PAGE = r"""
<section class="box-exercise">
  <div>
    <h2 class="box-legend"><span>Exercise \(\PageIndex{1}\)</span></h2>
    <p>Let \(X\) be a vector space. Show that the zero vector is unique and explain why.</p>
    <dl><dt>Answer</dt><dd><p>Suppose \(0\) and \(0'\) are both zero vectors. Then
    \(0 = 0 + 0' = 0'\) by the additive identity axiom, so they are equal. This proves
    uniqueness of the zero vector in any vector space.</p></dd></dl>
  </div>
</section>
<section class="box-exercise">
  <div>
    <h2 class="box-legend"><span>Exercise \(\PageIndex{2}\)</span></h2>
    <p>Let \(M\) be the set of vectors of length at most \(4\). Is \(M\) a subspace of
    \(\mathbb{R}^4\)?</p>
    <dl><dt>Answer</dt><dd><p>No. The vector \((1,1,1,1)\) is in \(M\) but \(20\) times
    that vector is not, so \(M\) is not closed under scalar multiplication.</p></dd></dl>
  </div>
</section>
<section class="box-exercise">
  <div>
    <h2 class="box-legend"><span>Exercise \(\PageIndex{3}\)</span></h2>
    <p>Compute the determinant of the matrix \(\begin{pmatrix}1&amp;2\\3&amp;4\end{pmatrix}\).</p>
    <dl><dt>Answer</dt><dd><p>Answer: \(-2\).</p></dd></dl>
  </div>
</section>
<section class="box-exercise">
  <div>
    <h2 class="box-legend"><span>Exercise \(\PageIndex{4}\)</span></h2>
    <p>This exercise has no answer block and must be skipped by the importer.</p>
  </div>
</section>
"""


def test_parse_page_imports_proof_and_yes_no():
    items, skipped = kuttler.parse_page(PAGE, "https://example.com/9e", "vector-space", "vs9")

    assert [item.id for item in items] == ["kuttler:vs9:1", "kuttler:vs9:2"]
    proof, yes_no = items
    assert proof.type == "proof"
    assert proof.content["en"].answer == "Proof"
    assert proof.cross_topics == ("vector-space",)
    assert yes_no.type == "apply"
    assert yes_no.content["en"].answer == "No"
    assert skipped["answer_not_extractable"] == 1
    assert skipped["missing_block"] == 1


def test_parse_page_adds_rule_cross_topic():
    items, _ = kuttler.parse_page(PAGE, "https://example.com/2e", "", "m2")

    assert items[0].cross_topics == ("vector-space",)
