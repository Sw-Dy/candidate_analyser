from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "analytics.db"

CANDIDATE_ID = 13104
APPLICATION_ID = 10
EXAM_ID = 12
USER_ID = 101014
TENANT_ID = "B16FABB4-953D-4BFF-9841-C9ECD0A04826"

CANDIDATE_DETAILS_URL = (
    "https://centralizeddemoapi.iecsl.in/api/CandidateProfile/"
    "GetCandidateBasicDetails"
)
EXAM_SUMMARY_URL = "https://lmsapi.iecsl.in/api/LMS/GetSubmittedExamSummary"
EXAM_ATTEMPT_URL = "https://lmsapi.iecsl.in/api/LMS/GetExamAttemptAnswer"
EXAM_METADATA_URL = "https://lmsapi.iecsl.in/api/LMS/GetExternalExamById"
RECOMMENDATION_URL = "https://chatgptapi.iecsl.in/api/ChatBot/chat"

DOMAIN_LABELS = ["Backend", "Frontend", "ML", "Security", "DevOps"]
