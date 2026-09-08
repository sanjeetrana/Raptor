# ---------------------------------------------------------------------------
# stranger — build system
#
# There is one source file and no dependencies, so there is not much to do
# here. `make` produces a runnable binary in one step, which is the rule.
# ---------------------------------------------------------------------------

SRC := src/main.rs

# --- MSYS / Git Bash guard -------------------------------------------------
#
# Under MSYS (Git Bash, MSYS2), any argument that looks like a Unix path is
# rewritten into a Windows one before the program sees it. That turns the
# linker flag `/Brepro` into `C:/Program Files/Git/Brepro`, and link.exe then
# fails with LNK1181 looking for `Brepro.obj`. These two variables switch the
# rewriting off. They are inert on Linux and macOS, where nothing reads them.
export MSYS_NO_PATHCONV := 1
export MSYS2_ARG_CONV_EXCL := *

# --- platform detection ----------------------------------------------------
#
# Reproducible builds are per-target by definition, and each linker hides its
# nondeterminism somewhere different. Detect the host and pass the right flag
# rather than pretending one incantation covers every platform.
RUST_HOST := $(shell rustc -vV 2>/dev/null | sed -n 's/^host: //p')

ifneq (,$(findstring windows,$(RUST_HOST)))
  BIN := stranger.exe
else
  BIN := stranger
endif

# MSVC embeds two per-link nondeterministic values in the PE image:
#   /Brepro      replaces the COFF TimeDateStamp with a content hash
#   /DEBUG:NONE  drops the CodeView debug directory, whose PDB GUID is
#                regenerated on every link — and which /Brepro would otherwise
#                fold into its hash, so the "deterministic" stamp varied too.
# Without both, two builds differ by 69 bytes across three sites. With both,
# they are byte-identical. Found the hard way; see STDLIB.md.
ifneq (,$(findstring windows-msvc,$(RUST_HOST)))
  PLATFORM_FLAGS := -C link-arg=/Brepro -C link-arg=/DEBUG:NONE
endif

# MinGW's ld stamps a timestamp of its own; this is its off switch.
ifneq (,$(findstring windows-gnu,$(RUST_HOST)))
  PLATFORM_FLAGS := -C link-arg=-Wl,--no-insert-timestamp
endif

# ELF carries no link timestamp, so nothing extra is needed there.
PLATFORM_FLAGS ?=

# --- determinism flags -----------------------------------------------------
#
# Each one removes a source of nondeterminism:
#   codegen-units=1     parallel codegen can reorder symbols between runs
#   debuginfo=0         debug records embed absolute paths
#   strip=symbols       symbol tables carry build-host detail
#   metadata            pins the crate disambiguator instead of deriving it
#   remap-path-prefix   erases the absolute build directory from the binary
REPRO_FLAGS := -C codegen-units=1 -C debuginfo=0 -C strip=symbols \
               -C metadata=stranger-1.0.0 $(PLATFORM_FLAGS) \
               --remap-path-prefix=$(CURDIR)=.

.PHONY: all build test check repro deps-proof clean demo install info

all: build

## info: what this build will do on this machine
info:
	@echo "host:            $(RUST_HOST)"
	@echo "binary:          $(BIN)"
	@echo "platform flags:  $(if $(PLATFORM_FLAGS),$(PLATFORM_FLAGS),none needed)"

## build: the one command. Produces the binary.
build:
	rustc -O $(REPRO_FLAGS) -o $(BIN) $(SRC)
	@echo "built ./$(BIN)  ($$(wc -c < $(BIN)) bytes)"

## test: run the suite (63 tests, stdlib harness, no test crate)
test:
	cargo test

## check: build + test, what CI runs
check: build test

## repro: build twice into separate trees and prove the bytes match
repro:
	@rm -rf .repro && mkdir -p .repro/a .repro/b
	@SOURCE_DATE_EPOCH=1756400000 rustc -O $(REPRO_FLAGS) -o .repro/a/$(BIN) $(SRC)
	@SOURCE_DATE_EPOCH=1756400000 rustc -O $(REPRO_FLAGS) -o .repro/b/$(BIN) $(SRC)
	@echo "target:  $(RUST_HOST)"
	@echo "build 1: $$(sha256sum .repro/a/$(BIN) | cut -d' ' -f1)"
	@echo "build 2: $$(sha256sum .repro/b/$(BIN) | cut -d' ' -f1)"
	@cmp .repro/a/$(BIN) .repro/b/$(BIN) \
	  && echo "REPRODUCIBLE: byte-identical" \
	  || (echo "NOT REPRODUCIBLE: $$(cmp -l .repro/a/$(BIN) .repro/b/$(BIN) | wc -l) bytes differ"; exit 1)

## deps-proof: regenerate the evidence that the manifest is empty
deps-proof: build
	@{ \
	  echo "# Dependency proof for stranger $(shell date -u +%Y-%m-%dT%H:%M:%SZ)"; \
	  echo "# Regenerate with: make deps-proof"; \
	  echo; \
	  echo '$$ rustc -vV'; \
	  rustc -vV; \
	  echo; \
	  echo '$$ cargo tree'; \
	  cargo tree; \
	  echo; \
	  echo '$$ grep -c "\[\[package\]\]" Cargo.lock'; \
	  grep -c '\[\[package\]\]' Cargo.lock; \
	  echo; \
	  echo '$$ cat Cargo.lock'; \
	  cat Cargo.lock; \
	  echo; \
	  echo '$$ ./$(BIN) audit Cargo.lock   # the tool auditing itself'; \
	  ./$(BIN) audit Cargo.lock --color never 2>&1 || true; \
	  echo; \
	  echo '# ---- reproducible build ----'; \
	  echo '$$ make repro'; \
	  $(MAKE) --no-print-directory repro; \
	} > deps-proof.txt
	@echo "wrote deps-proof.txt"

## demo: the tour used in the video
demo: build
	@echo '$$ ./$(BIN) audit examples/compromised-lock.json'
	@./$(BIN) audit examples/compromised-lock.json --color always --top 4 || true
	@echo
	@echo '$$ ./$(BIN) diff examples/clean-lock.json examples/compromised-lock.json'
	@./$(BIN) diff examples/clean-lock.json examples/compromised-lock.json --color always || true

install: build
	install -m 0755 $(BIN) $(DESTDIR)/usr/local/bin/$(BIN)

clean:
	rm -rf target $(BIN) .repro
