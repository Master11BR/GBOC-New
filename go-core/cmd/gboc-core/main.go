// ==============================================================================
// GBOC System v15.0.0 Enterprise Edition — Go Core CLI & Native Worker Engine
// Copyright (c) 2026 Master11BR - Todos os direitos reservados.
// ==============================================================================

package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/master11br/gboc-go-core/internal/chunker"
	"github.com/master11br/gboc-go-core/internal/syncer"
	"github.com/master11br/gboc-go-core/internal/telemetry"
)

const Version = "15.0.0"

func main() {
	if len(os.Args) < 2 {
		printVersion()
		return
	}

	sub := os.Args[1]
	switch sub {
	case "version", "--version", "-v":
		printVersion()

	case "verify-repo":
		fs := flag.NewFlagSet("verify-repo", flag.ExitOnError)
		repo := fs.String("repo", "", "Repository root directory")
		snap := fs.String("snapshot", "", "Optional snapshot ID")
		readData := fs.Bool("read-data", false, "Read and decompress blocks to verify SHA-256")
		_ = fs.Parse(os.Args[2:])
		if *repo == "" {
			fatalJSON("missing --repo argument")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
		defer cancel()
		rep := chunker.VerifyLocalRepo(ctx, *repo, *snap, *readData)
		writeJSON(rep)

	case "hash-dir":
		fs := flag.NewFlagSet("hash-dir", flag.ExitOnError)
		src := fs.String("src", "", "Source directory to chunk and hash")
		workers := fs.Int("workers", 0, "Worker goroutines (default: NumCPU)")
		_ = fs.Parse(os.Args[2:])
		if *src == "" {
			fatalJSON("missing --src argument")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Minute)
		defer cancel()
		items, err := chunker.HashDirectoryConcurrent(ctx, *src, *workers)
		if err != nil {
			fatalJSON(err.Error())
		}
		writeJSON(map[string]any{
			"status":  "success",
			"engine":  "gboc-go-core",
			"version": Version,
			"files":   items,
		})

	case "telemetry":
		fs := flag.NewFlagSet("telemetry", flag.ExitOnError)
		urlsRaw := fs.String("urls", "http://127.0.0.1:8000/api/watchdog/ping,http://127.0.0.1:9200/api/watchdog/ping", "Comma-separated watchdog URLs")
		timeoutMs := fs.Int("timeout-ms", 2500, "HTTP probe timeout in milliseconds")
		_ = fs.Parse(os.Args[2:])
		var urls []string
		for _, u := range strings.Split(*urlsRaw, ",") {
			if strings.TrimSpace(u) != "" {
				urls = append(urls, strings.TrimSpace(u))
			}
		}
		ctx, cancel := context.WithTimeout(context.Background(), time.Duration(*timeoutMs+500)*time.Millisecond)
		defer cancel()
		snap := telemetry.CollectSnapshot(ctx, urls, time.Duration(*timeoutMs)*time.Millisecond)
		writeJSON(snap)

	case "sync-assets":
		fs := flag.NewFlagSet("sync-assets", flag.ExitOnError)
		root := fs.String("root", ".", "Repository root directory")
		verify := fs.Bool("verify", false, "Dry-run verification only")
		_ = fs.Parse(os.Args[2:])
		shared := filepath.Join(*root, "shared-css")
		agentStatic := filepath.Join(*root, "GBOC-Agent", "static")
		serverStatic := filepath.Join(*root, "GBOC-Server", "static")
		rAgent := syncer.SyncTarget(shared, agentStatic, "Agent", *verify)
		rServer := syncer.SyncTarget(shared, serverStatic, "Server", *verify)
		ok := (rAgent.Diverged+rAgent.Missing+rServer.Diverged+rServer.Missing == 0) || !*verify
		writeJSON(map[string]any{
			"status":  map[bool]string{true: "success", false: "diverged"}[ok],
			"version": Version,
			"agent":   rAgent,
			"server":  rServer,
		})
		if !ok {
			os.Exit(1)
		}

	default:
		fatalJSON(fmt.Sprintf("unknown subcommand: %s", sub))
	}
}

func printVersion() {
	writeJSON(map[string]any{
		"system":  "GBOC System Enterprise Go Core",
		"version": Version,
		"status":  "ready",
	})
}

func writeJSON(v any) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func fatalJSON(msg string) {
	writeJSON(map[string]any{
		"status":  "error",
		"message": msg,
	})
	os.Exit(1)
}

