# API Terminal Usage

Start the server:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Base URL:

```text
http://127.0.0.1:8000
```

Use `curl.exe` in Windows PowerShell.

## Active APIs

### Dashboard Page

```bash
curl.exe "http://127.0.0.1:8000/"
```

### Health

```bash
curl.exe "http://127.0.0.1:8000/api/health"
```

### Full Analysis: All Candidates, Default Exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all"
```

### Full Analysis: All Candidates For One Exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?exam_id=9"
```

### Full Analysis: Selected Candidate Detail In One Exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/all?candidate_id=13104&exam_id=9"
```

### Latest Live Analysis

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/latest"
```

### Candidate Analysis: Candidate Only

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/13104"
```

### Candidate Analysis: Candidate And Exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/13104?exam_id=9"
```

### Candidate Attempts: Candidate Only

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/13104/attempts"
```

### Candidate Attempts: Candidate And Exam

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/candidate/13104/attempts?exam_id=9"
```

### Dashboard Analytics Wrapper: Default Exam

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/analytics"
```

### Dashboard Analytics Wrapper: One Exam

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/analytics?exam_id=9"
```

### Dashboard Analytics Wrapper: Selected Candidate And Exam

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/analytics?candidate_id=13104&exam_id=9"
```

### Dashboard Overview: Default View

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/overview"
```

### Dashboard Overview: One Exam

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/overview?exam_id=9"
```

### Dashboard Overview: Selected Candidate Only

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/overview?selected_candidate_id=13104"
```

### Dashboard Overview: Selected Candidate And Exam

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/overview?candidate_id=13104&exam_id=9"
```

### Latest Live API Corpus

```bash
curl.exe "http://127.0.0.1:8000/api/analysis/corpus/latest"
```

### Dashboard History

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/history"
```

### Export CSV

```bash
curl.exe "http://127.0.0.1:8000/api/dashboard/export/csv" -o student-assessment-analytics.csv
```

## Query Parameters

```text
candidate_id=<candidate id>
selected_candidate_id=<candidate id>
exam_id=<exam id>
force_refresh=true|false
```

`force_refresh` is accepted for older callers; all endpoints load live data.

