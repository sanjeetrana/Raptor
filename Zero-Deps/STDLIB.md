# Standard Library Compliance

NoDepDB follows a strict zero-dependency policy.

This project uses only the programming language's standard library and does not rely on any third-party packages.

## Command Line Interface

Normally Used:
- click
- typer

Used Instead:
- argparse

Reason:
argparse is included in the standard library and provides command-line argument parsing.

---

## Networking

Normally Used:
- requests
- aiohttp

Used Instead:
- socket

Reason:
socket provides TCP client and server communication without external dependencies.

---

## Output Formatting

Normally Used:
- rich

Used Instead:
- print()
- ANSI escape codes

Reason:
Simple formatted terminal output can be achieved using built-in functionality.

---

## Testing

Normally Used:
- pytest

Used Instead:
- unittest

Reason:
unittest is part of the standard library and supports automated testing.

---

## File Handling

Used Modules:
- os
- pathlib

Purpose:
Reading configuration files, command files, and database persistence.

---

## Time Utilities

Used Modules:
- time

Purpose:
Connection retries, timestamps, and uptime calculations.

---

## Summary

NoDepDB demonstrates that networking, storage, testing, and command-line tooling can be implemented using only standard library modules.
