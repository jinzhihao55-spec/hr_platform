import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SourceUploadGrid from './SourceUploadGrid';

describe('SourceUploadGrid', () => {
  it('shows confirmed OCR state after the matching review is answered', () => {
    render(
      <SourceUploadGrid
        sources={[{
          source_type: 'release',
          row_count: 4,
          original_extension: '.png',
          parse_status: 'needs_review',
        }]}
        decisions={[{
          fact_ref: 'source:release:row:ocr',
          status: 'answered',
        }]}
        errors={{}}
        uploadingType=""
        locked
        onUpload={vi.fn()}
      />,
    );

    expect(screen.getByText('识别已确认')).toBeVisible();
    expect(screen.queryByText('需要确认')).not.toBeInTheDocument();
  });
});
