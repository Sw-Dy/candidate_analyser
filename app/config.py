from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
LIVE_ANALYSIS_JSON_PATH = BASE_DIR / "analysis.json"
LIVE_API_CORPUS_JSON_PATH = BASE_DIR / "live_api_corpus.json"

CANDIDATE_ID = 13104
APPLICATION_ID = 10
EXAM_ID = 12
USER_ID = 101014
TENANT_ID = "B16FABB4-953D-4BFF-9841-C9ECD0A04826"
PORTAL_ID = 10
COURSE_USER_TYPE = "admin"
COURSE_EMAIL_ID = "pallab.das@iecsl.co.in"

CANDIDATE_DETAILS_URL = (
    "https://centralizeddemoapi.iecsl.in/api/CandidateProfile/"
    "GetCandidateBasicDetails"
)
CURRENT_CANDIDATE_PROFILE_URL = "https://centralizedapi.iecsl.in/api/CandidateProfile/CandidateEAF"
EXAM_SUMMARY_URL = "https://lmsdemoapi.iecsl.in/api/LMS/GetSubmittedExamSummary"
EXAM_ATTEMPT_URL = "https://lmsdemoapi.iecsl.in/api/LMS/GetExamAttemptAnswer"
EXAM_METADATA_URL = "https://lmsdemoapi.iecsl.in/api/LMS/GetExternalExamById"
ALL_CANDIDATE_ATTEMPTS_URL = (
    "https://lmsdemoapi.iecsl.in/api/Lms/GetAllCandidateExamAttemptAnswer"
)
COURSE_LIST_URL = "https://lmsdemoapi.iecsl.in/api/Lms/CourseList"
RECOMMENDATION_URL = "https://chatgptapi.iecsl.in/api/ChatBot/chat"
