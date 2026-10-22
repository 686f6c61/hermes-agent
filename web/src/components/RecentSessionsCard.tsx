import { Clock, Database } from "lucide-react";
import { Link } from "react-router";
import type { SessionInfo } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { sourceLabel } from "@/pages/SessionsPage_sources";
import { Badge } from "@nous-research/ui/ui/components/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { useI18n } from "@/i18n";

/**
 * The Overview tab's recent-session list.
 *
 * Each card is a link to the same `?resume=` route the History tab's
 * "Resume in Chat" button uses: they read as tappable, so they have to open
 * their session instead of swallowing the click (#142835).
 */
export function RecentSessionsCard({ sessions }: { sessions: SessionInfo[] }) {
  const { t } = useI18n();

  return (
    <Card className="min-w-0 max-w-full overflow-hidden">
      <CardHeader className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <Clock className="h-5 w-5 shrink-0 text-muted-foreground" />
          <CardTitle className="min-w-0 truncate text-base">
            {t.status.recentSessions}
          </CardTitle>
        </div>
      </CardHeader>

      <CardContent className="grid min-w-0 gap-3">
        {sessions.map((s) => (
          <Link
            key={s.id}
            to={`/chat?resume=${encodeURIComponent(s.id)}`}
            className="flex min-w-0 max-w-full flex-col gap-2 border border-border p-3 transition-colors hover:border-foreground/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-current/40 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <span
                className={`font-mondwest normal-case min-w-0 truncate text-sm ${s.title ? "font-medium" : "text-muted-foreground italic"}`}
              >
                {s.title ??
                  (s.preview ? s.preview.slice(0, 60) : t.common.untitled)}
              </span>

              <span className="min-w-0 break-words text-xs text-muted-foreground">
                {s.model && (
                  <>
                    <span className="font-mono-ui">
                      {s.model.split("/").pop()}
                    </span>{" "}
                    ·{" "}
                  </>
                )}
                {s.message_count} {t.common.msgs} · {timeAgo(s.last_active)}
              </span>

              {s.preview && s.title && (
                <p className="font-mondwest normal-case min-w-0 max-w-full text-xs leading-snug text-text-tertiary [overflow-wrap:anywhere]">
                  {s.preview}
                </p>
              )}
            </div>

            <Badge
              tone="outline"
              className="shrink-0 self-start text-xs sm:self-center"
            >
              <Database className="mr-1 h-3 w-3" />
              {s.source ? sourceLabel(s.source) : "local"}
            </Badge>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}
