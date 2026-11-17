// ==============================================================================
// GBOC System v15.0.0 Enterprise Edition — Go Canonical CSS/JS Sync Engine
// Copyright (c) 2026 Master11BR - Todos os direitos reservados.
// ==============================================================================

package syncer

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
)

type SyncResult struct {
	Target        string   `json:"target"`
	Diverged      int      `json:"diverged"`
	Missing       int      `json:"missing"`
	Copied        int      `json:"copied"`
	UpdatedFiles  []string `json:"updated_files"`
}

var CanonicalFiles = []string{
	"style.css",
	"gboc-layout.css",
	"gboc-themes.css",
	"gboc-hardware-hud.css",
	"gboc-file-picker.css",
	"gboc-fernly.css",
	"gboc-perf.js",
	"gboc-modal.js",
	"gboc-layout-manager.js",
	"gboc-hardware-hud.js",
	"gboc-motion.js",
	"gboc-fernly.js",
	"ui/react/gboc-react-core.js",
	"ui/react/gboc-react-components.js",
	"ui/react/gboc-react.css",
}

func FileSHA256(path string) (string, []byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", nil, err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), data, nil
}

func SyncTarget(sharedDir, targetDir, targetName string, verifyOnly bool) SyncResult {
	res := SyncResult{Target: targetName, UpdatedFiles: []string{}}
	for _, rel := range CanonicalFiles {
		src := filepath.Join(sharedDir, filepath.FromSlash(rel))
		dst := filepath.Join(targetDir, filepath.FromSlash(rel))
		_, srcBytes, err := FileSHA256(src)
		if err != nil {
			continue
		}
		_, dstBytes, dstErr := FileSHA256(dst)
		if dstErr != nil {
			res.Missing++
			if !verifyOnly {
				_ = os.MkdirAll(filepath.Dir(dst), 0755)
				if wErr := copyBytesAtomic(dst, srcBytes); wErr == nil {
					res.Copied++
					res.UpdatedFiles = append(res.UpdatedFiles, rel)
				}
			}
			continue
		}
		if !bytes.Equal(srcBytes, dstBytes) {
			res.Diverged++
			if !verifyOnly {
				if wErr := copyBytesAtomic(dst, srcBytes); wErr == nil {
					res.Copied++
					res.UpdatedFiles = append(res.UpdatedFiles, rel)
				}
			}
		}
	}
	return res
}

func copyBytesAtomic(dst string, data []byte) error {
	f, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(f, bytes.NewReader(data))
	return err
}

