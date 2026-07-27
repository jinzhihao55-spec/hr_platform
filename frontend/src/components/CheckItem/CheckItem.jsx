import './CheckItem.css';

export default function CheckItem({ label, hard, passed = true }) {
  return (
    <div className="chk">
      <span className="b" style={passed ? undefined : { color: 'var(--err)' }}>
        {passed ? '✓' : '✗'}
      </span>
      {label}
      {hard && <span className="hard">★</span>}
    </div>
  );
}
