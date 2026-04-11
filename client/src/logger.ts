/**
 * Small client-side logger with environment-controlled verbosity.
 *
 * Control via:
 *   VITE_LOG_LEVEL=debug|info|warn|error|silent
 */
type Level = "debug" | "info" | "warn" | "error" | "silent";

const LEVELS: Record<Exclude<Level, "silent">, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

function getLevel(): Level {
  const raw = (import.meta.env.VITE_LOG_LEVEL || "info").toLowerCase();
  if (raw === "silent") return "silent";
  if (raw === "debug" || raw === "info" || raw === "warn" || raw === "error") return raw;
  return "info";
}

function enabled(min: Exclude<Level, "silent">): boolean {
  const lvl = getLevel();
  if (lvl === "silent") return false;
  return LEVELS[min] >= LEVELS[lvl as Exclude<Level, "silent">];
}

export const log = {
  debug: (...args: any[]) => enabled("debug") && console.debug("[debug]", ...args),
  info: (...args: any[]) => enabled("info") && console.info("[info]", ...args),
  warn: (...args: any[]) => enabled("warn") && console.warn("[warn]", ...args),
  error: (...args: any[]) => enabled("error") && console.error("[error]", ...args),
};
