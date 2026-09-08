# Standard-Library Implementation

The canonical, judge-facing ledger is [`../STDLIB.md`](../STDLIB.md). It documents more than ten concrete substitutions and links each one to the production source that implements it.

Dependency invariants:

- Go 1.27 standard library only;
- no `require` block;
- no `go.sum`;
- no vendor tree;
- no runtime subprocesses or services;
- no website package manager or remote asset dependency.
