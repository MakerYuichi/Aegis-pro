"""CPython module builtins and their Optional types.

These are set by the CPython interpreter, not by the source file. The
Investigator can't see them as assignments because they aren't
assignments — they're set at import time by the interpreter itself.

Under -OO mode, docstrings are stripped and __doc__ becomes None.
Under -c or -m invocation, __file__ can be None. These are the shapes
that make pyright's reportOptional* rules fire on module builtins, and
that make those findings real bugs rather than false positives.

The Investigator is a general-purpose reasoner. It doesn't know
CPython's interpreter-level invariants by default. This module is the
table those invariants live in. When the pipeline hands the agent a
candidate whose symbol matches an entry here, the prompt surfaces the
invariant. The agent then reasons correctly about "should this
operation be guarded against None" — the answer for `__doc__ + '\n'`
is yes, because under some invocations `__doc__` genuinely is None.

Scope: CPython only. PyPy, MicroPython, and other Python runtimes
have similar but not identical semantics for some of these names.
The table lists the CPython invariants; using it under another
runtime would be overconfident. Nothing enforces that distinction
today — the pipeline targets CPython.
"""
from __future__ import annotations


# Module builtins that CPython sets to Optional[T].
#
# Each entry: name → (type_description, reason_it_can_be_None)
#
# The reason is written to be read by an LLM. It explains *why* the
# value can be None, not just *that* it can be. An LLM reasoning
# about "__doc__ + '\n'" needs to know the -OO mode explanation to
# correctly decide "yes, this can crash". A bare "Optional[str]" is
# not enough.
OPTIONAL_MODULE_BUILTINS: dict[str, tuple[str, str]] = {
    "__doc__": (
        "Optional[str]",
        "the module docstring; under python -OO (which strips "
        "docstrings) this is None",
    ),
    "__file__": (
        "Optional[str]",
        "the source file path; None when code runs from stdin or -c",
    ),
    "__spec__": (
        "Optional[ModuleSpec]",
        "the module spec; None for __main__ and the interactive REPL",
    ),
    "__loader__": (
        "Optional[Loader]",
        "the loader; None in some environments (frozen modules, "
        "imported modules)",
    ),
    "__package__": (
        "Optional[str]",
        "the package name; None for top-level scripts",
    ),
    "__path__": (
        "Optional[list[str]]",
        "the search path; None for non-package modules",
    ),
}


def lookup(symbol: str) -> tuple[str, str] | None:
    """Return (type_description, reason) for a module builtin, or None.

    Normalizes on the bare name so callers can pass either form:
        "__doc__"
        "module.__doc__"
        "self.__doc__"

    Strips attribute access, brackets, and trailing parens before
    the lookup. Preserves underscores — every key in the table has
    leading and trailing underscores, which is exactly what a naive
    strip() would remove.
    """
    if not symbol:
        return None
    bare = symbol.strip().rstrip("()").split("[")[0].rsplit(".", 1)[-1]
    return OPTIONAL_MODULE_BUILTINS.get(bare)


def format_note(symbol: str) -> str | None:
    """Return a prompt-ready note for a module builtin, or None.

    The note is what the Investigator sees. It states the type, the
    reason, and the implication in one paragraph. Meant to be
    appended to the system prompt only when the candidate's symbol
    matches — not to every prompt.

    Returns None when the symbol is not a known module builtin, so
    callers can gate on `if note is not None`.
    """
    entry = lookup(symbol)
    if entry is None:
        return None
    type_desc, reason = entry
    return (
        f"The symbol `{symbol}` in this finding is a CPython module "
        f"builtin. Its type is `{type_desc}` and it can be `None` "
        f"because {reason}. Treat any operation on this symbol that "
        f"requires a non-None value as a potential real defect. "
        f"Specifically: arithmetic (+, *, etc.), attribute access "
        f"(x.y), subscript access (x[k]), calling (x()), and "
        f"iteration (for _ in x) all raise at runtime when the "
        f"symbol is None. If the code does not have a runtime guard "
        f"before the operation, this is a real bug, not a false "
        f"positive."
    )
