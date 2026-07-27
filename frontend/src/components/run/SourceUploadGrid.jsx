import { BriefcaseBusiness, FileSignature, UserMinus, Users } from 'lucide-react';
import SourceSlot from './SourceSlot';

const SOURCE_DEFINITIONS = [
  {
    type: 'personnel',
    label: '人员表',
    description: '在职人员与组织归属事实',
    formatHint: 'Excel · .xlsx / .xls',
    accept: '.xlsx,.xls',
    icon: Users,
  },
  {
    type: 'resignation',
    label: '离职人员报表',
    description: '离职流程与最后工作日事实',
    formatHint: 'Excel · .xlsx / .xls',
    accept: '.xlsx,.xls',
    icon: UserMinus,
  },
  {
    type: 'release',
    label: '协议签署 / OA Release',
    description: '协议解除与 OA 流程记录',
    formatHint: '优先 Excel · 图片需确认并补充缺失 LWD',
    accept: '.xlsx,.xls,.jpg,.jpeg,.png,.bmp,.webp,.tif,.tiff',
    icon: FileSignature,
  },
  {
    type: 'recruitment',
    label: '招聘数据',
    description: 'Offer 与预计入职统计',
    formatHint: 'Excel 或图片 · 图片需人工确认识别结果',
    accept: '.xlsx,.xls,.jpg,.jpeg,.png,.bmp,.webp,.tif,.tiff',
    icon: BriefcaseBusiness,
  },
];

export default function SourceUploadGrid({
  sources,
  decisions = [],
  errors,
  uploadingType,
  locked,
  onUpload,
}) {
  const sourceByType = new Map((sources || []).map((source) => [source.source_type, source]));

  return (
    <div className="source-grid">
      {SOURCE_DEFINITIONS.map((definition) => {
        const sourceDecisions = decisions.filter((decision) => (
          decision.fact_ref?.startsWith(`source:${definition.type}:`)
        ));
        return (
          <SourceSlot
            key={definition.type}
            definition={definition}
            source={sourceByType.get(definition.type)}
            reviewResolved={(
              sourceDecisions.length > 0
              && sourceDecisions.every((decision) => decision.status === 'answered')
            )}
            error={errors[definition.type]}
            uploading={uploadingType === definition.type}
            locked={locked}
            onUpload={onUpload}
          />
        );
      })}
    </div>
  );
}
