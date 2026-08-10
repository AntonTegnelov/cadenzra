"""Tool schemas for the lyric layers.

Lines of lyricmode-convention text, not a syllable tree: hyphenated
`\\lyricmode` is what the model has seen a million times, and a structured
representation of the same thing would be the lowest-density surface in the
system sitting exactly where quality is decided (docs/08, principle 2;
docs/10).
"""

from typing import Any, Final

from cadenzra.model.lyrics import DEVICE_VOCABULARY

PLAN_LYRICS_TOOL: Final = "plan_lyrics"
WRITE_LYRICS_TOOL: Final = "write_lyrics"
OBSERVE_DEVICES_TOOL: Final = "observe_devices"


def plan_lyrics_schema(
    section_ids: list[str], relationships: list[str]
) -> dict[str, Any]:
    """The lyric plan: one story, and a brief per sung section."""
    return {
        "name": PLAN_LYRICS_TOOL,
        "description": "Plan what the words of the piece say, section by section.",
        "parameters": {
            "type": "object",
            "properties": {
                "story": {
                    "type": "string",
                    "description": (
                        "Two or three sentences: what the piece is about, and how "
                        "it moves from beginning to end."
                    ),
                },
                "directives": {
                    "type": "array",
                    "description": "One per sung section, in performance order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section_id": {
                                "type": "string",
                                "description": "One of: " + ", ".join(section_ids),
                            },
                            "story_beat": {
                                "type": "string",
                                "description": (
                                    "What this section says — the part of the "
                                    "story it carries, concretely."
                                ),
                            },
                            "relationship": {
                                "type": "string",
                                "description": (
                                    "How the voices relate here. One of: "
                                    + ", ".join(relationships)
                                ),
                            },
                            "rhyme_scheme": {
                                "type": "string",
                                "description": (
                                    "One capital letter per line, x for a free "
                                    "line — e.g. AABB, ABAB, AAxA. Omit if this "
                                    "section does not rhyme."
                                ),
                            },
                            "devices": {
                                "type": "array",
                                "description": (
                                    "Craft this section should use. Only: "
                                    + ", ".join(sorted(DEVICE_VOCABULARY))
                                ),
                                "items": {"type": "string"},
                            },
                            "refrain_of": {
                                "type": "string",
                                "description": (
                                    "If this section repeats an earlier section's "
                                    "words unchanged, that section's id."
                                ),
                            },
                        },
                        "required": ["section_id", "story_beat", "relationship"],
                    },
                },
            },
            "required": ["story", "directives"],
        },
    }


def write_lyrics_schema(voice_ids: list[str]) -> dict[str, Any]:
    """One section's words, every singing voice at once."""
    return {
        "name": WRITE_LYRICS_TOOL,
        "description": "Write the words for every voice singing in this section.",
        "parameters": {
            "type": "object",
            "properties": {
                "voices": {
                    "type": "array",
                    "description": (
                        "One entry per singing voice. Every one of these voices "
                        "must appear: " + ", ".join(voice_ids)
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "voice_id": {
                                "type": "string",
                                "description": "One of: " + ", ".join(voice_ids),
                            },
                            "lines": {
                                "type": "array",
                                "description": (
                                    "The words, one line per entry. A line is one "
                                    "breath-phrase — roughly a bar or two of the "
                                    "music, so a long section has many lines. "
                                    "Syllables of "
                                    "a word split across notes are separated by "
                                    "-- , and a syllable held across notes is "
                                    "followed by __ for each extra note. "
                                    "For example: 'sha -- dow on the wa -- ter "
                                    "__ __'. No barlines, no \\lyricmode wrapper."
                                ),
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["voice_id", "lines"],
                    },
                }
            },
            "required": ["voices"],
        },
    }


def observe_devices_schema() -> dict[str, Any]:
    """What a blind reader found in the lyrics (docs/10)."""
    return {
        "name": OBSERVE_DEVICES_TOOL,
        "description": "Report the poetic devices actually present in a text.",
        "parameters": {
            "type": "object",
            "properties": {
                "observations": {
                    "type": "array",
                    "description": (
                        "One per device you can point at. Empty if you find none."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "device": {
                                "type": "string",
                                "description": "The device, by the name given to you.",
                            },
                            "lines": {
                                "type": "array",
                                "description": "Which lines it is in, numbered from 1.",
                                "items": {"type": "integer"},
                            },
                            "evidence": {
                                "type": "string",
                                "description": "The words that show it.",
                            },
                        },
                        "required": ["device", "evidence"],
                    },
                }
            },
            "required": ["observations"],
        },
    }
