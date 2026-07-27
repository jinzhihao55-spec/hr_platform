import './TraceItem.css';

export default function TraceItem({ row, title, value, derive, open, fields }) {
  return (
    <details className={`trace${derive ? ' derive' : ''}`} open={open}>
      <summary>
        <span className="row">{row}</span>
        <span className="ti">{title}</span>
        <span className="tv">{value}</span>
      </summary>
      <div className="tbody">
        {fields.map((field, i) => (
          <div key={i}>
            <dt>{field.label}</dt>
            <dd className={[
              field.plain ? 'plain' : '',
              field.ok ? 'ok' : '',
            ].filter(Boolean).join(' ')}>
              {field.value}
            </dd>
          </div>
        ))}
      </div>
    </details>
  );
}
