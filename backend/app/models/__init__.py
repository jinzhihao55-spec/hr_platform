"""导入全部 ORM 模型，使 SQLAlchemy 将其注册到 Base.metadata。
表结构以 database/schema.sql 为权威源。任务状态存 Redis，不在此列。"""
from app.models.chat import ChatMessage  # noqa: F401
from app.models.clarification import Clarification  # noqa: F401
from app.models.facts import (  # noqa: F401
    EmploymentFact,
    FactEvent,
    PersonIdentity,
    RecruitmentSnapshot,
    ReleaseFact,
    ResignationFact,
    RunDecision,
    RunValidation,
)
from app.models.inputs import (  # noqa: F401
    Employee,
    EmployeeSnapshot,
    EmployeeResignation,
    OAProtocol,
    Project,
    RecruitmentPipeline,
    SourceUploadRecord,
)
from app.models.jobs import JobKind, JobStatus  # noqa: F401
from app.models.reports import (  # noqa: F401
    DailyReport,
    MonthOpeningBaseline,
    MonthlyReport,
    TenureSnapshotMetric,
    WeeklyReport,
)
from app.models.publication import (  # noqa: F401
    PublicationAttempt,
    PublishedReport,
    ReportArtifact,
)
from app.models.runs import (  # noqa: F401
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)
