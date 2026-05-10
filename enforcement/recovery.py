"""
Recovery executor — async dispatcher for RecoveryRequest.

Receives a RecoveryRequest from the decision layer, looks up the
registered handler for the request's action, awaits its execution, and
emits a RecoveryAck whether the handler succeeded, failed, or raised.

Architectural rules
-------------------
- The executor is async because real action handlers (e.g. MAVSDK mode
  change) are async. Synchronous handlers (e.g. subprocess restart) live
  inside an async wrapper and are still awaited by the executor.
- Action handlers are PLUGGABLE: registered in a dict at executor
  construction. This makes the executor architecture-independent and
  unit-testable with stub handlers; real PX4/MAVSDK/iptables handlers
  arrive in step 8 (monitor wiring) without changing this module.
- `enabled=False` short-circuits to a failure ack with
  error='recovery_disabled'. This is a defensive safety net — under
  normal flow RecoveryDecider already drops requests when recovery is
  off, so this branch fires only on misconfiguration.

Failure modes
-------------
Every path that can fail produces a RecoveryAck with success=False and
a structured error string, never an unhandled exception. The executor's
contract to the host monitor is: you give me a RecoveryRequest, I give
you back a RecoveryAck — always. The error categories are:

    recovery_disabled               executor disabled
    unknown_action:<action>         no handler registered
    handler_exception:<message>     handler raised
    <message>                       handler returned (False, message)

The full chain is reconstructible from the JSONL log via caused_by:
SecurityEvent -> IsolationAnnounce -> RecoveryRequest -> RecoveryAck.

The action timing decomposition (detect -> isolate -> recovery_start
-> recovery_complete) is the responsibility of the metrics module
(step 10), not the executor — the executor only carries timestamps via
the events it produces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.events import RecoveryAck, RecoveryRequest


class ActionHandler(ABC):
    """
    Pluggable handler for one recovery action.

    Real implementations (RestartProcessHandler, ModeLoiterHandler,
    FilterCommandsHandler) live in this package and are wired up in
    step 8. Tests construct lightweight fakes that implement this
    interface directly.

    The execute() method must NOT raise. Errors are returned as
    (False, error_message). The executor will catch exceptions
    defensively, but a well-behaved handler reports its own errors.
    """

    @abstractmethod
    async def execute(
        self, request: RecoveryRequest
    ) -> tuple[bool, Optional[str]]:
        """
        Carry out the action. Return (success, error_message).

        success=True implies error_message is None.
        success=False MUST include a non-empty error_message.
        """


class RecoveryExecutor:
    """
    Dispatch RecoveryRequest -> ActionHandler.execute -> RecoveryAck.

    Parameters
    ----------
    source     Process identifier emitted as RecoveryAck.source and
               .executor. In Architecture C this is typically
               'enforcer_uav_<i>' on the target UAV's monitor process.
    enabled    Defensive flag. False means short-circuit every
               request to a failure ack. Architectures A and B set
               enabled=False; C sets enabled=True.
    handlers   Mapping action name -> ActionHandler instance.
               Architecture C registers all three actions; minimal
               configurations may register a subset (and the executor
               will report unknown_action for any others received).
    """

    def __init__(
        self,
        source: str,
        *,
        enabled: bool,
        handlers: dict[str, ActionHandler],
    ) -> None:
        self._source = source
        self._enabled = enabled
        self._handlers: dict[str, ActionHandler] = dict(handlers)

        # Diagnostics counters.
        self._n_executed: int = 0
        self._n_succeeded: int = 0
        self._n_failed: int = 0
        self._n_disabled: int = 0
        self._n_unknown_action: int = 0
        self._n_handler_exceptions: int = 0

    # ----- main API -----

    async def execute(self, request: RecoveryRequest) -> RecoveryAck:
        if not self._enabled:
            self._n_disabled += 1
            return self._fail(request, error="recovery_disabled")

        handler = self._handlers.get(request.action)
        if handler is None:
            self._n_unknown_action += 1
            return self._fail(request, error=f"unknown_action:{request.action}")

        self._n_executed += 1
        try:
            success, error = await handler.execute(request)
        except Exception as exc:
            self._n_handler_exceptions += 1
            self._n_failed += 1
            return self._fail(request, error=f"handler_exception:{exc}")

        if not success:
            self._n_failed += 1
            return self._fail(
                request,
                error=error if error else "handler_returned_failure",
            )

        # Defensive: success=True must mean no error message — fix-up if
        # a handler violates the contract by returning (True, "junk").
        self._n_succeeded += 1
        return RecoveryAck(
            source=self._source,
            target_uav=request.target_uav,
            action=request.action,
            success=True,
            executor=self._source,
            error=None,
            caused_by=request.event_id,
        )

    def reset(self) -> None:
        self._n_executed = 0
        self._n_succeeded = 0
        self._n_failed = 0
        self._n_disabled = 0
        self._n_unknown_action = 0
        self._n_handler_exceptions = 0

    # ----- diagnostics -----

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def supported_actions(self) -> frozenset[str]:
        return frozenset(self._handlers.keys())

    @property
    def stats(self) -> dict[str, int]:
        return {
            "executed": self._n_executed,
            "succeeded": self._n_succeeded,
            "failed": self._n_failed,
            "disabled_short_circuits": self._n_disabled,
            "unknown_action": self._n_unknown_action,
            "handler_exceptions": self._n_handler_exceptions,
        }

    # ----- internals -----

    def _fail(self, request: RecoveryRequest, *, error: str) -> RecoveryAck:
        return RecoveryAck(
            source=self._source,
            target_uav=request.target_uav,
            action=request.action,
            success=False,
            executor=self._source,
            error=error,
            caused_by=request.event_id,
        )
