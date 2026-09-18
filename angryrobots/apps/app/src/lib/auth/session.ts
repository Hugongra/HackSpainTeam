import { queryOptions } from "@tanstack/react-query"

import { getSession } from "@/lib/auth/client"

export function sessionQueryOptions() {
  return queryOptions({
    queryKey: ["session"],
    queryFn: async () => {
      try {
        const { data } = await getSession()
        return data
      } catch {
        // Backend unreachable (e.g. static preview without an API): treat as
        // signed out so the app renders the sign-in flow instead of an error.
        return null
      }
    },
  })
}
