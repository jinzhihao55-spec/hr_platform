"""应用配置。所有密钥仅从环境变量 / .env 读取，不得硬编码。"""
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 非 dev 环境视为"生产/类生产"，此时缺失的关键密钥不能静默留空。
_NON_PROD_ENVS = {"dev", "local", "test"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 应用
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    report_rule_version: str = "2026-07-23"

    # MySQL
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "hr_agent"
    mysql_password: str = ""
    mysql_db: str = "ai_hr_reports"
    mysql_charset: str = "utf8mb4"

    # Redis
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # LLM——文本（阿里云百炼 OpenAI 兼容接口）
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen3.7-plus"

    # LLM——视觉（图像解析兜底：OA协议/招聘截图）
    # 阿里云百炼官方多模态模型 qwen3.7-plus。
    # 留空 LLM_VISION_API_KEY = 不启用视觉兜底。
    llm_vision_api_key: str = ""
    llm_vision_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_vision_model: str = "qwen3.7-plus"

    # LLM——请求边界（文本/视觉共用）：不设上限会让一次挂起的视觉调用
    # 占住上传请求数分钟（SDK 默认超时 600s）。
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2

    # API 守门：token 为空 = 关闭认证（仅限本机开发）；承载真实人事数据
    # 的部署必须设置 API_AUTH_TOKEN，并按前端实际来源收紧 CORS 白名单。
    api_auth_token: str = ""
    cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_mb: int = 20
    month_opening_allowed_users: str = ""

    # 自然人身份键。生产和恢复环境必须保留同一密钥；轮换时提升版本并迁移。
    person_key_secret: str = ""
    person_key_version: str = "v1"

    # 路径
    skills_dir: str = "./docs/skills"
    upload_dir: str = "./data/uploads"
    output_dir: str = "./data/outputs"

    # 临时：支持通过 DATABASE_URL 环境变量覆盖（用于 SQLite 本地测试）
    database_url: str = ""

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"
            f"?charset={self.mysql_charset}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def ensure_dirs(self) -> None:
        for p in (self.upload_dir, self.output_dir, self.skills_dir):
            Path(p).mkdir(parents=True, exist_ok=True)

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        """mysql_password / redis_password 之前默认空字符串，且没有任何启动期
        校验：如果部署时忘了在 .env 里配置密码，服务会悄悄以"无密码/连本机"
        的方式连接 MySQL/Redis 而不是启动失败——这种配置错误本该越早暴露越好，
        而不是留到查数据时才发现连到了错误的实例。dev/local/test 环境允许留空
        （本地经常就是无密码的 MySQL/Redis），其余环境视为生产/类生产，
        mysql_password / redis_password 必须非空，直接 fail fast。"""
        if self.app_env not in _NON_PROD_ENVS and not self.mysql_password:
            raise ValueError(
                f"app_env={self.app_env!r} 非开发环境，但 mysql_password 为空。"
                "请在 .env 中配置 MYSQL_PASSWORD，或将 APP_ENV 设为 dev/local/test。"
            )
        if self.app_env not in _NON_PROD_ENVS and not self.redis_password:
            raise ValueError(
                f"app_env={self.app_env!r} 非开发环境，但 redis_password 为空。"
                "请在 .env 中配置 REDIS_PASSWORD，或将 APP_ENV 设为 "
                "dev/local/test。"
            )
        if self.app_env not in _NON_PROD_ENVS and not self.person_key_secret:
            raise ValueError(
                f"app_env={self.app_env!r} 非开发环境，但 person_key_secret 为空。"
                "请在 .env 中配置 PERSON_KEY_SECRET，或将 APP_ENV 设为 "
                "dev/local/test。"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_deepseek_env(cls, data: Any) -> Any:
        """兼容旧 .env 中的 DEEPSEEK_* 变量名，映射到 LLM_*。"""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        pairs = (
            ("DEEPSEEK_API_KEY", "LLM_API_KEY"),
            ("DEEPSEEK_BASE_URL", "LLM_BASE_URL"),
            ("DEEPSEEK_MODEL", "LLM_MODEL"),
            ("DEEPSEEK_VISION_API_KEY", "LLM_VISION_API_KEY"),
            ("DEEPSEEK_VISION_BASE_URL", "LLM_VISION_BASE_URL"),
            ("DEEPSEEK_VISION_MODEL", "LLM_VISION_MODEL"),
        )
        for old, new in pairs:
            if out.get(old) and not out.get(new):
                out[new] = out[old]
        # 旧配置只设 DEEPSEEK_API_KEY 时，视觉默认同 key
        if out.get("LLM_API_KEY") and not out.get("LLM_VISION_API_KEY"):
            out.setdefault("LLM_VISION_API_KEY", out["LLM_API_KEY"])
        if out.get("LLM_BASE_URL") and not out.get("LLM_VISION_BASE_URL"):
            out.setdefault("LLM_VISION_BASE_URL", out["LLM_BASE_URL"])
        return out


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
