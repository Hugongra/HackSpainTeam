import { drizzle } from "drizzle-orm/node-postgres"

import { env } from "@workspace/db/lib/env"
import { relations } from "@workspace/db/schema/relations"

export const db = drizzle(env.DATABASE_URL, { relations })
