"""Tool-call schemas for the structured layers.

Every field here is surface-shaped: bars, beats, chord symbols, meter strings
like "7/8 (2+2+3)", Italian dynamics. No internal type appears — in particular
no `Fraction`, which would put the internal register in front of the model and
defeat the seam these schemas sit on (docs/06).
"""

from typing import Any, Final

DERIVE_STYLE_TOOL: Final = "describe_style"
PLAN_STRUCTURE_TOOL: Final = "plan_structure"
WRITE_MOTIFS_TOOL: Final = "write_motifs"
WRITE_HARMONY_TOOL: Final = "write_harmony"
REVIEW_TOOL: Final = "give_verdict"


def describe_style_schema(meters: list[str]) -> dict[str, Any]:
    """Style as concrete, checkable material rather than a band name."""
    return {
        "name": DERIVE_STYLE_TOOL,
        "description": (
            "Turn a free-text style brief into concrete material every later "
            "step can use."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "idioms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Short directives a performer or composer would recognize: "
                        "modes, textures, habits of the style."
                    ),
                },
                "rhythmic_cells": {
                    "type": "array",
                    "description": (
                        "One-bar rhythm patterns, at least two for each meter listed: "
                        + ", ".join(meters)
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "meter": {
                                "type": "string",
                                "description": (
                                    "Exactly one of: " + ", ".join(meters)
                                ),
                            },
                            "lily": {
                                "type": "string",
                                "description": (
                                    "One bar of rhythm in LilyPond on the note c, with "
                                    "an explicit duration on every note and no bar "
                                    "check, e.g. 'c8 c c c c4.'"
                                ),
                            },
                            "description": {
                                "type": "string",
                                "description": "How it feels, e.g. 'driving 2+2+3'.",
                            },
                        },
                        "required": ["meter", "lily", "description"],
                    },
                },
                "harmony_guidance": {"type": "string"},
                "parallel_fifths_policy": {
                    "type": "string",
                    "enum": ["forbid", "allow", "encourage"],
                    "description": (
                        "Whether parallel fifths and octaves belong in this style."
                    ),
                },
                "dissonance_policy": {"type": "string"},
                "dynamics_arc": {"type": "string"},
                "few_shot_fragments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Two or three short LilyPond fragments in this style, absolute "
                        "pitch, explicit durations."
                    ),
                },
            },
            "required": [
                "idioms",
                "rhythmic_cells",
                "harmony_guidance",
                "parallel_fifths_policy",
                "dynamics_arc",
            ],
        },
    }


