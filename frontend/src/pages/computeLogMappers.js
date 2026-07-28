export function mapChecks(viewData) {
  return (viewData?.checks || viewData?.validations || []).map((check) => {
    const label = typeof check === 'string'
      ? check
      : check.message || check.name || check.label || check.check;
    return {
      label: typeof check === 'object' && check.resolved_by_review
        ? `${label}（已人工复核）`
        : label,
      hard: typeof check === 'object'
        ? check.hard_block || check.hard || false
        : false,
      passed: typeof check === 'object' ? (check.passed ?? true) : true,
    };
  });
}
