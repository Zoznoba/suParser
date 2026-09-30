import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { RealtimeEvent } from "../api/types";
import { handleEvent } from "./handleEvent";
import { attachViewingSender } from "./viewing";

const PING_INTERVAL = 25_000;
const MAX_BACKOFF = 30_000;

/** Держит WebSocket к /api/ws с авто-реконнектом. Возвращает, подключены ли сейчас. */
export function useRealtime(): boolean {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`;
    let ws: WebSocket | undefined;
    let attempt = 0;
    let stopped = false;
    let pingTimer: ReturnType<typeof setInterval> | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      ws = new WebSocket(url);
      ws.onopen = () => {
        // пока были офлайн, могли пропустить события — перечитываем всё
        if (attempt > 0) qc.invalidateQueries();
        attempt = 0;
        setConnected(true);
        pingTimer = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), PING_INTERVAL);
        // какие анкеты открыты — сервер забыл их вместе со старым соединением, напоминаем
        const socket = ws;
        attachViewingSender((ids) => {
          if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "view", candidate_ids: ids }));
        });
      };
      ws.onmessage = (e) => {
        if (e.data !== "pong") handleEvent(qc, JSON.parse(e.data) as RealtimeEvent);
      };
      ws.onclose = () => {
        attachViewingSender(null);
        setConnected(false);
        clearInterval(pingTimer);
        if (!stopped) reconnectTimer = setTimeout(connect, Math.min(MAX_BACKOFF, 1000 * 2 ** attempt++));
      };
    };

    connect();
    return () => {
      stopped = true;
      clearInterval(pingTimer);
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [qc]);

  return connected;
}
