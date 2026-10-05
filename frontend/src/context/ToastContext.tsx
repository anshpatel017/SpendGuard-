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
    const id = `toast-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
    setToasts((prev) => {
      // Deduplication: remove existing toasts with identical message
      const withoutDup = prev.filter((t) => t.message !== message);
      // Limit stacking to prevent screen clutter
      const trimmed = withoutDup.slice(-2);
      return [...trimmed, { id, message, type }];
    });

    // Auto-dismiss after 4000ms (4 seconds)
    setTimeout(() => {
      dismissToast(id);
    }, 4000);
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
        let icon = <Info className="w-4 h-4 text-black shrink-0" />;

        if (toast.type === "success") {
          icon = <CheckCircle2 className="w-4 h-4 text-black shrink-0" />;
        } else if (toast.type === "warning") {
          icon = <AlertTriangle className="w-4 h-4 text-black shrink-0" />;
        } else if (toast.type === "danger" || toast.type === "error") {
          icon = <XCircle className="w-4 h-4 text-black shrink-0" />;
        }

        return (
          <div
            key={toast.id}
            className="pointer-events-auto flex items-center justify-between p-3.5 rounded-lg border border-black bg-white text-black shadow-md text-xs sm:text-sm font-semibold transition-all animate-in fade-in slide-in-from-bottom-2"
          >
            <div className="flex items-center gap-2.5">
              {icon}
              <span className="font-semibold text-xs sm:text-sm text-black">{toast.message}</span>
            </div>
            <button
              onClick={() => dismissToast(toast.id)}
              className="p-1 text-slate-400 hover:text-black transition-colors ml-2 cursor-pointer"
              aria-label="Close notification"
            >
              <X className="w-3.5 h-3.5 text-black" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
