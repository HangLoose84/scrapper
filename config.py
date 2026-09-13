from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Target(BaseModel):
    name: str
    url: str
    json_path: str | None = None  # dotted path into a JSON body, e.g. "data.price"
    css_selector: str | None = None  # CSS selector into an HTML body, e.g. "span.price"
    css_attribute: str | None = None  # read this attribute instead of the visible text

    @model_validator(mode="after")
    def _one_extractor(self) -> "Target":
        if bool(self.json_path) == bool(self.css_selector):
            raise ValueError(f"{self.name}: set exactly one of json_path / css_selector")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_token: str = ""
    telegram_chat_id: str = ""  # where alerts are sent
    telegram_owner_id: int = 0  # the only user the bot will talk to
    drop_threshold: float = 0.15  # fraction below the historical median that counts as anomalous
    poll_seconds: int = 60
    history_size: int = 20
    db_url: str = "sqlite+aiosqlite:///prices.db"
    # Targets live in SQLite now, managed from /menu. See migrate_targets.py.


settings = Settings()
