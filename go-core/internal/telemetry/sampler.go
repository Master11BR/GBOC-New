// ==============================================================================
// GBOC System v15.0.0 Enterprise Edition — Go Telemetry & Watchdog Engine
// Copyright (c) 2026 Master11BR - Todos os direitos reservados.
// ==============================================================================

package telemetry

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"runtime"
	"time"
)

type NodeStatus struct {
	Component  string  `json:"component"`
	URL        string  `json:"url"`
	Healthy    bool    `json:"healthy"`
	LatencyMs  float64 `json:"latency_ms"`
	StatusCode int     `json:"status_code"`
	CheckedAt  string  `json:"checked_at"`
	Error      string  `json:"error,omitempty"`
}

type RuntimeTelemetry struct {
	Hostname     string       `json:"hostname"`
	OS           string       `json:"os"`
	Arch         string       `json:"arch"`
	NumCPU       int          `json:"num_cpu"`
	GoVersion    string       `json:"go_version"`
	Goroutines   int          `json:"goroutines"`
	AllocBytes   uint64       `json:"alloc_bytes"`
	TimestampUTC string       `json:"timestamp_utc"`
	Nodes        []NodeStatus `json:"nodes,omitempty"`
}

// CollectSnapshot gathers host/runtime telemetry and checks configured HTTP watchdog endpoints concurrently.
func CollectSnapshot(ctx context.Context, urls []string, timeout time.Duration) RuntimeTelemetry {
	host, _ := os.Hostname()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)

	snap := RuntimeTelemetry{
		Hostname:     host,
		OS:           runtime.GOOS,
		Arch:         runtime.Arch,
		NumCPU:       runtime.NumCPU(),
		GoVersion:    runtime.Version(),
		Goroutines:   runtime.NumGoroutine(),
		AllocBytes:   ms.Alloc,
		TimestampUTC: time.Now().UTC().Format(time.RFC3339),
	}

	if len(urls) == 0 {
		return snap
	}

	ch := make(chan NodeStatus, len(urls))
	client := &http.Client{Timeout: timeout}

	for _, u := range urls {
		go func(target string) {
			t0 := time.Now()
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
			if err != nil {
				ch <- NodeStatus{URL: target, Healthy: false, CheckedAt: time.Now().UTC().Format(time.RFC3339), Error: err.Error()}
				return
			}
			resp, err := client.Do(req)
			dt := float64(time.Since(t0).Microseconds()) / 1000.0
			if err != nil {
				ch <- NodeStatus{URL: target, Healthy: false, LatencyMs: dt, CheckedAt: time.Now().UTC().Format(time.RFC3339), Error: err.Error()}
				return
			}
			_ = resp.Body.Close()
			ch <- NodeStatus{
				URL:        target,
				Healthy:    resp.StatusCode >= 200 && resp.StatusCode < 400,
				LatencyMs:  dt,
				StatusCode: resp.StatusCode,
				CheckedAt:  time.Now().UTC().Format(time.RFC3339),
			}
		}(u)
	}

	for i := 0; i < len(urls); i++ {
		snap.Nodes = append(snap.Nodes, <-ch)
	}
	return snap
}

// BroadcastHermesBeacon sends a single UDP LAN Mesh discovery beacon on port 19200.
func BroadcastHermesBeacon(agentID string, port int) error {
	if port <= 0 {
		port = 19200
	}
	addr := &net.UDPAddr{IP: net.IPv4bcast, Port: port}
	conn, err := net.DialUDP("udp4", nil, addr)
	if err != nil {
		return err
	}
	defer conn.Close()

	payload, _ := json.Marshal(map[string]any{
		"type":      "gboc-hermes-beacon",
		"version":   "15.0.0",
		"agent_id":  agentID,
		"timestamp": time.Now().UTC().Unix(),
	})
	_, err = fmt.Fprintf(conn, "%s", string(payload))
	return err
}

