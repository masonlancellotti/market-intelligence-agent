"""Calibration Lab endpoints — systematic rule backtests (RETROSPECTIVE)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/calibration/rules")
def calibration_rules() -> dict:
    """Per-rule + pooled reliability curves and skill scores over historical rule backtests."""
    from ..conviction.rulebook import rule_backtest_summary

    return rule_backtest_summary()
