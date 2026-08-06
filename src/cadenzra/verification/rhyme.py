"""Does the stated rhyme scheme hold?

That is the only question this module answers. Not "is this a good rhyme", not
"should these have rhymed" — a scheme the plan declared is a contract, and a
contract is decidable. Taste is not (docs/01, docs/10).

Phonetics come from CMUdict via `pronouncing` rather than a hand-rolled
syllabifier, following docs/05's "prefer existing tools over new parsers". That
makes the check English-only; other languages fall back to LLM review, which is
weaker, and is stated rather than hidden.
"""

from typing import Final

import pronouncing

# Unstressed vowels reduce in ordinary speech, and dictionaries disagree about
# which reduced vowel they are — CMUdict spells the second syllable of "poet"
# AH0 and of "know it" IH0. Collapsing them is what lets "poet" rhyme with
# "know it", which is a rhyme any listener hears.
_SCHWA: Final = "AX"

# How many trailing words a rhyme may span. Two covers ordinary mosaic rhymes
# ("know it", "caught her"); three covers the showy ones. Beyond that the
# "rhyme" is a whole line, which is a holorime — a device, reviewed by ear.
_MAX_RHYME_WORDS: Final = 3

_ENGLISH: Final = frozenset({"english", "en", "en-us", "en-gb", "american english"})


def is_english(language: str) -> bool:
    """Whether the deterministic path applies to this language."""
    return language.strip().lower() in _ENGLISH


def rhyme_keys(words: list[str]) -> set[str]:
    """Every way the end of this line could be heard as a rhyme.

    A set rather than one key, for two reasons: a word may have several
    pronunciations, and a rhyme may span more than one word. Two lines rhyme if
    any of their keys agree — which is what makes multi-word and multi-syllable
    rhymes pass rather than fail.

    Empty means "we cannot tell": an unknown word, or no words at all. Callers
    treat that as no evidence, never as a failure.
    """
    if not words:
        return set()

    keys: set[str] = set()
    for span in range(1, min(_MAX_RHYME_WORDS, len(words)) + 1):
        tail = words[-span:]
        for phones in _phone_variants(tail):
            key = _rhyming_part(phones)
            if key:
                keys.add(key)
    return keys


def lines_rhyme(first: list[str], second: list[str]) -> bool | None:
    """Whether two line endings rhyme. None when the dictionary cannot say."""
    left, right = rhyme_keys(first), rhyme_keys(second)
    if not left or not right:
        return None
    return bool(left & right)


def scheme_violations(
    endings: list[list[str]], scheme: str
) -> list[str]:
    """Where the lines fail the scheme they were written to.

    Messages are rehearsal notes, naming the lines and the words that do not
    agree, because their real consumer is a regeneration prompt (docs/04).
    """
    letters = [letter for letter in scheme if letter != "x"]
    del letters  # only the positional scheme matters below

    problems: list[str] = []
    if len(endings) != len(scheme):
        problems.append(
            f"the rhyme scheme {scheme} asks for {len(scheme)} lines, "
            f"and there are {len(endings)}"
        )

    groups: dict[str, list[int]] = {}
    for index, letter in enumerate(scheme[: len(endings)]):
        if letter == "x":
            continue
        groups.setdefault(letter, []).append(index)

    for letter, indexes in groups.items():
        if len(indexes) < 2:
            continue
        anchor = indexes[0]
        for other in indexes[1:]:
            verdict = lines_rhyme(endings[anchor], endings[other])
            if verdict is False:
                problems.append(
                    f"lines {anchor + 1} and {other + 1} are both marked {letter} "
                    f"in the scheme {scheme}, but "
                    f'"{_ending_text(endings[anchor])}" and '
                    f'"{_ending_text(endings[other])}" do not rhyme'
                )
    return problems


def _ending_text(words: list[str]) -> str:
    return " ".join(words[-2:]) if len(words) > 1 else (words[-1] if words else "")


def _phone_variants(words: list[str]) -> list[str]:
    """Every pronunciation of this word sequence, as one phone string each.

    Returns nothing if any word is unknown: a made-up word, a proper noun or a
    loan word is not evidence that a rhyme failed.
    """
    variants: list[list[str]] = [[]]
    for index, word in enumerate(words):
        pronunciations = pronouncing.phones_for_word(word)
        if not pronunciations:
            return []
        variants = [
            [*prefix, _elide(phones, initial=index > 0)]
            for prefix in variants
            for phones in pronunciations
        ]
    return [" ".join(parts) for parts in variants]


def _elide(phones: str, *, initial: bool) -> str:
    """Drop a word-initial /h/ inside a multi-word ending.

    "call her" is sung "call'er", which is the whole mechanism a mosaic rhyme
    runs on — /h/ is the one consonant that reliably disappears in connected
    speech. Without this, "taller / call her" reads as a failed rhyme and the
    writer is sent to fix something they got right.
    """
    if initial and phones.startswith("HH "):
        return phones[3:]
    return phones


def _rhyming_part(phones: str) -> str:
    """The phones from the last stressed vowel onward, stress-normalized."""
    tokens = phones.split()
    last_stressed = None
    for index, token in enumerate(tokens):
        if token[-1] in "12":
            last_stressed = index
    if last_stressed is None:
        return ""
    return " ".join(_normalize(token) for token in tokens[last_stressed:])


def _normalize(phone: str) -> str:
    """Drop stress marks, and collapse unstressed vowels to one schwa."""
    if phone[-1].isdigit():
        stress, base = phone[-1], phone[:-1]
        return _SCHWA if stress == "0" else base
    return phone
