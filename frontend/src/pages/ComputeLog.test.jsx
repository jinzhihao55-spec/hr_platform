import { describe, expect, it } from 'vitest';
import { mapChecks } from './computeLogMappers';

describe('published computation-log checks', () => {
  it('labels accepted review findings without showing them as failures', () => {
    expect(mapChecks({
      validations: [{
        check: '前三项目截止位并列',
        severity: 'REVIEW',
        passed: true,
        resolved_by_review: true,
      }],
    })).toEqual([{
      label: '前三项目截止位并列（已人工复核）',
      hard: false,
      passed: true,
    }]);
  });
});
