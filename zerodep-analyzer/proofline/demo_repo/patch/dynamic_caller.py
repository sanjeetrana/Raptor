"""
dynamic_caller.py — ADVERSARIAL CASE: dynamic dispatch via getattr.

This file exists to test that Proofline correctly reports UNKNOWN
for dynamic dispatch, per §8:

  "one dynamic-dispatch call (getattr) that must be correctly reported
   as UNKNOWN, not omitted or guessed"

The tool MUST:
  - Flag `getattr(service, method_name)()` as UNKNOWN
  - NOT silently omit this caller
  - NOT upgrade it to PROVEN or INFERRED by guessing

This represents the real-world pattern of plugin systems, dependency
injection frameworks, and config-driven dispatch that AI-generated code
frequently produces.
"""


def dispatch_auth_check(service, method_name: str, token: str):
    """
    Dynamic dispatch: call any method on service by name.

    PROOFLINE EXPECTED OUTPUT:
      [UNKNOWN] dynamic_caller.dispatch_auth_check → <method_name>
      Cannot statically resolve — getattr-based dispatch.
    """
    # This is the UNKNOWN call site — Proofline cannot know at parse time
    # which method is being called without running the code.
    result = getattr(service, method_name)(token)  # UNKNOWN — dynamic dispatch
    return result


def process_with_validator(token: str, validator_fn) -> int:
    """
    Higher-order function: accepts any callable as validator.

    The call `validator_fn(token)` cannot be statically resolved —
    the callee is a parameter, not a name. UNKNOWN.
    """
    return validator_fn(token)  # UNKNOWN — callable parameter


class PluginRegistry:
    """Plugin system that dispatches via __class__ method lookup."""

    def __init__(self):
        self._handlers: dict = {}

    def register(self, name: str, handler) -> None:
        self._handlers[name] = handler

    def execute(self, name: str, token: str):
        """Dynamic dispatch through registry. UNKNOWN edge."""
        handler = self._handlers.get(name)
        if handler:
            return handler(token)  # UNKNOWN — dict-based dispatch
        return None
