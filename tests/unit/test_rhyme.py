"""Does the stated scheme hold?

The module answers exactly that and nothing else — these tests pin both halves
of that boundary: schemes it must enforce, and judgments it must refuse to make.
"""

from cadenzra.verification.rhyme import (
    is_english,
    lines_rhyme,
    rhyme_keys,
    scheme_violations,
)


def test_plain_rhymes() -> None:
    assert lines_rhyme(["time"], ["climb"]) is True
    assert lines_rhyme(["night"], ["light"]) is True
    assert lines_rhyme(["love"], ["orange"]) is False


def test_multisyllable_rhymes() -> None:
    """A rhyme is measured from the last stressed vowel, so two syllables of
    agreement count as the rhyme they are."""
    assert lines_rhyme(["water"], ["daughter"]) is True
    assert lines_rhyme(["flying"], ["dying"]) is True


def test_mosaic_rhymes_where_one_side_is_several_words() -> None:
    """"poet" / "know it" is a rhyme a listener hears, and the check has to
    hear it too — otherwise a scheme the writer satisfied gets rejected."""
    assert lines_rhyme(["the", "poet"], ["you", "know", "it"]) is True
    assert lines_rhyme(["taller"], ["call", "her"]) is True


def test_an_unknown_word_is_not_evidence_of_anything() -> None:
    """An invented word, a proper noun or a loan word says nothing about
    whether a rhyme succeeded — so the answer is "cannot tell", not "no"."""
    assert lines_rhyme(["zzqx"], ["light"]) is None
    assert rhyme_keys(["zzqx"]) == set()
    assert rhyme_keys([]) == set()


def test_a_scheme_that_holds_reports_nothing() -> None:
    endings = [["night"], ["light"], ["sea"], ["tree"]]

    assert scheme_violations(endings, "AABB") == []


def test_a_broken_scheme_names_the_lines_and_the_words() -> None:
    """The message goes into a regeneration prompt, so it has to say which
    lines and which words (docs/04)."""
    endings = [["night"], ["orange"], ["sea"], ["tree"]]

    problems = scheme_violations(endings, "AABB")

    assert len(problems) == 1
    assert "lines 1 and 2" in problems[0]
    assert "night" in problems[0] and "orange" in problems[0]


def test_alternating_schemes_compare_the_right_pairs() -> None:
    abab_ok = [["night"], ["sea"], ["light"], ["tree"]]
    assert scheme_violations(abab_ok, "ABAB") == []

    # The same lines under AABB should fail: 1/2 and 3/4 do not rhyme.
    assert len(scheme_violations(abab_ok, "AABB")) == 2


def test_free_lines_are_never_checked() -> None:
    """`x` means the writer did not promise anything about that line."""
    endings = [["night"], ["orange"], ["light"]]

    assert scheme_violations(endings, "AxA") == []


def test_a_scheme_describes_a_stanza_and_repeats() -> None:
    """Reading a scheme as one fixed-length stanza forced a writer to answer a
    twenty-bar section with four lines of thirty syllables. AABB across eight
    lines is two quatrains, and the second one's A owes nothing to the first."""
    two_stanzas = [
        ["night"], ["light"], ["sea"], ["tree"],
        ["stone"], ["bone"], ["day"], ["way"],
    ]

    assert scheme_violations(two_stanzas, "AABB") == []

    broken = [*two_stanzas[:5], ["orange"], *two_stanzas[6:]]
    problems = scheme_violations(broken, "AABB")
    assert len(problems) == 1
    assert "lines 5 and 6" in problems[0]


def test_a_line_count_that_is_not_a_whole_number_of_stanzas_is_reported() -> None:
    problems = scheme_violations([["night"], ["light"]], "AABB")

    assert any("multiple of 4" in problem for problem in problems)


def test_a_letter_used_once_constrains_nothing() -> None:
    assert scheme_violations([["night"], ["sea"], ["moon"]], "ABC") == []


def test_the_deterministic_path_is_english_only() -> None:
    """CMUdict cannot speak for Latin; the fallback is stated, not hidden
    (docs/10)."""
    assert is_english("English")
    assert is_english("en-US")
    assert not is_english("Latin")
    assert not is_english("Korean")
