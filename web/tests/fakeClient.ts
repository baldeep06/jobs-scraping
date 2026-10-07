import type { SupabaseClient } from "@supabase/supabase-js";

type Result = { data?: unknown; count?: number | null; error?: { code?: string; message: string } | null };
export type Call = [string, ...unknown[]];

/** Minimal stand-in for supabase-js: records calls; resolves via `respond(calls, head)`. */
export function fakeClient(respond: (calls: Call[], head: boolean) => Result) {
  const log: Call[][] = [];
  const client = {
    from(table: string) {
      const calls: Call[] = [["from", table]];
      log.push(calls);
      let head = false;
      const builder: Record<string, unknown> = {};
      for (const m of ["in", "eq", "ilike", "gte", "not", "or", "order", "range", "limit"]) {
        builder[m] = (...args: unknown[]) => {
          calls.push([m, ...args]);
          return builder;
        };
      }
      builder.select = (cols: string, opts?: { head?: boolean }) => {
        head = Boolean(opts?.head);
        calls.push(["select", cols, opts]);
        return builder;
      };
      builder.then = (resolve: (r: Result) => unknown) =>
        Promise.resolve({ data: null, count: null, error: null, ...respond(calls, head) }).then(
          resolve,
        );
      return builder;
    },
  };
  return { client: client as unknown as SupabaseClient, log };
}
