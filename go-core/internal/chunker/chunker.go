// ==============================================================================
// GBOC System v15.0.0 Enterprise Edition — Go Native Chunker & Verifier
// Copyright (c) 2026 Master11BR - Todos os direitos reservados.
// ==============================================================================

package chunker

import (
	"bytes"
	"compress/zlib"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
)

const (
	ChunkSize      = 4 * 1024 * 1024 // 4 MiB
	PackTargetSize = 8 * 1024 * 1024 // 8 MiB
	PackBlobMax    = 512 * 1024      // 512 KiB
)

var PackMagic = []byte("GBP1")

var IncompressibleExts = map[string]bool{
	".zip": true, ".7z": true, ".rar": true, ".gz": true, ".tgz": true,
	".bz2": true, ".xz": true, ".zst": true, ".lz4": true, ".cab": true,
	".jpg": true, ".jpeg": true, ".png": true, ".gif": true, ".webp": true,
	".mp3": true, ".mp4": true, ".mkv": true, ".avi": true, ".mov": true,
	".pdf": true, ".docx": true, ".xlsx": true, ".pptx": true, ".iso": true,
	".vhdx": true, ".pst": true,
}

type FileHashResult struct {
	Path   string   `json:"path"`
	Size   int64    `json:"size"`
	Mtime  float64  `json:"mtime"`
	Hash   string   `json:"hash"`
	Chunks []string `json:"chunks"`
	Error  string   `json:"error,omitempty"`
}

type VerifyIssue struct {
	Snapshot string `json:"snapshot"`
	Path     string `json:"path"`
	Chunk    string `json:"chunk"`
	Error    string `json:"error,omitempty"`
}

type VerifyReport struct {
	Success         bool          `json:"success"`
	Engine          string        `json:"engine"`
	Snapshots       int           `json:"snapshots"`
	ChunksChecked   int           `json:"chunks_checked"`
	Missing         []VerifyIssue `json:"missing"`
	Corrupt         []VerifyIssue `json:"corrupt"`
	LegacySnapshots int           `json:"legacy_snapshots"`
	ReadData        bool          `json:"read_data"`
	Summary         string        `json:"summary"`
}

// SHA256Hex computes the lowercase hex SHA-256 digest of b.
func SHA256Hex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// CompressBlock compresses data using zlib (tag 'Z') or stores raw (tag 'R') when not beneficial.
func CompressBlock(data []byte, codec string) []byte {
	if codec == "none" || len(data) < 64 {
		out := make([]byte, 1+len(data))
		out[0] = 'R'
		copy(out[1:], data)
		return out
	}
	var buf bytes.Buffer
	buf.WriteByte('Z')
	w, err := zlib.NewWriterLevel(&buf, 6)
	if err != nil {
		out := make([]byte, 1+len(data))
		out[0] = 'R'
		copy(out[1:], data)
		return out
	}
	_, _ = w.Write(data)
	_ = w.Close()
	if float64(buf.Len()) >= float64(len(data))*0.97 {
		out := make([]byte, 1+len(data))
		out[0] = 'R'
		copy(out[1:], data)
		return out
	}
	return buf.Bytes()
}

// DecompressBlock decompresses a GBOC v4 block ('R' raw, 'Z' zlib).
func DecompressBlock(blob []byte) ([]byte, error) {
	if len(blob) == 0 {
		return nil, errors.New("empty block")
	}
	switch blob[0] {
	case 'R':
		return blob[1:], nil
	case 'Z':
		r, err := zlib.NewReader(bytes.NewReader(blob[1:]))
		if err != nil {
			return nil, err
		}
		defer r.Close()
		return io.ReadAll(r)
	default:
		return nil, fmt.Errorf("unsupported codec tag: %c", blob[0])
	}
}

// BuildPack concatenates small blobs and appends the GBP1 trailer index.
func BuildPack(blobs map[string][]byte) (string, []byte, [][]any, error) {
	var buf bytes.Buffer
	entries := make([][]any, 0, len(blobs))
	for h, blob := range blobs {
		off := buf.Len()
		entries = append(entries, []any{h, off, len(blob)})
		buf.Write(blob)
	}
	idxJSON, err := json.Marshal(entries)
	if err != nil {
		return "", nil, nil, err
	}
	trailer := CompressBlock(idxJSON, "zlib")
	buf.Write(trailer)
	var lenBytes [4]byte
	binary.LittleEndian.PutUint32(lenBytes[:], uint32(len(trailer)))
	buf.Write(lenBytes[:])
	buf.Write(PackMagic)
	data := buf.Bytes()
	return SHA256Hex(data), data, entries, nil
}

// HashDirectoryConcurrent walks baseDir and hashes/chunks all files using a worker pool.
func HashDirectoryConcurrent(ctx context.Context, baseDir string, workers int) ([]FileHashResult, error) {
	if workers <= 0 {
		workers = runtime.NumCPU()
	}
	paths := make(chan string, workers*4)
	results := make(chan FileHashResult, workers*4)

	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			buf := make([]byte, ChunkSize)
			for p := range paths {
				select {
				case <-ctx.Done():
					return
				default:
				}
				results <- hashSingleFile(baseDir, p, buf)
			}
		}()
	}

	go func() {
		_ = filepath.Walk(baseDir, func(path string, info os.FileInfo, err error) error {
			if err != nil || info == nil || info.IsDir() {
				return nil
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case paths <- path:
				return nil
			}
		})
		close(paths)
		wg.Wait()
		close(results)
	}()

	var out []FileHashResult
	for r := range results {
		out = append(out, r)
	}
	return out, nil
}

