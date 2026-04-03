"use client";

import { useState, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface TestResult {
  name: string;
  method: string;
  path: string;
  status: number | null;
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
    const contentType = resp.headers.get("content-type") || "";

    let bodyPreview: string;
    if (contentType.includes("json")) {
      const json = await resp.json();
      bodyPreview = JSON.stringify(json).slice(0, 300);
    } else if (contentType.includes("image/png")) {
      const blob = await resp.blob();
      bodyPreview = `PNG image (${blob.size} bytes)`;
    } else if (contentType.includes("application/pdf")) {
      const blob = await resp.blob();
      bodyPreview = `PDF file (${blob.size} bytes)`;
    } else {
      bodyPreview = (await resp.text()).slice(0, 300);
    }

    // If the browser could read the cross-origin response, CORS is working.
    // Browsers block the response entirely (throwing a TypeError) when CORS
    // headers are missing — so reaching this point IS the proof.
    return {
      name,
      method,
      path,
      status: resp.status,
      contentType,
      bodyPreview,
      pass: resp.ok,
      error: resp.ok ? null : `HTTP ${resp.status}`,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const isCors = msg.includes("Failed to fetch") || msg.includes("NetworkError");
    return {
      name,
      method,
      path,
      status: null,
      contentType: null,
      bodyPreview: "",
      pass: false,
      error: isCors ? `CORS BLOCKED — ${msg}` : msg,
    };
  }
}

async function fetchTemplateId(): Promise<string | null> {
  try {
    const resp = await fetch(`${API_BASE}/templates`);
    const data = await resp.json();
    if (Array.isArray(data) && data.length > 0) return data[0].id;
  } catch { /* no-op */ }
  return null;
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
    push(await runTest("List templates", "GET", "/templates"));

    // Get a usable template ID via a clean fetch (not from bodyPreview)
    const templateId = await fetchTemplateId();

    if (!templateId) {
      push({
        name: "SKIPPED (no template)",
        method: "-",
        path: "-",
        status: null,
        contentType: null,
        bodyPreview: "No template in the store. Upload a PDF via POST /templates first.",
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
        Each test makes a cross-origin fetch from this page. If the browser can read the response, CORS
        is working. A CORS failure surfaces as a &quot;Failed to fetch&quot; TypeError.
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
                  <div className="col-span-2 truncate">Body: <span className="font-mono">{r.bodyPreview || "—"}</span></div>
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
