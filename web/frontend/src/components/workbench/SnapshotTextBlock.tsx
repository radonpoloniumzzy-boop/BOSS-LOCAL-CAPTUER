import { useEffect, useState } from "react";

type CopyState = "idle" | "success" | "error";

export function SnapshotTextBlock({
  text,
  emptyText = "未保存原始快照",
  collapsible = false,
  previewLines = 8,
}: {
  text: string;
  emptyText?: string;
  collapsible?: boolean;
  previewLines?: number;
}) {
  const content = text || "";
  const hasContent = content.trim().length > 0;
  const [expanded, setExpanded] = useState(false);
  const [copyState, setCopyState] = useState<CopyState>("idle");

  useEffect(() => {
    if (copyState === "idle") return undefined;
    const timer = window.setTimeout(() => setCopyState("idle"), 1800);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  useEffect(() => {
    setExpanded(false);
    setCopyState("idle");
  }, [text]);

  const copySnapshot = async () => {
    if (!hasContent) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopyState("success");
    } catch {
      setCopyState("error");
    }
  };

  return (
    <div className="snapshot-reader">
      <div className="snapshot-reader-actions">
        {collapsible && hasContent && (
          <button className="secondary-button" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "收起" : "展开完整快照"}
          </button>
        )}
        <button className="secondary-button" onClick={() => void copySnapshot()} disabled={!hasContent}>
          复制快照
        </button>
        {copyState === "success" && <span className="inline-feedback" role="status">已复制快照。</span>}
        {copyState === "error" && <span className="inline-feedback" role="status">复制失败，请稍后重试。</span>}
      </div>
      <div
        className={expanded || !collapsible ? "snapshot-text expanded" : "snapshot-text"}
        style={collapsible && !expanded ? { ["--preview-lines" as string]: String(previewLines) } : undefined}
      >
        <pre>{hasContent ? content : emptyText}</pre>
      </div>
    </div>
  );
}
