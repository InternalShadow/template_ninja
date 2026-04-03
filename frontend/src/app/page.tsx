import Link from "next/link";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-16">
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Resume Style Builder
        </h1>
        <p className="max-w-lg text-lg text-zinc-600 dark:text-zinc-400">
          Upload a resume template PDF, extract its visual style, then generate
          a pixel-perfect resume from your own data.
        </p>
      </div>

      <Link
        href="/build/demo"
        className="rounded-full bg-foreground px-6 py-3 text-sm font-medium text-background transition-colors hover:bg-zinc-700 dark:hover:bg-zinc-300"
      >
        Try the Builder
      </Link>
    </main>
  );
}
