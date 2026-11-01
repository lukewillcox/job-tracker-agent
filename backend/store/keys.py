"""DynamoDB single-table key construction (design.md data model).

All item keys are built here so the prefix scheme lives in one place:

    User             USER#{uid}            PROFILE
    Application      USER#{uid}            APP#{app_id}
    Event            USER#{uid}            EVENT#{app_id}#{ts}#{msg_id}
    ProcessedMessage USER#{uid}            MSG#{internet_message_id}
    Deadline         USER#{uid}            DEADLINE#{deadline_id}
    Task             USER#{uid}            TASK#{task_id}
    PrepPack         USER#{uid}            PREP#{app_id}
    ScanRun          USER#{uid}            SCAN#{started_at}
    FirmOverride     USER#{uid}            FIRM#{company_norm}
    FirmCache        FIRM#{company_norm}   META

GSI1 (reminder sweeper): REMIND#{bucket} / USER#{uid}#DEADLINE#{id}
GSI2 (active users):     ACTIVE_USERS / USER#{uid}
"""

from __future__ import annotations

__all__ = ["K"]


class K:
    """Namespaced key builders (static methods, no state)."""

    # --- partition key ---------------------------------------------------
    @staticmethod
    def user_pk(uid: str) -> str:
        return f"USER#{uid}"

    # --- sort keys -------------------------------------------------------
    PROFILE = "PROFILE"

    @staticmethod
    def app_sk(app_id: str) -> str:
        return f"APP#{app_id}"

    @staticmethod
    def event_sk(app_id: str, ts: str, msg_id: str) -> str:
        return f"EVENT#{app_id}#{ts}#{msg_id}"

    @staticmethod
    def event_prefix(app_id: str) -> str:
        return f"EVENT#{app_id}#"

    @staticmethod
    def msg_sk(internet_message_id: str) -> str:
        return f"MSG#{internet_message_id}"

    @staticmethod
    def deadline_sk(deadline_id: str) -> str:
        return f"DEADLINE#{deadline_id}"

    @staticmethod
    def task_sk(task_id: str) -> str:
        return f"TASK#{task_id}"

    @staticmethod
    def prep_sk(app_id: str) -> str:
        return f"PREP#{app_id}"

    @staticmethod
    def scan_sk(started_at_iso: str) -> str:
        return f"SCAN#{started_at_iso}"

    @staticmethod
    def firm_override_sk(company_norm: str) -> str:
        return f"FIRM#{company_norm}"

    # --- global firm cache (its own partition) ---------------------------
    @staticmethod
    def firm_cache_pk(company_norm: str) -> str:
        return f"FIRM#{company_norm}"

    FIRM_CACHE_SK = "META"

    # --- SK prefixes for queries -----------------------------------------
    APP_PREFIX = "APP#"
    DEADLINE_PREFIX = "DEADLINE#"
    TASK_PREFIX = "TASK#"
    SCAN_PREFIX = "SCAN#"

    # --- GSI1: reminder buckets ------------------------------------------
    @staticmethod
    def remind_pk(bucket: str) -> str:
        return f"REMIND#{bucket}"

    @staticmethod
    def remind_sk(uid: str, deadline_id: str) -> str:
        return f"USER#{uid}#DEADLINE#{deadline_id}"

    # --- GSI2: active users ----------------------------------------------
    ACTIVE_USERS_PK = "ACTIVE_USERS"

    @staticmethod
    def active_user_sk(uid: str) -> str:
        return f"USER#{uid}"
