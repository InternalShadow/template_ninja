"use client";

import { useState, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface TestResult {
  name: string;
  method: string;
  path: string;
  status: number | null;
  corsOrigin: string | null;
  contentType: string | null;
  bodyPreview: string;
  pass: boolean;
  error: string | null;
}

const SAMPLE_CONTENT = {
  name: "John Doe",
  title: "Software Engineer",
  summary: "Experienced software engineer.",
  contact: {
    email: "john@example.com",
    phone: "555-0100",
    location: "New York, NY",
  },
  skills: [{ category: "Languages", items: ["Python", "TypeScript"] }],
  experience: [
    {
      company: "Acme Corp",
      title: "Engineer",
      dates: "2022-2024",
      bullets: ["Built things", "Fixed things"],
    },
  ],
  education: [
    {
      degree: "BS Computer Science",
      school: "MIT",
      dates: "2018-2022",
    },
  ],
  projects: [],
};

async function runTest(
  name: string,
  method: string,
  path: string,
  options?: RequestInit
): Promise<TestResult> {
  const url = `${API_BASE}${path}`;
  try {
    const resp = await fetch(url, { method, ...options });
    const corsOrigin = resp.headers.get("access-control-allow-origin");
    const contentType = resp.headers.get("content-type") || "";

    let bodyPreview: string;
    if (contentType.includes("json")) {
      const json = await resp.json();
      bodyPreview = JSON.stringify(json).slice(0, 200);
    } else if (contentType.includes("image/png")) {
      const blob = await resp.blob();
      bodyPreview = `PNG image (${blob.size} bytes)`;
    } else if (contentType.includes("application/pdf")) {
      const blob = await resp.blob();
      bodyPreview = `PDF file (${blob.size} bytes)`;
    } else {
      bodyPreview = (await resp.text()).slice(0, 200);
    }

    return {
      name,
      method,
      path,
      status: resp.status,
      corsOrigin,
      contentType,
      bodyPreview,
      pass: resp.ok && corsOrigin !== null,
      error: null,
    };
  } catch (err) {
    return {
      name,
      method,
      path,
      status: null,
      corsOrigin: null,
      contentType: null,
      bodyPreview: "",
      pass: false,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

export default function SmokeTestPage() {
  const [results, setResults] = useState<TestResult[]>([]);
  const [running, setRunning] = useState(false);

  const runAll = useCallback(async () => {
    setRunning(true);
    setResults([]);
    const all: TestResult[] = [];

    const push = (r: TestResult) => {
      all.push(r);
      setResults([...all]);
    };

    // 1. GET /health
    push(await runTest("Health check", "GET", "/health"));

    // 2. GET /templates
    const listResult = await runTest("List templates", "GET", "/templates");
    push(listResult);

    let templateId: string | null = null;
    if (listResult.status === 200) {
      try {
        const parsed = JSON.parse(listResult.bodyPreview.length < 200 ? listResult.bodyPreview : "[]");
        if (Array.isArray(parsed) && parsed.length > 0) {
          templateId = parsed[0].id;
        }
      } catch {
        // re-fetch to get the actual data
        const resp = await fetch(`${API_BASE}/templates`);
        const data = await resp.json();
        if (data.length > 0) templateId = data[0].id;
      }
    }

    if (!templateId) {
      // Upload a test template using a minimal PDF
      const minimalPdf = new Uint8Array([
        0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x30, 0x0a, 0x31, 0x20,
        0x30, 0x20, 0x6f, 0x62, 0x6a, 0x3c, 0x3c, 0x2f, 0x54, 0x79, 0x70,
        0x65, 0x2f, 0x43, 0x61, 0x74, 0x61, 0x6c, 0x6f, 0x67, 0x2f, 0x50,
        0x61, 0x67, 0x65, 0x73, 0x20, 0x32, 0x20, 0x30, 0x20, 0x52, 0x3e,
        0x3e, 0x65, 0x6e, 0x64, 0x6f, 0x62, 0x6a, 0x0a,
      ]);
      const formData = new FormData();
      formData.append("file", new Blob([minimalPdf], { type: "application/pdf" }), "test.pdf");
      formData.append("name", "CORS Smoke Test");

      const uploadResult = await runTest("Upload template", "POST", "/templates", {
        body: formData,
      });
      push(uploadResult);

      if (uploadResult.status === 201) {
        try {
          const parsed = JSON.parse(uploadResult.bodyPreview);
          templateId = parsed.id;
        } catch { /* no-op */ }
      }
    }

    if (!templateId) {
      push({
        name: "SKIPPED (no template)",
        method: "-",
        path: "-",
        status: null,
        corsOrigin: null,
        contentType: null,
        bodyPreview: "No template available. Upload a PDF first.",
        pass: false,
        error: "No template ID available",
      });
      setRunning(false);
      return;
    }

    // 3. GET /templates/:id
    push(await runTest("Get template detail", "GET", `/templates/${templateId}`));

    // 4. GET /templates/:id/image
    push(await runTest("Get template image (PNG)", "GET", `/templates/${templateId}/image`));

    // 5. GET /blueprints/:id
    push(await runTest("Get blueprint", "GET", `/blueprints/${templateId}`));

    // 6. PUT /blueprints/:id
    push(
      await runTest("Update blueprint (PUT)", "PUT", `/blueprints/${templateId}`, {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ line_spacing: 1.2 }),
      })
    );

    // 7. POST /generate/:id
    push(
      await runTest("Generate PDF", "POST", `/generate/${templateId}`, {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(SAMPLE_CONTENT),
      })
    );

    // 8. POST /preview/:id
    push(
      await runTest("Generate preview (PNG)", "POST", `/preview/${templateId}`, {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(SAMPLE_CONTENT),
      })
    );

    // 9. POST /blueprints/:id/extract
    push(await runTest("Re-extract blueprint", "POST", `/blueprints/${templateId}/extract`));

    setRunning(false);
  }, []);

  const passed = results.filter((r) => r.pass).length;
  const failed = results.filter((r) => !r.pass).length;

  return (
    <main className="max-w-4xl mx-auto px-6 py-10">
      <h1 className="text-3xl font-bold mb-2">CORS Integration Smoke Test</h1>
      <p className="text-zinc-500 mb-1">
        Origin: <code className="text-sm bg-zinc-100 dark:bg-zinc-800 px-1 rounded">http://localhost:3000</code>
        {" → "}
        Backend: <code className="text-sm bg-zinc-100 dark:bg-zinc-800 px-1 rounded">{API_BASE}</code>
      </p>
      <p className="text-zinc-500 mb-6 text-sm">
        Tests every API endpoint from the browser to verify CORS is configured correctly.
      </p>

      <button
        onClick={runAll}
        disabled={running}
        className="mb-8 rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {running ? "Running..." : "Run All Tests"}
      </button>

      {results.length > 0 && (
        <>
          <div className="mb-4 flex gap-4 text-sm font-medium">
            <span className="text-green-600">{passed} passed</span>
            {failed > 0 && <span className="text-red-600">{failed} failed</span>}
          </div>

          <div className="space-y-3">
            {results.map((r, i) => (
              <div
                key={i}
                className={`rounded-lg border p-4 ${
                  r.pass
                    ? "border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950"
                    : "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950"
                }`}
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-lg">{r.pass ? "✓" : "✗"}</span>
                  <span className="font-semibold">{r.name}</span>
                  <code className="text-xs bg-zinc-200 dark:bg-zinc-700 px-1.5 py-0.5 rounded">
                    {r.method} {r.path}
                  </code>
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-zinc-600 dark:text-zinc-400 ml-8">
                  <div>Status: <span className="font-mono">{r.status ?? "—"}</span></div>
                  <div>Content-Type: <span className="font-mono">{r.contentType ?? "—"}</span></div>
                  <div>
                    CORS Origin:{" "}
                    <span className={`font-mono ${r.corsOrigin ? "text-green-600" : "text-red-600"}`}>
                      {r.corsOrigin ?? "MISSING"}
                    </span>
                  </div>
                  <div className="truncate">Body: <span className="font-mono">{r.bodyPreview || "—"}</span></div>
                  {r.error && (
                    <div className="col-span-2 text-red-600 font-mono">{r.error}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
