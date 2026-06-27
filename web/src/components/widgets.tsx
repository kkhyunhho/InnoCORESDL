import { Plug, TriangleAlert } from "lucide-react"

import type { Conn } from "@/lib/types"

export function StatusPill({ label, state }: { label: string; state: Conn }) {
  const m = {
    ok: { cls: "text-status-ok", Icon: Plug, word: "ok" },
    fault: { cls: "text-status-fault", Icon: TriangleAlert, word: "fault" },
    idle: { cls: "text-status-idle", Icon: Plug, word: "—" },
  }[state]
  const { Icon } = m
  return (
    <span className={`inline-flex items-center gap-1 text-sm ${m.cls}`}>
      <Icon className="size-4" aria-hidden />
      <span className="font-medium">{label}</span>
      <span className="text-xs opacity-80">{m.word}</span>
    </span>
  )
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-lg tabular-nums">{value}</span>
    </div>
  )
}
