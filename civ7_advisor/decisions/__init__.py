"""Structured decisions: evidence, action candidates and the cards the UI renders.

Advisors produce ranked `Insight`s. This package turns those into decisions that can be
acted on: each one names a target, a next step, the observations it rests on and the
reviewed guide that explains how to do it in game. Nothing here invents a number, a
prerequisite or a URL — every claim resolves to an `EvidenceFact` or a `GuideEntry`.
"""
