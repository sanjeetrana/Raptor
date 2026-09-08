package tests

import (
	"html"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/daniel-oluwadunsin/undolang/internal/cli"
	"github.com/daniel-oluwadunsin/undolang/internal/lang/frontend"
)

func repositoryRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	return root
}

func TestEveryExampleParses(t *testing.T) {
	files, err := filepath.Glob(filepath.Join(repositoryRoot(t), "examples", "*.undo"))
	if err != nil || len(files) == 0 {
		t.Fatalf("examples=%v err=%v", files, err)
	}
	for _, file := range files {
		t.Run(filepath.Base(file), func(t *testing.T) {
			source, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			if _, diagnostic := frontend.Parse(source); diagnostic != nil {
				t.Fatal(diagnostic)
			}
		})
	}
}

func TestPublicUndoLangSnippetsParse(t *testing.T) {
	root := repositoryRoot(t)
	markdownPattern := regexp.MustCompile("(?s)```undolang\\s*\\n(.*?)```")
	htmlPattern := regexp.MustCompile(`(?s)<code class="language-undolang">(.*?)</code>`)
	var snippets int
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() && (entry.Name() == ".git" || entry.Name() == "dist") {
			return filepath.SkipDir
		}
		if entry.IsDir() || (!strings.HasSuffix(path, ".md") && !strings.HasSuffix(path, ".html")) {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		matches := markdownPattern.FindAllSubmatch(data, -1)
		if strings.HasSuffix(path, ".html") {
			matches = htmlPattern.FindAllSubmatch(data, -1)
		}
		for index, match := range matches {
			snippets++
			source := html.UnescapeString(string(match[1]))
			if _, diagnostic := frontend.Parse([]byte(source)); diagnostic != nil {
				t.Errorf("%s snippet %d: %v", path, index+1, diagnostic)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if snippets < 3 {
		t.Fatalf("only %d parser-checked public snippets", snippets)
	}
}

func TestMarketingHasNoExternalRuntimeAssets(t *testing.T) {
	root := filepath.Join(repositoryRoot(t), "marketing")
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		lower := strings.ToLower(string(data))
		for _, forbidden := range []string{"fonts.googleapis.com", "cdn.", "<script src=\"http", "<link rel=\"stylesheet\" href=\"http"} {
			if strings.Contains(lower, forbidden) {
				t.Errorf("%s contains external runtime marker %q", path, forbidden)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"package.json", "package-lock.json", "yarn.lock"} {
		if _, err := os.Stat(filepath.Join(root, forbidden)); !os.IsNotExist(err) {
			t.Errorf("forbidden marketing dependency file exists: %s", forbidden)
		}
	}
}

func TestMarketingLocalLinksResolve(t *testing.T) {
	root := filepath.Join(repositoryRoot(t), "marketing")
	references := regexp.MustCompile(`(?:href|src)="([^"]+)"`)
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil || entry.IsDir() || filepath.Ext(path) != ".html" {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		for _, match := range references.FindAllSubmatch(data, -1) {
			reference := string(match[1])
			if reference == "" || strings.HasPrefix(reference, "#") || strings.Contains(reference, "://") {
				continue
			}
			reference = strings.SplitN(reference, "#", 2)[0]
			if _, err := os.Stat(filepath.Join(filepath.Dir(path), filepath.FromSlash(reference))); err != nil {
				t.Errorf("%s references missing local asset %q: %v", path, reference, err)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestDocumentedCommandsExposeHelp(t *testing.T) {
	commands := []string{"check", "plan", "run", "recover", "history", "inspect", "version", "capabilities", "schema", "agent-guide"}
	for _, command := range commands {
		if code := (cli.App{Stdout: io.Discard, Stderr: io.Discard}).Run([]string{command, "--help"}); code != 0 {
			t.Errorf("%s --help exit %d", command, code)
		}
	}
}
