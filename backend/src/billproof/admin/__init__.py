"""Server-only inventory and cleanup helpers.

These modules are intentionally not imported by API routes. They expose safe
metadata operations for explicit admin commands and never return document
bodies in their reports.
"""
