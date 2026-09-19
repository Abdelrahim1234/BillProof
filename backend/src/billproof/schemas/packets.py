from pydantic import BaseModel, Field

from billproof.enums import Language, PacketGoal


class PacketRequest(BaseModel):
    goal: PacketGoal
    language: Language = Language.EN
    additional_context: str | None = Field(default=None, max_length=1000)


class PacketResponse(BaseModel):
    packet_id: str
    case_id: str
    goal: str
    language: str
    packet: dict
    markdown: str
