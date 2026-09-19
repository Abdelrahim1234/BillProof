from pydantic import BaseModel


class ToolResult[T](BaseModel):
    """Every MCP tool returns this: typed data plus the safe, user-visible
    summary that also becomes the activity_receipts row for protected tools
    (docs/04: 'every tool response includes ... a safe user-visible activity
    summary')."""

    data: T
    activity_summary: str
