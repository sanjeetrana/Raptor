.DEFAULT_GOAL := help

SHELL := /bin/sh

GO ?= go
BIN ?= dist/undo
FUZZTIME ?= 5s
GO_OFFLINE = GOTOOLCHAIN=go1.27.0 GOPROXY=off
BUILD_ENV = CGO_ENABLED=0 $(GO_OFFLINE)

ROOT_FLAG = $(if $(ROOT),--root "$(ROOT)",)
TRANSACTION_FLAG = $(if $(TRANSACTION),--transaction "$(TRANSACTION)",)
JSON_FLAG = $(if $(JSON),--json,)
YES_FLAG = $(if $(YES),--yes,)
ALLOW_PATH_FLAGS = $(foreach path,$(ALLOW_PATHS),--allow-path "$(path)")

.PHONY: help all build version test vet race fuzz stress crash-test examples \
	check plan run recover history inspect capabilities schema agent-guide \
	modules deps-proof repro reproducible-build release verify

help:
	@echo "UndoLang commands"
	@echo "  make build                                      build $(BIN)"
	@echo "  make version                                    print the binary version"
	@echo "  make test                                       run the offline test suite"
	@echo "  make vet                                        run go vet offline"
	@echo "  make race                                       run the race detector"
	@echo "  make examples                                   parse every examples/*.undo file"
	@echo "  make modules                                    show the module graph (main module only)"
	@echo "  make verify                                     run build, tests, proofs, and release checks"
	@echo "  make check FILE=x.undo ROOT=/path               validate without changing files"
	@echo "  make plan FILE=x.undo ROOT=/path [JSON=1]       inspect the planned changes"
	@echo "  make run FILE=x.undo ROOT=/path YES=1           execute after explicit approval"
	@echo "  make recover ROOT=/path YES=1                   recover an interrupted transaction"
	@echo "  make history ROOT=/path [JSON=1]                list transaction history"
	@echo "  make inspect TXID=id ROOT=/path [JSON=1]        inspect one transaction"
	@echo "  make capabilities                               print the agent capabilities"
	@echo "  make schema                                     print the language schema"
	@echo "  make agent-guide                                print the agent workflow"
	@echo "  make fuzz | make stress | make crash-test       run longer safety checks"
	@echo "  make reproducible-build                        build twice and show both SHA-256 hashes"
	@echo "  make deps-proof | make repro | make release   write/prove release artifacts"
	@echo ""
	@echo "Optional variables: BIN=..., FUZZTIME=5s, TRANSACTION=..., JSON=1, YES=1, ALLOW_PATHS='dir1 dir2'"



build:
	go build ./cmd/undo/main.go

reproducible-build:
	GO="$(GO)" ./scripts/repro-build.sh
