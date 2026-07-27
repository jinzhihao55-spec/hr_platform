import { useState } from 'react';
import { downloadReport } from '../../services';
import './ArchiveFold.css';

export default function ArchiveFold({ entry }) {
  const tagClass = (tag) => (tag === '日报' ? 'd' : 'w');
  const [downloading, setDownloading] = useState(null);

  const handleDownload = async (e, file) => {
    e.preventDefault();
    if (!file.downloadPath || downloading) return;
    setDownloading(file.name);
    try {
      const blob = await downloadReport(file.downloadPath);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = file.name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert('下载失败：' + err.message);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <details className="fold" open={entry.open}>
      <summary>
        📁 {entry.date}
        {entry.tags.map((t) => (
          <span className={`tag ${tagClass(t)}`} key={t}>
            {t}
          </span>
        ))}
        <span className="path right">{entry.path}</span>
      </summary>
      {entry.files.map((file, i) => (
        <div className="file" key={i}>
          <span className="ic">{file.icon}</span>
          {file.name}
          <span className="sz">{file.size}</span>
          <a href="#" onClick={(e) => handleDownload(e, file)}>
            {downloading === file.name ? '下载中…' : '下载'}
          </a>
        </div>
      ))}
    </details>
  );
}
