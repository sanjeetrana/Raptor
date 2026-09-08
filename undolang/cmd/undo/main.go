package main

import (
	"os"

	"github.com/daniel-oluwadunsin/undolang/internal/cli"
)

func main() { os.Exit((cli.App{Stdout: os.Stdout, Stderr: os.Stderr}).Run(os.Args[1:])) }
