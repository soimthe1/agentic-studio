import { useTranslation } from "react-i18next";
import { api, when } from "../api";
import { Icon } from "../components/Icon";
import { Empty, Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { Topbar } from "../components/Topbar";

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Everything your agents produced for you: data files, documents, archives, downloaded pages. */
export function Files() {
  const { t, i18n } = useTranslation();
  const list = useLoad(api.files);

  async function remove(name: string) {
    if (!window.confirm(t("files.confirmDelete", { name }))) return;
    await api.deleteFile(name);
    list.reload();
  }

  return (
    <>
      <Topbar title={<>{t("files.title")}</>} subtitle={t("files.intro")}>
        <label className="btn primary">
          {t("files.add")}
          <input type="file" hidden onChange={async (e) => {
            const f = e.target.files?.[0]; e.target.value = "";
            if (!f) return;
            try { await api.uploadFile(f); list.reload(); } catch (err) { alert((err as Error).message); }
          }} />
        </label>
        <button className="btn ghost" onClick={list.reload}>{t("appr.refresh")}</button>
      </Topbar>
      <section className="card list-card">
        {list.loading && <Loading />}
        {list.error && <Failed message={list.error} retry={list.reload} />}
        {list.data && list.data.length === 0 && <Empty title={t("files.emptyTitle")} text={t("files.emptyText")} />}
        <div className="list">
          {(list.data ?? []).map((f) => (
            <div className="row" key={f.name}>
              <span className="chip"><Icon name="database" /></span>
              <span className="txt">
                <b>{f.name}</b>
                <small>{f.format.toUpperCase()} · {size(f.bytes)}</small>
              </span>
              <span className="meta">{when(f.modified_at, i18n.language)}</span>
              <a className="btn" href={api.fileUrl(f.name)} download>{t("files.download")}</a>
              <button className="btn ghost" onClick={() => remove(f.name)}>{t("files.delete")}</button>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