def plan_structure_schema(
    meters: list[str], voices: list[str], groups: list[str]
) -> dict[str, Any]:
    """The formal map: sections, and any material the form needs."""
    voice_ref = {
        "type": "string",
        "description": "A voice: " + ", ".join(voices)
        + (("; or a group: " + ", ".join(groups)) if groups else ""),
    }
    return {
        "name": PLAN_STRUCTURE_TOOL,
        "description": "Lay out the form of the piece, section by section.",
        "parameters": {
            "type": "object",
            "properties": {
                "form_summary": {
                    "type": "string",
                    "description": "One or two sentences on the shape of the piece.",
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section_id": {
                                "type": "string",
                                "description": "A short unique label, e.g. 'A', 'B1'.",
                            },
                            "bars": {"type": "integer"},
                            "meter": {
                                "type": "string",
                                "description": "Exactly one of: " + ", ".join(meters),
                            },
                            "key": {"type": "string", "description": "e.g. 'd phrygian'"},
                            "tempo_bpm": {"type": "integer"},
                            "texture": {
                                "type": "string",
                                "description": (
                                    "e.g. 'homophonic', 'imitative', 'unison', 'solo'"
                                ),
                            },
                            "dynamics_start": {
                                "type": "string",
                                "description": "Italian dynamic, e.g. 'pp'.",
                            },
                            "dynamics_targets": {
                                "type": "array",
                                "description": "Waypoints of the arc, in bar order.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "bar": {"type": "integer"},
                                        "level": {"type": "string"},
                                    },
                                    "required": ["bar", "level"],
                                },
                            },
                            "active_voices": {"type": "array", "items": voice_ref},
                            "intent": {
                                "type": "string",
                                "description": "One sentence on its musical purpose.",
                            },
                            "material": {
                                "type": "array",
                                "description": (
                                    "Where named material returns in this section. "
                                    "Only for forms that reuse material."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "motif_id": {"type": "string"},
                                        "voice_id": {"type": "string"},
                                        "bar": {
                                            "type": "integer",
                                            "description": "Bar within this section.",
                                        },
                                        "relation": {
                                            "type": "string",
                                            "description": (
                                                "How it relates to the original: "
                                                "'exact', 'inversion', 'tonal answer', "
                                                "'real answer', or an interval with a "
                                                "direction like 'P5 up', 'octave down'."
                                            ),
                                        },
                                    },
                                    "required": ["motif_id", "voice_id", "bar", "relation"],
                                },
                            },
                        },
                        "required": [
                            "section_id",
                            "bars",
                            "meter",
                            "key",
                            "tempo_bpm",
                            "texture",
                            "dynamics_start",
                            "active_voices",
                            "intent",
                        ],
                    },
                },
                "materials_needed": {
                    "type": "array",
                    "description": (
                        "Recurring material this form requires. Leave empty unless the "
                        "form genuinely reuses a theme."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "motif_id": {"type": "string"},
                            "role": {
                                "type": "string",
                                "description": "e.g. 'fugue subject', 'riff', 'theme'",
                            },
                            "description": {"type": "string"},
                            "carrying_voices": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["motif_id", "role", "description"],
                    },
                },
            },
            "required": ["form_summary", "sections"],
        },
    }


def write_motifs_schema() -> dict[str, Any]:
    return {
        "name": WRITE_MOTIFS_TOOL,
        "description": "Write the recurring material the piece is built from.",
        "parameters": {
            "type": "object",
            "properties": {
                "motifs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "motif_id": {"type": "string"},
                            "role": {"type": "string"},
                            "lily_music": {
                                "type": "string",
                                "description": (
                                    "The material itself: absolute pitch, an explicit "
                                    "duration on every note, a bar check | at the end "
                                    "of every bar, no structural commands."
                                ),
                            },
                            "description": {"type": "string"},
                        },
                        "required": ["motif_id", "role", "lily_music"],
                    },
                }
            },
            "required": ["motifs"],
        },
    }


def write_harmony_schema(bars: int) -> dict[str, Any]:
    return {
        "name": WRITE_HARMONY_TOOL,
        "description": "Write the chord progression for one section.",
        "parameters": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "description": (
                        f"The chords in order, with no gaps and no overlaps, covering "
                        f"all {bars} bars exactly."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "bar": {
                                "type": "integer",
                                "description": f"1 to {bars}, within this section.",
                            },
                            "beat": {
                                "type": "number",
                                "description": (
                                    "Where in the bar the chord starts; 1 is the "
                                    "downbeat. Decimals allowed, e.g. 2.5."
                                ),
                            },
                            "duration_beats": {
                                "type": "number",
                                "description": "How many beats it lasts.",
                            },
                            "chord": {
                                "type": "string",
                                "description": (
                                    "A chord symbol: Dm, Esus4, F#m7, Bb/D, D5."
                                ),
                            },
                        },
                        "required": ["bar", "beat", "duration_beats", "chord"],
                    },
                }
            },
            "required": ["events"],
        },
    }


def review_schema() -> dict[str, Any]:
    """The verdict shape every LLM validator answers in."""
    return {
        "name": REVIEW_TOOL,
        "description": "Answer the question with a verdict and reasons.",
        "parameters": {
            "type": "object",
            "properties": {
                "acceptable": {"type": "boolean"},
                "reasons": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concrete, specific; name bars and voices.",
                },
                "suggestions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["acceptable", "reasons"],
        },
    }
