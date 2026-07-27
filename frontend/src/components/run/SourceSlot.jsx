import { CheckCircle2, FileWarning, LoaderCircle, Upload } from 'lucide-react';

export default function SourceSlot({
  definition,
  source,
  reviewResolved,
  error,
  uploading,
  locked,
  onUpload,
}) {
  const inputId = `source-${definition.type}`;

  const handleChange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    await onUpload(definition.type, file);
    event.target.value = '';
  };

  return (
    <article
      className={`source-slot ${source ? 'ready' : ''} ${error ? 'has-error' : ''}`}
      onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('drag-over'); }}
      onDragLeave={(e) => { e.preventDefault(); e.currentTarget.classList.remove('drag-over'); }}
      onDrop={async (e) => {
        e.preventDefault(); e.currentTarget.classList.remove('drag-over');
        const file = e.dataTransfer.files?.[0];
        if (file) await onUpload(definition.type, file);
      }}>
      <div className="source-slot-heading">
        <span className="source-icon"><definition.icon aria-hidden="true" size={18} /></span>
        <div>
          <h3>{definition.label}</h3>
          <p>{definition.description}</p>
        </div>
        {source && <CheckCircle2 className="source-ready-icon" aria-label="已上传" size={18} />}
      </div>

      <div className="source-slot-body">
        {source ? (
          <div className="source-metadata">
            <span>{source.row_count} 行</span>
            <span>{source.original_extension || '已解析'}</span>
            {source.original_filename && <span title={source.original_filename}>{source.original_filename.length > 20 ? source.original_filename.slice(0, 20) + '…' : source.original_filename}</span>}
            <span>
              {source.parse_status === 'needs_review'
                ? (reviewResolved ? '识别已确认' : '需要确认')
                : '解析完成'}
            </span>
          </div>
        ) : (
          <span className="source-empty">尚未上传</span>
        )}

        <input
          id={inputId}
          className="source-file-input"
          type="file"
          aria-label={definition.label}
          accept={definition.accept}
          disabled={locked || uploading}
          onChange={handleChange}
        />
        <label
          className={`source-upload-button ${locked || uploading ? 'disabled' : ''}`}
          htmlFor={inputId}
          title={locked ? '该运行已冻结输入' : undefined}
        >
          {uploading ? (
            <LoaderCircle className="spin" aria-hidden="true" size={15} />
          ) : (
            <Upload aria-hidden="true" size={15} />
          )}
          {uploading ? '正在处理' : source ? '替换文件' : '选择文件'}
        </label>
      </div>

      <div className="source-format">{definition.formatHint}</div>
      {error && (
        <div className="source-error" role="alert">
          <FileWarning aria-hidden="true" size={15} />
          <span>{error}</span>
        </div>
      )}
    </article>
  );
}
