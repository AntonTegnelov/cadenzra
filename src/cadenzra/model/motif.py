"""`MotifLibrary` — thematic material as first-class state.

Motifs exist so that "themes that return" is a checkable claim rather than an
aspiration. At the LLM surface they always travel as verbatim notation with a
musician's instruction; the id is bookkeeping for validators, the notes are for
the composer (docs/03).
"""

from pydantic import BaseModel, Field

from cadenzra.model.primitives.ids import MotifId


class Motif(BaseModel, frozen=True):
    motif_id: MotifId
    role: str
    lily_music: str
    description: str = ""


class MotifLibrary(BaseModel, frozen=True):
    motifs: dict[MotifId, Motif] = Field(default_factory=dict)

    def __getitem__(self, motif_id: MotifId) -> Motif:
        return self.motifs[motif_id]

    def __contains__(self, motif_id: MotifId) -> bool:
        return motif_id in self.motifs