func hashSingleFile(baseDir, fullPath string, buf []byte) FileHashResult {
	rel, err := filepath.Rel(baseDir, fullPath)
	if err != nil {
		rel = fullPath
	}
	rel = filepath.ToSlash(rel)
	st, err := os.Stat(fullPath)
	if err != nil {
		return FileHashResult{Path: rel, Error: err.Error()}
	}
	f, err := os.Open(fullPath)
	if err != nil {
		return FileHashResult{Path: rel, Error: err.Error()}
	}
	defer f.Close()

	fileHasher := sha256.New()
	var chunks []string
	for {
		n, rErr := f.Read(buf)
		if n > 0 {
			slice := buf[:n]
			fileHasher.Write(slice)
			chunks = append(chunks, SHA256Hex(slice))
		}
		if rErr == io.EOF {
			break
		}
		if rErr != nil {
			return FileHashResult{Path: rel, Error: rErr.Error()}
		}
	}
	return FileHashResult{
		Path:   rel,
		Size:   st.Size(),
		Mtime:  float64(st.ModTime().UnixNano()) / 1e9,
		Hash:   hex.EncodeToString(fileHasher.Sum(nil)),
		Chunks: chunks,
	}
}

type manifestDoc struct {
	Version int `json:"version"`
	Entries []struct {
		Path   string   `json:"path"`
		Chunks []string `json:"chunks"`
	} `json:"entries"`
}

// VerifyLocalRepo concurrently checks all v4 snapshots and objects in a local repository.
func VerifyLocalRepo(ctx context.Context, repoDir string, snapshotID string, readData bool) VerifyReport {
	entries, err := os.ReadDir(repoDir)
	if err != nil {
		return VerifyReport{
			Success: false,
			Engine:  "gboc-go-core",
			Missing: []VerifyIssue{},
			Corrupt: []VerifyIssue{},
			Summary: fmt.Sprintf("Erro ao abrir repositório: %v", err),
		}
	}

	var snaps []string
	if snapshotID != "" {
		snaps = []string{snapshotID}
	} else {
		for _, e := range entries {
			if e.IsDir() {
				mf := filepath.Join(repoDir, e.Name(), "manifest.json")
				if _, err := os.Stat(mf); err == nil {
					snaps = append(snaps, e.Name())
				}
			}
		}
	}

	checked := make(map[string]bool)
	missing := make([]VerifyIssue, 0)
	corrupt := make([]VerifyIssue, 0)
	legacy := 0

	for _, sid := range snaps {
		mfPath := filepath.Join(repoDir, sid, "manifest.json")
		raw, err := os.ReadFile(mfPath)
		if err != nil {
			continue
		}
		var doc manifestDoc
		if err := json.Unmarshal(raw, &doc); err != nil {
			continue
		}
		if doc.Version < 4 {
			legacy++
			continue
		}
		for _, entry := range doc.Entries {
			for _, h := range entry.Chunks {
				if checked[h] || len(h) < 4 {
					continue
				}
				checked[h] = true
				objPath := filepath.Join(repoDir, "objects", h[:2], h)
				info, statErr := os.Stat(objPath)
				if statErr != nil || info.IsDir() {
					shortH := h
					if len(shortH) > 16 {
						shortH = shortH[:16]
					}
					missing = append(missing, VerifyIssue{
						Snapshot: sid,
						Path:     entry.Path,
						Chunk:    shortH,
					})
					continue
				}
				if readData {
					blob, rErr := os.ReadFile(objPath)
					if rErr != nil {
						corrupt = append(corrupt, VerifyIssue{Snapshot: sid, Path: entry.Path, Chunk: h[:16], Error: rErr.Error()})
						continue
					}
					data, dErr := DecompressBlock(blob)
					if dErr != nil {
						if strings.Contains(dErr.Error(), "unsupported codec tag: S") || strings.Contains(dErr.Error(), "unsupported codec tag: L") {
							continue
						}
						corrupt = append(corrupt, VerifyIssue{Snapshot: sid, Path: entry.Path, Chunk: h[:16], Error: dErr.Error()})
						continue
					}
					if SHA256Hex(data) != h {
						corrupt = append(corrupt, VerifyIssue{Snapshot: sid, Path: entry.Path, Chunk: h[:16], Error: "hash mismatch"})
					}
				}
			}
		}
	}

	ok := len(missing) == 0 && len(corrupt) == 0
	summary := "Íntegro: todos os blocos presentes"
	if readData && ok {
		summary += " e conferidos"
	}
	if !ok {
		summary = fmt.Sprintf("%d bloco(s) ausente(s), %d corrompido(s)", len(missing), len(corrupt))
	}

	return VerifyReport{
		Success:         ok,
		Engine:          "gboc-go-core",
		Snapshots:       len(snaps),
		ChunksChecked:   len(checked),
		Missing:         missing,
		Corrupt:         corrupt,
		LegacySnapshots: legacy,
		ReadData:        readData,
		Summary:         summary,
	}
}

