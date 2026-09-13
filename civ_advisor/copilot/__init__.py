"""A conversation grounded in the same evidence as the briefing.

The model chooses NAMED questions from a fixed catalog and writes prose around the
facts they return. It never writes SQL or Lua, and every number in its prose must
appear in a fact it cited (grounding.py) or the prose is not shown.
"""
