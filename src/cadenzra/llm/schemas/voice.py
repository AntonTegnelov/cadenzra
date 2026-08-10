"""The tool-call schema for `generate_voice`.

Fragments arrive via a tool call so extraction is uniform, but their *real*
validation is the compile-and-analyze path: JSON well-formedness says nothing
about musical well-formedness. Structured outputs guarantee shape; the compiler
guarantees substance (docs/06).

Schemas are surface-shaped — bars, note names, plain LilyPond. No internal type
appears here, and in particular no `Fraction` ever reaches a schema.
"""

from typing import Any, Final

WRITE_PART_TOOL: Final = "write_part"


def write_part_schema(*, techniques: bool) -> dict[str, Any]:
    """The schema for one voice part.

    `techniques` gates its field out of the schema entirely when the piece has
    no use for it — the surface shows only what is needed (docs/04).

    There is no lyrics field: words are written afterwards, by the lyric layer,
    against the finished music and for every singer in the section at once
    (docs/10).
    """
    properties: dict[str, Any] = {
        # Declared before the notes so the arithmetic is planned first — the
        # parser sums each bar's declaration exactly, and a bar that does not
        # add up is rejected before anything compiles.
        "bar_durations": {
            "type": "string",
            "description": (
                "Every duration in the part, bar by bar, in order, with bars "
                "separated by | — e.g. '8 8 16 16 4. | 4 4 4.'. Plain values "
                "with dots, or a real length like 1/6 for a tuplet note. Each "
                "bar must sum to exactly one full bar of the meter: count "
                "this out first, then write the notes to match."
            ),
        },
        "lily_music": {
            "type": "string",
            "description": (
                "The music expression in LilyPond: absolute pitch, an explicit "
                "duration on every note — exactly the durations declared in "
                "bar_durations — a bar check | at the end of every bar, and no "
                "structural commands."
            ),
        },
    }
    required = ["bar_durations", "lily_music"]

    if techniques:
        properties["techniques"] = {
            "type": "array",
            "description": (
                "Extended techniques used, matching the markings in the notation."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "technique": {"type": "string"},
                    "from_bar": {"type": "integer"},
                    "to_bar": {
                        "type": "integer",
                        "description": "Omit for a technique at a single point.",
                    },
                },
                "required": ["technique", "from_bar"],
            },
        }

    return {
        "name": WRITE_PART_TOOL,
        "description": "Submit the notation for one voice's part in one section.",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
