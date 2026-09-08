package main

import (
	"flag"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"

	"replaynet/internal/proxy"
	"replaynet/internal/replay"
	"replaynet/internal/session"
	"replaynet/internal/visualizer"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}

	switch os.Args[1] {
	case "proxy":
		runProxy(os.Args[2:])
	case "replay":
		runReplay(os.Args[2:])
	case "version", "-version", "--version", "-v":
		fmt.Println("replaynet v0.1.0 (zero-dependency stdlib-only)")
	case "help", "-help", "--help", "-h":
		usage()
	default:
		usage()
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "ReplayNet - Zero-dependency HTTP recording, deterministic replay & fault injection")
	fmt.Fprintln(os.Stderr, "")
	fmt.Fprintln(os.Stderr, "Usage:")
	fmt.Fprintln(os.Stderr, "  replaynet proxy --listen :9000 --upstream http://localhost:3000 --session out.rnet [--inspect :9001]")
	fmt.Fprintln(os.Stderr, "  replaynet replay session.rnet --listen :9002 [--fault at=N,type=latency,ms=N] [--inspect :9003]")
	fmt.Fprintln(os.Stderr, "  replaynet version")
	fmt.Fprintln(os.Stderr, "")
	fmt.Fprintln(os.Stderr, "Commands:")
	fmt.Fprintln(os.Stderr, "  proxy    Record inbound HTTP traffic and forward to upstream")
	fmt.Fprintln(os.Stderr, "  replay   Deterministically replay recorded session without upstream")
	fmt.Fprintln(os.Stderr, "  version  Print version information")
}

func runProxy(args []string) {
	fs := flag.NewFlagSet("proxy", flag.ExitOnError)
	listen := fs.String("listen", ":9000", "address to listen on")
	upstream := fs.String("upstream", "", "upstream backend URL to proxy traffic to (required)")
	sessionPath := fs.String("session", "session.rnet", "path to .rnet session file to write")
	inspect := fs.String("inspect", "", "optional port to start the live visualizer inspector on")
	fs.Parse(args)

	if *upstream == "" {
		fmt.Fprintln(os.Stderr, "error: --upstream is required")
		fs.Usage()
		os.Exit(1)
	}

	var viz *visualizer.Server
	if *inspect != "" {
		viz = visualizer.New()
		go func() {
			fmt.Println("inspector listening on", *inspect)
			http.ListenAndServe(*inspect, viz.Handler())
		}()
	}

	var onEvent func(session.Event)
	if viz != nil {
		onEvent = viz.Broadcast
	}

	p, err := proxy.New(*upstream, *sessionPath, onEvent)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	defer p.Close()

	fmt.Println("proxying", *listen, "->", *upstream)
	fmt.Println("recording to", *sessionPath)

	if err := http.ListenAndServe(*listen, p); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func runReplay(args []string) {
	fs := flag.NewFlagSet("replay", flag.ExitOnError)
	listen := fs.String("listen", ":9002", "address to listen on")
	inspect := fs.String("inspect", "", "optional port to start the live visualizer inspector on")
	var faultArgs repeatedFlag
	fs.Var(&faultArgs, "fault", "fault rule e.g. 'at=3,type=latency,ms=4000' or 'at=3,type=status,code=503'")

	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "error: session file required")
		usage()
		os.Exit(1)
	}

	if args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
		fmt.Fprintln(os.Stderr, "usage: replaynet replay <session.rnet> [flags]")
		fs.Usage()
		os.Exit(0)
	}

	sessionPath := args[0]
	fs.Parse(args[1:])

	sess, err := session.Load(sessionPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error loading session:", err)
		os.Exit(1)
	}

	var viz *visualizer.Server
	if *inspect != "" {
		viz = visualizer.New()
		go func() {
			fmt.Println("inspector listening on", *inspect)
			http.ListenAndServe(*inspect, viz.Handler())
		}()
	}

	var onEvent func(session.Event)
	if viz != nil {
		onEvent = viz.Broadcast
	}

	faults, err := parseFaults(faultArgs)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error parsing --fault:", err)
		os.Exit(1)
	}

	srv := replay.New(sess, faults, onEvent)

	fmt.Println("replaying", sessionPath, "on", *listen)

	if err := http.ListenAndServe(*listen, srv); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func parseFaults(raw []string) ([]replay.FaultRule, error) {
	var rules []replay.FaultRule
	for _, r := range raw {
		rule := replay.FaultRule{}
		parts := strings.Split(r, ",")
		for _, part := range parts {
			kv := strings.SplitN(part, "=", 2)
			if len(kv) != 2 {
				return nil, fmt.Errorf("malformed fault clause: %q", part)
			}
			key, val := kv[0], kv[1]
			switch key {
			case "at":
				n, err := strconv.Atoi(val)
				if err != nil {
					return nil, err
				}
				rule.AtEventIndex = n
			case "type":
				switch val {
				case "latency":
					rule.Type = replay.FaultLatency
				case "drop":
					rule.Type = replay.FaultDrop
				case "status":
					rule.Type = replay.FaultStatus
				default:
					return nil, fmt.Errorf("unknown fault type: %q", val)
				}
			case "ms":
				n, err := strconv.Atoi(val)
				if err != nil {
					return nil, err
				}
				rule.LatencyMs = n
			case "code":
				n, err := strconv.Atoi(val)
				if err != nil {
					return nil, err
				}
				rule.StatusOverride = n
			}
		}
		rules = append(rules, rule)
	}
	return rules, nil
}
