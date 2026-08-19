import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";

export type Loadable<T> = {
  rows: T[];
  total: number;
  page: number;
  page_size: number;
  loading: boolean;
  error: string;
};

export function formatDate(value: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export function StatusBadge({ tone = "neutral", children }: { tone?: string; children: React.ReactNode }) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}

export function RatingBadge({ rating }: { rating?: string | null }) {
  const normalized = String(rating || "").trim().toUpperCase();
  if (!["UR", "SSR", "SR", "R", "N"].includes(normalized)) {
    return <span className="rating-badge unrated">未评级</span>;
  }
  return <span className={`rating-badge rating-${normalized.toLowerCase()}`}>1{normalized}</span>;
}

export function TableState({ loading, error, empty, emptyText = "还没有采集批次。" }: { loading: boolean; error: string; empty: boolean; emptyText?: string }) {
  if (loading) return <div className="table-state skeleton-state"><span />正在读取本地数据…</div>;
  if (error) return <div className="table-state error-table-state">{error}</div>;
  if (empty) return <div className="table-state">{emptyText}</div>;
  return null;
}

export function RefreshButton({ onClick, label = "刷新" }: { onClick: () => void; label?: string }) {
  return <button className="icon-button" onClick={onClick} aria-label={label} title={label}><RefreshCw size={16} /></button>;
}

export function Pager({ page, pageSize, total, onPrevious, onNext }: { page: number; pageSize: number; total: number; onPrevious: () => void; onNext: () => void }) {
  const maxPage = Math.max(1, Math.ceil(total / Math.max(pageSize, 1)));
  return <div className="pager">
    <button className="icon-button" onClick={onPrevious} disabled={page <= 1} aria-label="上一页"><ChevronLeft size={16} /></button>
    <span>第 {page} / {maxPage} 页</span><small>共 {total} 条</small>
    <button className="icon-button" onClick={onNext} disabled={page >= maxPage} aria-label="下一页"><ChevronRight size={16} /></button>
  </div>;
}
