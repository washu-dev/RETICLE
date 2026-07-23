// Launches the FastAPI backend using the repo-local .venv interpreter.
// Used by the root "dev:api" / "setup:api" npm scripts. Spawning the venv
// python directly (instead of a shell string) avoids Windows cmd.exe quoting
// issues with the ".venv/..." path and works the same on macOS/Linux.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const isWin = process.platform === "win32";
const binDir = isWin ? "Scripts" : "bin";
const exe = isWin ? "python.exe" : "python";

// Look for the interpreter in the usual spots, in priority order: repo-root
// .venv (README default), then api/.venv and api/venv (where deps may already
// be installed). The first that exists wins.
const candidates = [
  join(repoRoot, ".venv", binDir, exe),
  join(repoRoot, "api", ".venv", binDir, exe),
  join(repoRoot, "api", "venv", binDir, exe),
];
const python = candidates.find((p) => existsSync(p));

if (!python) {
  console.error(`\n[api] venv interpreter not found. Looked in:`);
  candidates.forEach((p) => console.error(`[api]   ${p}`));
  console.error(`[api] Create one first:  py -3.11 -m venv .venv   (then run: npm run setup)\n`);
  process.exit(1);
}

const install = process.argv.includes("--install");
const args = install
  ? ["-m", "pip", "install", "-r", join("api", "requirements.txt")]
  : ["-m", "uvicorn", "main:app", "--reload", "--app-dir", "api", "--host", "127.0.0.1", "--port", "8000"];

const child = spawn(python, args, { cwd: repoRoot, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
child.on("error", (err) => {
  console.error(`[api] failed to launch: ${err.message}`);
  process.exit(1);
});
