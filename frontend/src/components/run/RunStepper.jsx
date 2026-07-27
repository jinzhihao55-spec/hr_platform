import { Check } from 'lucide-react';

const STAGES = ['数据录入', '人工确认', '报表预览', '完成发布'];

function currentStage(run) {
  const targets = run?.targets || [];
  if (targets.length > 0 && targets.every((target) => target.status === 'published')) {
    return STAGES.length;
  }
  if (targets.some((target) => target.status === 'published')) return 3;
  if (run?.status === 'ready') return 2;
  if (run?.status === 'needs_review') return 1;
  return 0;
}

export default function RunStepper({ run }) {
  const active = currentStage(run);

  return (
    <ol className="run-stepper" aria-label="报表处理进度">
      <span className="run-stepper-progress" style={{width: `${Math.max(0, (active / (STAGES.length - 1)) * 100)}%`}} />
      {STAGES.map((label, index) => {
        const complete = index < active;
        const current = index === active;
        return (
          <li
            key={label}
            className={`${complete ? 'complete' : ''} ${current ? 'current' : ''}`}
            aria-current={current ? 'step' : undefined}
          >
            <span className="step-marker">
              {complete ? <Check aria-hidden="true" size={14} strokeWidth={2.5} /> : index + 1}
            </span>
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
