import { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";

export type ToastType = "success" | "warning" | "danger" | "error" | "info";

export interface ToastItem {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  toasts: ToastItem[];
  showToast: (message: string, type?: ToastType) => void;
  dismissToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback((message: string, type: ToastType = "success") => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
    setToasts((prev) => [...prev, { id, message, type }]);

    setTimeout(() => {
      dismissToast(id);
    }, 4500);
  }, [dismissToast]);

  return (
    <ToastContext.Provider value={{ toasts, showToast, dismissToast }}>
      {children}
      <ToastContainer toasts={toasts} dismissToast={dismissToast} />
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // fallback if used outside provider
    return {
      toasts: [],
      showToast: (msg: string) => console.log(msg),
      dismissToast: () => {},
    };
  }
  return ctx;
}

function ToastContainer({
  toasts,
  dismissToast,
}: {
  toasts: ToastItem[];
  dismissToast: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-md w-full pointer-events-none">
      {toasts.map((toast) => {
        let borderClass = "border-slate-800 bg-white text-slate-900 shadow-lg";
        let icon = <Info className="w-4 h-4 text-sky-600 shrink-0" />;

        if (toast.type === "success") {
          borderClass = "border-emerald-600 bg-white text-slate-900 shadow-lg";
          icon = <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />;
        } else if (toast.type === "warning") {
          borderClass = "border-amber-600 bg-white text-slate-900 shadow-lg";
          icon = <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />;
        } else if (toast.type === "danger" || toast.type === "error") {
          borderClass = "border-red-600 bg-white text-slate-900 shadow-lg";
          icon = <XCircle className="w-4 h-4 text-red-600 shrink-0" />;
        }

        return (
          <div
            key={toast.id}
            className={`pointer-events-auto flex items-center justify-between p-3.5 rounded-xl border text-sm transition-all animate-in fade-in slide-in-from-bottom-2 ${borderClass}`}
          >
            <div className="flex items-center gap-2.5">
              {icon}
              <span className="font-semibold text-xs sm:text-sm text-slate-900">{toast.message}</span>
            </div>
            <button
              onClick={() => dismissToast(toast.id)}
              className="p-1 text-slate-400 hover:text-slate-900 transition-colors ml-2"
              aria-label="Close notification"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
