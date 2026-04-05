import { type ToastType } from '../store';
import { X } from 'lucide-react';

interface Props {
  toasts: { id: number; message: string; type: ToastType }[];
  onRemove: (id: number) => void;
}

export default function ToastContainer({ toasts, onRemove }: Props) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast toast-${t.type}`}>
          <span>{t.message}</span>
          <button className="toast-close" onClick={() => onRemove(t.id)}>
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
