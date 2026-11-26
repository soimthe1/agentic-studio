import { useTranslation } from "react-i18next";

export function Loading() {
  const { t } = useTranslation();
  return <p className="empty" role="status">{t("loading")}</p>;
}

export function Failed({ message, retry }: { message: string; retry: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="empty" role="alert">
      <p className="error">{message}</p>
      <button className="btn" onClick={retry}>{t("retry")}</button>
    </div>
  );
}

export function Empty({ title, text, children }: { title: string; text: string; children?: React.ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      <p>{text}</p>
      {children}
    </div>
  );
}
