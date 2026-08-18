import { PropsWithChildren, useEffect, useRef } from "react";

let drawerIdSeed = 0;
let drawerStack: number[] = [];
let scrollLockCount = 0;
let previousBodyOverflow = "";

function pushDrawer(id: number) {
  drawerStack = [...drawerStack, id];
}

function removeDrawer(id: number) {
  drawerStack = drawerStack.filter((value) => value !== id);
}

function isTopDrawer(id: number) {
  return drawerStack.at(-1) === id;
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

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    pushDrawer(drawerId.current);
    lockBodyScroll();
    const focusFrame = window.requestAnimationFrame(() => {
      panelRef.current?.focus();
    });
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (!isTopDrawer(drawerId.current)) return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleKeyDown);
      removeDrawer(drawerId.current);
      unlockBodyScroll();
      const target = returnFocusRef.current;
      if (target && target.isConnected) target.focus();
    };
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        ref={panelRef}
        className={className}
        role="complementary"
        aria-label={label}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </aside>
    </div>
  );
}
