import { createContext, useCallback, useContext, useRef, useState } from "react";

const ToastCtx = createContext(null);

let seq = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const toast = useCallback((msg, isErr) => {
    const id = ++seq;
    setToasts((t) => [...t, { id, msg, isErr: !!isErr }]);
    const timer = setTimeout(() => {
      setToasts((t) => t.filter((x) => x.id !== id));
      timers.current.delete(id);
    }, 3200);
    timers.current.set(id, timer);
  }, []);

  return (
    <ToastCtx.Provider value={toast}>
      {children}
      {toasts.map((t) => (
        <div key={t.id} className={"toast" + (t.isErr ? " err" : "")}>
          {t.msg}
        </div>
      ))}
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
