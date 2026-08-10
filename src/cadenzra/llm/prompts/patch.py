"""The prompt for `patch_voice`: fix the named bars, touch nothing else.

The surface is the same musician register as `generate_voice` — the notation
contract rides the system prompt there and here. What differs is scope: the
part is shown numbered, the rehearsal notes name bars, and the ask is those
bars alone.
"""

from cadenzra.llm.prompts.surface import chord_chart, range_text, section_text
from cadenzra.llm.prompts.voice import SYSTEM_PROMPT as _VOICE_SYSTEM
from cadenzra.model.contexts import PatchContext
from cadenzra.notation.scaffold import split_bars

PATCH_SYSTEM = _VOICE_SYSTEM.replace(
    "Write the music by calling the `write_part` tool.",
    "Answer by calling the `rewrite_bars` tool with the changed bars only.",
)


def build_patch_prompt(ctx: PatchContext) -> str:
    """The user-turn prompt for one bar-scoped repair."""
    numbered = "\n".join(
        f"  {number}: {bar.strip()}"
        for number, bar in enumerate(split_bars(ctx.part.lily_music), start=1)
    )
    bars_text = _bars_text(ctx.editable_bars)
    blocks = [
        section_text(ctx.section),
        f"Range for {ctx.voice.voice_id}: {range_text(ctx.voice)}. "
        "Every note must fall inside it.",
    ]
    if ctx.skeleton is not None and ctx.skeleton.events:
        blocks.append(
            "Harmony to write against:\n" + chord_chart(ctx.skeleton, ctx.section.meter)
        )
    blocks.append(
        f"Here is the {ctx.voice.voice_id} part as it stands, bar by bar:\n"
        f"{numbered}"
    )
    blocks.append(
        f"Rewrite only {bars_text}. Every other bar is fixed — some carry "
        "declared material that is checked note for note — and will be kept "
        "exactly as written, so do not restate them."
    )
    blocks.append(
        "Fix these problems:\n"
        + "\n".join(f"  - {item.message}" for item in ctx.feedback)
    )
    if ctx.siblings:
        lines = "\n".join(
            f"  {voice_id}:\n    " + music.replace("\n", "\n    ")
            for voice_id, music in ctx.siblings.items()
        )
        blocks.append(
            "The other voices, which yours has to fit against — these are "
            "fixed, so your rewritten bars are the notes that move:\n" + lines
        )
    return "\n\n".join(blocks)


def _bars_text(bars: tuple[int, ...]) -> str:
    if len(bars) == 1:
        return f"bar {bars[0]}"
    return "bars " + ", ".join(str(bar) for bar in bars)
