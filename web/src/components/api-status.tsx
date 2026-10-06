import { connection } from "next/server";

import { apiServer } from "@/lib/api/server";

export async function ApiStatus() {
  await connection();
  let ready = false;
  try {
    const { response } = await apiServer().GET("/readyz");
    ready = response.ok;
  } catch {
    ready = false;
  }

  return (
    <p className="inline-flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${ready ? "bg-emerald-500" : "bg-red-500"}`}
      />
      API {ready ? "online" : "unreachable"}
    </p>
  );
}
