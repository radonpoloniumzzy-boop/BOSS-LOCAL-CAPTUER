import { PropsWithChildren, useEffect, useRef } from "react";

let drawerIdSeed = 0;
type DrawerEntry = {
  id: number;
  getPanel: () => HTMLElement | null;
  close: () => void;
};

let drawerStack: DrawerEntry[] = [];
let scrollLockCount = 0;
let previousBodyOverflow = "";
let listenerAttached = false;

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

function ensureGlobalListener() {
  if (listenerAttached) return;
  document.addEventListener("keydown", handleDocumentKeyDown);
  listenerAttached = true;
}

function cleanupGlobalListener() {
  if (!listenerAttached || drawerStack.length > 0) return;
  document.removeEventListener("keydown", handleDocumentKeyDown);
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
  const drawerId = useRef(++drawerIdSeed);
  const panelRef = useRef<HTMLElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const lastFocusedWithinRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

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
    pushDrawer({
      id: drawerId.current,
      getPanel: () => panelRef.current,
      close: () => onCloseRef.current(),
    });
    lockBodyScroll();
    const focusFrame = window.requestAnimationFrame(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const [firstFocusable] = getFocusableElements(panel);
      (firstFocusable || panel).focus();
    });
    return () => {
      window.cancelAnimationFrame(focusFrame);
      removeDrawer(drawerId.current);
      unlockBodyScroll();
      const target = returnFocusRef.current;
      if (target && target.isConnected) {
        window.requestAnimationFrame(() => {
          if (target.isConnected) {
            target.focus();
          }
        });
      }
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
