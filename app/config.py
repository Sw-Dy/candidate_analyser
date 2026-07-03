from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
LIVE_ANALYSIS_JSON_PATH = BASE_DIR / "analysis.json"
LIVE_API_CORPUS_JSON_PATH = BASE_DIR / "live_api_corpus.json"
LIVE_ANALYSIS_DEMO_JSON_PATH = BASE_DIR / "analysis_demo.json"
LIVE_API_CORPUS_DEMO_JSON_PATH = BASE_DIR / "live_api_corpus_demo.json"

CANDIDATE_ID = 13104
APPLICATION_ID = 10
EXAM_ID = 12
USER_ID = 101014
TENANT_ID = "B16FABB4-953D-4BFF-9841-C9ECD0A04826"
PORTAL_ID = 10
COURSE_USER_TYPE = "admin"
COURSE_EMAIL_ID = "pallab.das@iecsl.co.in"

CANDIDATE_DETAILS_URL_DEMO = (
    "https://centralizeddemoapi.iecsl.in/api/CandidateProfile/"
    "GetCandidateBasicDetails"
)
CANDIDATE_DETAILS_URL = (
    "https://centralizedapi.iecsl.in/api/CandidateProfile/"
    "GetCandidateBasicDetails"
)
CURRENT_CANDIDATE_PROFILE_URL = "https://centralizedapi.iecsl.in/api/CandidateProfile/CandidateEAF"

EXAM_SUMMARY_URL_DEMO = "https://lmsdemoapi.iecsl.in/api/LMS/GetSubmittedExamSummary"
EXAM_SUMMARY_URL = "https://lmsapi.iecsl.in/api/LMS/GetSubmittedExamSummary"
EXAM_ATTEMPT_URL_DEMO = "https://lmsdemoapi.iecsl.in/api/LMS/GetExamAttemptAnswer"
EXAM_ATTEMPT_URL = "https://lmsapi.iecsl.in/api/LMS/GetExamAttemptAnswer"
EXAM_METADATA_URL_DEMO = "https://lmsdemoapi.iecsl.in/api/LMS/GetExternalExamById"
EXAM_METADATA_URL = "https://lmsapi.iecsl.in/api/LMS/GetExternalExamById"
ALL_CANDIDATE_ATTEMPTS_URL_DEMO = (
    "https://lmsdemoapi.iecsl.in/api/Lms/GetAllCandidateExamAttemptAnswer"
)
ALL_CANDIDATE_ATTEMPTS_URL = (
    "https://lmsapi.iecsl.in/api/Lms/GetAllCandidateExamAttemptAnswer"
)
COURSE_LIST_URL_DEMO = "https://lmsdemoapi.iecsl.in/api/Lms/CourseList"
COURSE_LIST_URL = "https://lmsapi.iecsl.in/api/Lms/CourseList"

RECOMMENDATION_URL = "https://chatgptapi.iecsl.in/api/ChatBot/chat"
