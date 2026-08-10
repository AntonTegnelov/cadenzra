"""The `rewrite_bars` tool: replacement bars for a part under repair."""

from typing import Any, Final

REWRITE_BARS_TOOL: Final = "rewrite_bars"


def rewrite_bars_schema(editable_bars: list[int]) -> dict[str, Any]:
    """Replacements for the named bars only.

    The enum on `bar` is the permission model made mechanical: a bar the
    schema does not offer cannot be rewritten, however persuasive the
    feedback reads.
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
                                "type": "integer",
                                "enum": editable_bars,
                                "description": "The bar number this replaces.",
                            },
                            "lily_music": {
                                "type": "string",
                                "description": (
                                    "The complete new bar, ending with its "
                                    "bar check |."
                                ),
                            },
                        },
                        "required": ["bar", "lily_music"],
                    },
                }
            },
            "required": ["replacements"],
        },
    }
