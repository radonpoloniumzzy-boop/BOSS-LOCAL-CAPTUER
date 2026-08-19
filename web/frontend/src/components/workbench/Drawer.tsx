import { PropsWithChildren, useEffect, useRef } from "react";

let drawerIdSeed = 0;
type DrawerEntry = {
  id: number;
  getPanel: () => HTMLElement | null;
  getLastFocused: () => HTMLElement | null;
  focusInside: (preferredTarget?: HTMLElement | null) => boolean;
  close: () => void;
};

let drawerStack: DrawerEntry[] = [];
let scrollLockCount = 0;
let previousBodyOverflow = "";
let listenerAttached = false;
let isRestoringFocus = false;
let queuedFocusRestore = 0;

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

function topDrawerEntry() {
  return drawerStack.reduce<DrawerEntry | null>(
    (currentTop, entry) => (!currentTop || entry.id > currentTop.id ? entry : currentTop),
    null,
  );
}

function pushDrawer(entry: DrawerEntry) {
  drawerStack = [...drawerStack, entry];
  ensureGlobalListener();
}

function removeDrawer(id: number) {
  drawerStack = drawerStack.filter((entry) => entry.id !== id);
  cleanupGlobalListener();
}

function getFocusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((element) => {
    if (!element.isConnected) return false;
    if (element.getAttribute("aria-hidden") === "true") return false;
    if (element.tabIndex < 0) return false;
    return true;
  });
}

function focusWithinEntry(entry: DrawerEntry, preferredTarget?: HTMLElement | null) {
  const panel = entry.getPanel();
  if (!panel) return false;

  const focusable = getFocusableElements(panel);
  const lastFocused = entry.getLastFocused();
  const target =
    (preferredTarget && preferredTarget.isConnected && panel.contains(preferredTarget) ? preferredTarget : null) ||
    (lastFocused && lastFocused.isConnected && panel.contains(lastFocused) ? lastFocused : null) ||
    focusable[0] ||
    panel;

  if (document.activeElement === target) return true;
  isRestoringFocus = true;
  try {
    target.focus();
  } finally {
    isRestoringFocus = false;
  }
  return document.activeElement === target;
}

function focusWithinTopDrawer(preferredTarget?: HTMLElement | null) {
  const topEntry = topDrawerEntry();
  if (!topEntry) return false;
  return topEntry.focusInside(preferredTarget);
}

function focusExternalTarget(target: HTMLElement | null) {
  if (!target || !target.isConnected) return false;
  isRestoringFocus = true;
  try {
    target.focus();
  } finally {
    isRestoringFocus = false;
  }
  return document.activeElement === target;
}

function scheduleFocusRestore(preferredTarget?: HTMLElement | null) {
  const topEntry = topDrawerEntry();
  if (!topEntry) {
    if (queuedFocusRestore) {
      window.cancelAnimationFrame(queuedFocusRestore);
      queuedFocusRestore = 0;
    }
    focusExternalTarget(preferredTarget ?? null);
    return;
  }

  if (queuedFocusRestore) {
    window.cancelAnimationFrame(queuedFocusRestore);
  }
  queuedFocusRestore = window.requestAnimationFrame(() => {
    queuedFocusRestore = 0;
    const currentTopEntry = topDrawerEntry();
    if (!currentTopEntry) {
      focusExternalTarget(preferredTarget ?? null);
      return;
    }

    const panel = currentTopEntry.getPanel();
    if (!panel) return;

    if (preferredTarget && preferredTarget.isConnected && panel.contains(preferredTarget)) {
      currentTopEntry.focusInside(preferredTarget);
      return;
    }

    currentTopEntry.focusInside();
  });
}

function lockBodyScroll() {
  if (scrollLockCount === 0) {
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  scrollLockCount += 1;
}

function unlockBodyScroll() {
  scrollLockCount = Math.max(0, scrollLockCount - 1);
  if (scrollLockCount === 0) {
    document.body.style.overflow = previousBodyOverflow;
  }
}

function handleDocumentKeyDown(event: KeyboardEvent) {
  const topEntry = topDrawerEntry();
  const panel = topEntry?.getPanel() ?? null;
  if (!topEntry || !panel) return;

  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    topEntry.close();
    return;
  }

  if (event.key !== "Tab") return;
  const focusable = getFocusableElements(panel);
  if (focusable.length === 0) {
    event.preventDefault();
    panel.focus();
    return;
  }

  const firstFocusable = focusable[0];
  const lastFocusable = focusable[focusable.length - 1];
  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;

  if (event.shiftKey) {
    if (activeElement === firstFocusable || activeElement === panel || !panel.contains(activeElement)) {
      event.preventDefault();
      lastFocusable.focus();
    }
    return;
  }

  if (activeElement === lastFocusable || activeElement === panel || !panel.contains(activeElement)) {
    event.preventDefault();
    firstFocusable.focus();
  }
}

function handleDocumentFocusIn(event: FocusEvent) {
  if (isRestoringFocus) return;
  const topEntry = topDrawerEntry();
  const panel = topEntry?.getPanel() ?? null;
  const target = event.target instanceof HTMLElement ? event.target : null;
  if (!topEntry || !panel || !target) return;
  if (panel.contains(target)) return;

  focusWithinTopDrawer();
}

function ensureGlobalListener() {
  if (listenerAttached) return;
  document.addEventListener("keydown", handleDocumentKeyDown);
  document.addEventListener("focusin", handleDocumentFocusIn);
  listenerAttached = true;
}

function cleanupGlobalListener() {
  if (!listenerAttached || drawerStack.length > 0) return;
  document.removeEventListener("keydown", handleDocumentKeyDown);
  document.removeEventListener("focusin", handleDocumentFocusIn);
  listenerAttached = false;
}

export function Drawer({
  label,
  className = "",
  onClose,
  children,
}: PropsWithChildren<{
  label: string;
  className?: string;
  onClose: () => void;
}>) {
  const drawerId = useRef<number | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const lastFocusedWithinRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  if (drawerId.current === null) {
    drawerId.current = ++drawerIdSeed;
  }

  onCloseRef.current = onClose;

  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return undefined;

    const handleFocusIn = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement) {
        lastFocusedWithinRef.current = event.target;
      }
    };

    panel.addEventListener("focusin", handleFocusIn);
    return () => {
      panel.removeEventListener("focusin", handleFocusIn);
    };
  }, []);

  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!activeElement || panel.contains(activeElement) || activeElement !== returnFocusRef.current) return;

    const focusTarget = lastFocusedWithinRef.current?.isConnected
      ? lastFocusedWithinRef.current
      : getFocusableElements(panel)[0] || panel;
    focusTarget.focus();
  });

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const currentDrawerId = drawerId.current!;
    pushDrawer({
      id: currentDrawerId,
      getPanel: () => panelRef.current,
      getLastFocused: () => lastFocusedWithinRef.current,
      focusInside: (preferredTarget?: HTMLElement | null) => focusWithinEntry({
        id: currentDrawerId,
        getPanel: () => panelRef.current,
        getLastFocused: () => lastFocusedWithinRef.current,
        focusInside: () => false,
        close: () => onCloseRef.current(),
      }, preferredTarget),
      close: () => onCloseRef.current(),
    });
    lockBodyScroll();
    const focusFrame = window.requestAnimationFrame(() => {
      focusWithinTopDrawer();
    });
    return () => {
      window.cancelAnimationFrame(focusFrame);
      removeDrawer(currentDrawerId);
      unlockBodyScroll();
      scheduleFocusRestore(returnFocusRef.current);
    };
  }, []);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        ref={panelRef}
        className={className}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </aside>
    </div>
  );
}
