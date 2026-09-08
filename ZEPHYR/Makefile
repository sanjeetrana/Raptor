# ZEPHYR v2.0.0 (by Naman Swami) Makefile
# Standard one-command builds for local environments & CI

.PHONY: all build test doctor check-deps clean reproducible-build

all: build test

build:
	go build -o zephyr.exe main.go

test:
	go test -vet=off -v ./...

doctor:
	go run main.go doctor

check-deps:
	@echo "Auditing dependencies..."
	go list -m all

reproducible-build:
	go build -trimpath -ldflags="-s -w -buildid=" -o b1.exe main.go
	go build -trimpath -ldflags="-s -w -buildid=" -o b2.exe main.go
	@echo "Checking byte-identical SHA256 hashes..."
	@certutil -hashfile b1.exe SHA256 2>nul || sha256sum b1.exe
	@certutil -hashfile b2.exe SHA256 2>nul || sha256sum b2.exe

clean:
	rm -f zephyr.exe taskrunner.exe b1.exe b2.exe
	rm -rf .taskcache .cache-server
