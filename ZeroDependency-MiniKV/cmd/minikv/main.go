// Command minikv is the CLI for MiniKV, a zero-dependency embedded
// key-value storage engine. See internal/engine for the storage engine
// itself and internal/cli for command implementations.
package main

import (
	"os"

	"minikv/internal/cli"
)

func main() {
	code := cli.Run(os.Args[1:], os.Stdout, os.Stderr)
	os.Exit(code)
}
