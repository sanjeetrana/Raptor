// Command buildproof computes deterministic SHA-256 receipts using only the Go
// standard library. With two inputs, it also fails if their bytes differ.
package main

import (
	"bytes"
	"crypto/sha256"
	"flag"
	"fmt"
	"io"
	"os"
)

func main() {
	flags := flag.NewFlagSet("buildproof", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	output := flags.String("output", "", "also write the checksum list to this file")
	hashOnly := flags.Bool("hash-only", false, "print one SHA-256 hash per input without file names")
	if err := flags.Parse(os.Args[1:]); err != nil {
		os.Exit(2)
	}
	paths := flags.Args()
	if len(paths) == 0 {
		fmt.Fprintln(os.Stderr, "usage: go run ./tools/buildproof [-output FILE] [-hash-only] FILE [FILE ...]")
		os.Exit(2)
	}
	hashes := make([][sha256.Size]byte, 0, len(paths))
	var receipt bytes.Buffer
	for _, path := range paths {
		hash, err := hashFile(path)
		if err != nil {
			fmt.Fprintf(os.Stderr, "buildproof: %s: %v\n", path, err)
			os.Exit(1)
		}
		hashes = append(hashes, hash)
		if *hashOnly {
			fmt.Fprintf(&receipt, "%x\n", hash)
		} else {
			fmt.Fprintf(&receipt, "%x  %s\n", hash, path)
		}
	}
	_, _ = os.Stdout.Write(receipt.Bytes())
	if len(hashes) == 2 && hashes[0] != hashes[1] {
		fmt.Fprintln(os.Stderr, "buildproof: files are not byte-identical")
		os.Exit(1)
	}
	if *output != "" {
		if err := os.WriteFile(*output, receipt.Bytes(), 0o644); err != nil {
			fmt.Fprintf(os.Stderr, "buildproof: write receipt: %v\n", err)
			os.Exit(1)
		}
	}
}

func hashFile(path string) ([sha256.Size]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return [sha256.Size]byte{}, err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return [sha256.Size]byte{}, err
	}
	var result [sha256.Size]byte
	copy(result[:], hash.Sum(nil))
	return result, nil
}
