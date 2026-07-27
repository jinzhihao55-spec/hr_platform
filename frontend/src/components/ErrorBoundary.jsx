import { Component } from 'react';
import { CircleAlert, RotateCcw } from 'lucide-react';
import './ErrorBoundary.css';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error('[UI Error Boundary]', error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="fatal-error" role="alert">
        <CircleAlert aria-hidden="true" size={28} />
        <h1>页面发生异常</h1>
        <p>当前操作未继续执行。刷新后可从运行日历重新进入。</p>
        <button type="button" onClick={() => window.location.reload()}>
          <RotateCcw aria-hidden="true" size={16} />刷新页面
        </button>
      </main>
    );
  }
}
