.PHONY: build test bench deps-proof repro demo install clean

build:
	go build -trimpath -buildvcs=false -o bin/replaynet ./cmd/replaynet

test:
	go test -v ./...

bench:
	go test -bench=. -benchmem ./tests

deps-proof:
	go list -m all > deps-proof.txt

repro:
	./scripts/reproducible-build.sh

demo: build
	./scripts/demo.sh

install: build
	install -m 755 bin/replaynet /usr/local/bin/replaynet 2>/dev/null || cp bin/replaynet $$(go env GOPATH)/bin/replaynet

clean:
	rm -rf bin demo.rnet
