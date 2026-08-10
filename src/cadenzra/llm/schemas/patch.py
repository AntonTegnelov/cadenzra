"""The `rewrite_bars` tool: replacement bars for a part under repair."""

from typing import Any, Final

REWRITE_BARS_TOOL: Final = "rewrite_bars"


def rewrite_bars_schema(editable_bars: list[int]) -> dict[str, Any]:
    """Replacements for the named bars only.

    The enum on `bar` is the permission model made mechanical: a bar the
    schema does not offer cannot be rewritten, however persuasive the
    feedback reads. The enum values are strings because Gemini's schema
    subset only permits `enum` on `type: string` — the parser turns them
    back into the ints the rest of the pipeline speaks.
    """
    return {
        "name": REWRITE_BARS_TOOL,
        "description": (
            "Rewrite only the bars you were asked to fix. Every bar you do "
            "not name stays exactly as written."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "replacements": {
                    "type": "array",
                    "description": "One entry per bar you are changing.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "bar": {
                                "type": "string",
                                "enum": [str(bar) for bar in editable_bars],
                                "description": "The bar number this replaces.",
                            },
                            "durations": {
                                "type": "string",
                                "description": (
                                    "Every duration in the new bar, in order, "
                                    "space-separated — e.g. '8 8 16 16 4.'. "
                                    "Plain values with dots, or a real length "
                                    "like 1/6 for a tuplet note. They must sum "
                                    "to exactly one full bar: count this out "
                                    "first, then write the notes to match."
                                ),
                            },
                            "lily_music": {
                                "type": "string",
                                "description": (
                                    "The complete new bar, using exactly the "
                                    "durations declared above, ending with its "
                                    "bar check |."
                                ),
                            },
                        },
                        "required": ["bar", "durations", "lily_music"],
                    },
                }
            },
            "required": ["replacements"],
        },
    }
