"""What the installed game files say, for the games that ship a queryable ruleset.

Below the advisor layer and unaware of it: this package answers "what does the ruleset
say about X" and nothing about the game in progress. Civilization VII has no such source
and gets `NullRuleset`, which is why the advisor's Civ VII behaviour is the fallback
behaviour here rather than a special case.
"""
