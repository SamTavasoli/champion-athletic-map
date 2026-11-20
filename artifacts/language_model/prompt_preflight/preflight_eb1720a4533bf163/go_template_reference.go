package main

import (
    "bytes"
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "fmt"
    "os"
    "runtime"
    "text/template"
)

type Fixture struct {
    CaseID string `json:"case_id"`
    System string `json:"system"`
    User string `json:"user"`
}

type Message struct {
    Role string
    Content string
}

type Values struct {
    System string
    Tools []string
    Messages []Message
}

type Result struct {
    CaseID string `json:"case_id"`
    System string `json:"system"`
    User string `json:"user"`
    Rendered string `json:"rendered"`
    RenderedSHA256 string `json:"rendered_sha256"`
}

func main() {
    if len(os.Args) != 3 { panic("expected template and fixture paths") }
    source, err := os.ReadFile(os.Args[1]); if err != nil { panic(err) }
    fixtureBytes, err := os.ReadFile(os.Args[2]); if err != nil { panic(err) }
    var fixtures []Fixture
    if err := json.Unmarshal(fixtureBytes, &fixtures); err != nil { panic(err) }
    parsed, err := template.New("recorded_ollama_template").Option("missingkey=error").Parse(string(source))
    if err != nil { panic(err) }
    results := make([]Result, 0, len(fixtures))
    for _, fixture := range fixtures {
        var output bytes.Buffer
        values := Values{System: fixture.System, Tools: nil, Messages: []Message{{Role: "user", Content: fixture.User}}}
        if err := parsed.Execute(&output, values); err != nil { panic(err) }
        digest := sha256.Sum256(output.Bytes())
        results = append(results, Result{fixture.CaseID, fixture.System, fixture.User, output.String(), hex.EncodeToString(digest[:])})
    }
    sourceDigest := sha256.Sum256(source)
    receipt := map[string]any{"schema_version": "step24-go-template-reference-capture-1", "go_version": runtime.Version(),
        "execution_scope": "Go_standard_library_text_template_only_no_Ollama_requests",
        "template_sha256": hex.EncodeToString(sourceDigest[:]), "cases": results}
    encoded, err := json.MarshalIndent(receipt, "", "  "); if err != nil { panic(err) }
    fmt.Println(string(encoded))
}
