"""Reference host integration contract, not a monkey-patch for a closed harness.

The host owns native snapshots, durable compare-and-swap commitment, reliable
request budgets, lifecycle events and resumable task scheduling. This module
never fabricates a summary and never infers consent to run native compaction.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from .core import PruneError


class Choice(str, Enum):
    PRUNE = "prune"
    COMPACT = "compact"
    PAUSE = "pause"


class Outcome(str, Enum):
    READY = "ready"
    APPLIED = "manual_prune_applied_without_resuming"
    WAITING = "waiting_for_compact_or_pause"
    PAUSED = "paused"
    COMPACTED = "native_compaction_returned"
    STALE = "stale_episode"
    FAILED = "failed_without_fallback"


@dataclass(frozen=True)
class Budget:
    """Host-measured complete request input plus reserves; never a byte heuristic."""
    input_tokens: int
    generation_reserve: int
    uncertainty_margin: int
    window: int
    scoped_tokens: int
    scoped_limit: int
    hysteresis: int

    def fits(self) -> bool:
        values = vars(self).values()
        if any(type(v) is not int or v < 0 for v in values):
            return False
        return (self.window > 0 and self.scoped_limit > 0
                and self.input_tokens + self.generation_reserve + self.uncertainty_margin <= self.window
                and self.scoped_tokens + self.hysteresis < self.scoped_limit)


class Host(Protocol):
    """All methods refer to a single isolated thread and authorized pending task."""
    def revision(self) -> str:
        """Stamp includes appends, pending input, model, policy, and history edits."""
        ...
    def propose_prune(self) -> Any:
        """Return bounded validated proposal; no mutation or native compaction."""
        ...
    def commit_prune(self, expected_revision: str, plan: Any) -> bool:
        """Atomically persist/rebase active projection; false means nothing committed."""
        ...
    def budget(self) -> Budget | None:
        """Count complete next request; None cannot authorize continuation."""
        ...
    def native_compact(self, trigger: str) -> None:
        """Call original implementation, preserving native hooks and failures."""
        ...


@dataclass
class Episode:
    id: str
    revision: str
    trigger: str
    prune_attempted: bool = False
    closed: bool = False


class Gate:
    def __init__(self, host: Host):
        self.host = host
        self.episode: Episode | None = None

    def begin(self, episode_id: str, trigger: str = "automatic") -> Episode:
        if self.episode and not self.episode.closed:
            return self.episode  # Do not create duplicate popups.
        self.episode = Episode(episode_id, self.host.revision(), trigger)
        return self.episode

    def manual_compact(self) -> Outcome:
        self.host.native_compact("manual")  # No evaluator, chooser or wrapper fallback.
        return Outcome.COMPACTED

    def manual_prune(self) -> Outcome:
        stamp = self.host.revision()
        try:
            plan = self.host.propose_prune()
            return Outcome.APPLIED if self.host.commit_prune(stamp, plan) else Outcome.STALE
        except Exception:
            return Outcome.FAILED  # Deliberately never invoke native compaction.

    def choose(self, episode_id: str, choice: Choice) -> Outcome:
        episode = self.episode
        if not episode or episode.closed or episode.id != episode_id:
            return Outcome.STALE
        if self.host.revision() != episode.revision:
            episode.closed = True
            return Outcome.STALE
        if choice == Choice.PAUSE:
            episode.closed = True
            return Outcome.PAUSED
        if choice == Choice.COMPACT:
            episode.closed = True
            try:
                self.host.native_compact(episode.trigger)
                return Outcome.COMPACTED
            except Exception:
                return Outcome.FAILED
        if choice != Choice.PRUNE or episode.prune_attempted:
            raise PruneError("Invalid or repeated choice")
        episode.prune_attempted = True
        try:
            plan = self.host.propose_prune()
            if not self.host.commit_prune(episode.revision, plan):
                episode.closed = True
                return Outcome.STALE
            episode.revision = self.host.revision()
            budget = self.host.budget()
            if budget and budget.fits():
                episode.closed = True
                return Outcome.READY
        except Exception:
            # A host must report any durable commit separately from a later failure.
            # Never roll back by guessing; query its current revision and stay held.
            episode.revision = self.host.revision()
        return Outcome.WAITING
