"""Signal engine: indicators, breadth, regime model, alert DSL.

Computed nightly on daily bars (an intraday subset during RTH). Every value is
traceable to a stored bar; property + fixture tests guard correctness.
"""

__all__ = ["recompute_all"]


def recompute_all(*args, **kwargs):
    """Lazy proxy to engine.recompute_all (keeps import graph light)."""
    from .engine import recompute_all as _impl

    return _impl(*args, **kwargs)
