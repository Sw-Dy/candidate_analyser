import { downloadCsv, fetchDashboard } from "./api.js?v=20260616-1";
import { renderCharts } from "./charts.js?v=20260616-1";

const summaryCards = document.getElementById("summaryCards");
const questionTableBody = document.getElementById("questionTableBody");
const domainFilter = document.getElementById("domainFilter");
const statusFilter = document.getElementById("statusFilter");
const searchInput = document.getElementById("searchInput");
const courseRecommendationGrid = document.getElementById("courseRecommendationGrid");
const candidateList = document.getElementById("candidateList");
const topPerformerPanel = document.getElementById("topPerformerPanel");
const aggregateInsightList = document.getElementById("aggregateInsightList");
const selectedCandidatePanel = document.getElementById("selectedCandidatePanel");
const recommendationList = document.getElementById("recommendationList");
const questionEmptyState = document.getElementById("questionEmptyState");

let currentPayload = null;
let selectedCandidateId = null;
let selectedExamId = null;
let filterCandidateId = null;

function formatNumber(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatDate(value) {
    if (!value) {
        return "-";
    }

    return new Date(value).toLocaleString();
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value;
    }
}

function renderSummaryCards(payload) {
    const metrics = payload.aggregate_analysis?.metrics || {};
    const cards = [
        { label: "Candidates", value: `${metrics.total_candidates || 0}`, meta: "Ranked in live corpus" },
        { label: "Attempts", value: `${metrics.total_attempts || 0}`, meta: "Exam records analyzed" },
        { label: "Avg Accuracy", value: `${formatNumber(metrics.average_accuracy || 0)}%`, meta: "Cohort-wide average" },
        { label: "Avg Marks", value: `${formatNumber(metrics.average_marks_percent || 0)}%`, meta: "Marks conversion across candidates" },
        { label: "Strong Performers", value: `${metrics.strong_performers || 0}`, meta: `${metrics.at_risk_candidates || 0} at-risk candidates` },
    ];

    summaryCards.innerHTML = cards.map((card) => `
        <article class="summary-card">
            <h3>${card.label}</h3>
            <strong>${card.value}</strong>
            <span>${card.meta}</span>
        </article>
    `).join("");
}

function renderTags(id, values, className) {
    const container = document.getElementById(id);
    if (!container) {
        return;
    }
    container.innerHTML = (values || []).map((value) => `<span class="tag ${className}">${value}</span>`).join("");
}

function buildTopicTags(questions) {
    const statsByTopic = new Map();
    questions.forEach((question) => {
        const topic = String(question.topic || question.primary_skill || "General").trim() || "General";
        const stats = statsByTopic.get(topic) || { total: 0, marks: 0, fullMarks: 0 };
        stats.total += 1;
        stats.marks += Number(question.marks_obtained || 0);
        stats.fullMarks += Number(question.full_marks || 0);
        statsByTopic.set(topic, stats);
    });

    const strengths = [];
    const weaknesses = [];
    statsByTopic.forEach((stats, topic) => {
        const score = stats.fullMarks ? (stats.marks / stats.fullMarks) * 100 : 0;
        const label = `${topic} (${formatNumber(stats.marks)}/${formatNumber(stats.fullMarks)} marks)`;
        const item = { topic, total: stats.total, score };
        if (score >= 70) {
            strengths.push({ ...item, label });
        } else if (score < 50) {
            weaknesses.push({ ...item, label });
        }
    });

    const sortByScoreDesc = (left, right) =>
        right.score - left.score || right.total - left.total || left.topic.localeCompare(right.topic);
    const sortByScoreAsc = (left, right) =>
        left.score - right.score || right.total - left.total || left.topic.localeCompare(right.topic);

    return {
        strengths: strengths.sort(sortByScoreDesc).map((item) => item.label),
        weaknesses: weaknesses.sort(sortByScoreAsc).map((item) => item.label),
    };
}

function renderRecommendations(items) {
    recommendationList.innerHTML = items.length
        ? items.map((item) => `<li>${item}</li>`).join("")
        : "<li>No recommendation text is available for the selected candidate.</li>";
}

function renderCourseRecommendations(items) {
    courseRecommendationGrid.innerHTML = items.length ? items.map((item) => `
        <article class="course-card">
            <div class="course-card-header">
                <h3>${item.course_name}</h3>
                <span class="tag ${item.priority === "High" ? "strong" : ""}">${item.priority}</span>
            </div>
            <p>${item.reason}</p>
        </article>
    `).join("") : "<p class=\"empty-state\">No LMS course recommendations are available for the selected candidate.</p>";
}

function renderDomainFilter(candidate) {
    const domains = candidate.domains || [];
    const options = ['<option value="all">All Domains</option>']
        .concat(domains.map((domain) => `<option value="${domain.domain}">${domain.domain}</option>`));
    domainFilter.innerHTML = options.join("");
}

function filteredQuestions() {
    if (!currentPayload || !currentPayload.selected_candidate) {
        return [];
    }

    const questions = currentPayload.selected_candidate.questions || [];
    const searchValue = searchInput.value.trim().toLowerCase();
    const domainValue = domainFilter.value;
    const statusValue = statusFilter.value;

    return questions.filter((question) => {
        const matchesSearch = !searchValue
            || question.question_text.toLowerCase().includes(searchValue)
            || question.topic.toLowerCase().includes(searchValue);
        const matchesDomain = domainValue === "all" || question.domain === domainValue;
        const matchesStatus = statusValue === "all" || question.status === statusValue;
        return matchesSearch && matchesDomain && matchesStatus;
    });
}

function renderQuestionTable() {
    const selectedCandidate = currentPayload?.selected_candidate || {};
    const rows = filteredQuestions();
    const hasQuestions = (selectedCandidate.questions || []).length > 0;
    questionEmptyState.hidden = hasQuestions;
    questionTableBody.innerHTML = rows.map((question) => `
        <tr>
            <td>${question.question_id}</td>
            <td>${question.question_text}</td>
            <td><strong>${question.topic}</strong></td>
            <td>${question.primary_skill || "-"}</td>
            <td>${question.domain}</td>
            <td>${question.difficulty_label || question.difficulty} (${question.difficulty_rating || "-"}/5)</td>
            <td><span class="status-pill ${question.status}">${question.status}</span></td>
            <td>${formatNumber(question.marks_obtained)}/${formatNumber(question.full_marks)}</td>
            <td>${formatNumber(question.time_spent_seconds)}s</td>
        </tr>
    `).join("");
}

function renderTopPerformer(payload) {
    const top = payload.top_performer_analysis || {};
    const courses = (top.recommended_courses || []).map((item) => item.course_name).join(", ");
    topPerformerPanel.innerHTML = `
        <h3>${top.candidate_name || "-"}</h3>
        <p>${top.headline || "No top performer analysis is available."}</p>
        <div class="detail-metric-grid">
            <article class="detail-metric"><span class="meta-label">Rank</span><strong>#${top.rank || "-"}</strong></article>
            <article class="detail-metric"><span class="meta-label">Accuracy</span><strong>${formatNumber(top.accuracy || 0)}%</strong></article>
            <article class="detail-metric"><span class="meta-label">Marks</span><strong>${formatNumber(top.marks_percent || 0)}%</strong></article>
            <article class="detail-metric"><span class="meta-label">Composite</span><strong>${formatNumber(top.composite_score || 0)}</strong></article>
        </div>
        <ul class="recommendation-list">${(top.insights || []).map((item) => `<li>${item}</li>`).join("")}</ul>
        ${courses ? `<p class="support-text">Suggested LMS courses: ${courses}</p>` : ""}
    `;
}

function renderAggregateInsights(payload) {
    aggregateInsightList.innerHTML = (payload.aggregate_analysis?.insights || []).map((item) => `<li>${item}</li>`).join("");
}

function renderCandidateList(payload) {
    candidateList.innerHTML = (payload.ranked_candidates || []).map((candidate) => `
        <button class="candidate-card ${candidate.candidate_id === payload.selected_candidate?.candidate_id ? "active" : ""}" data-candidate-id="${candidate.candidate_id}">
            <div class="candidate-card-header">
                <strong>#${candidate.rank} ${candidate.candidate_name}</strong>
                <span class="tag">${candidate.has_full_analysis ? "Full Analysis" : "Summary Only"}</span>
            </div>
            <p>Accuracy ${formatNumber(candidate.accuracy)}% | Marks ${formatNumber(candidate.marks_percent)}% | Composite ${formatNumber(candidate.composite_score)}</p>
        </button>
    `).join("");

    candidateList.querySelectorAll("[data-candidate-id]").forEach((button) => {
        button.addEventListener("click", async () => {
            const nextId = Number(button.getAttribute("data-candidate-id"));
            selectedCandidateId = Number.isFinite(nextId) ? nextId : null;
            await loadDashboard(false, selectedCandidateId);
        });
    });
}

function renderSelectedCandidate(payload) {
    const candidate = payload.selected_candidate || {};
    const profile = candidate.profile || {};
    const notes = candidate.notes || [];
    const attempts = candidate.attempt_summaries || [];
    const topicTags = candidate.questions?.length ? buildTopicTags(candidate.questions) : null;
    const languages = (profile.languages || []).join(", ");
    const sectionSummary = (profile.profile_sections || [])
        .map((item) => `${item.section}: ${item.items}`)
        .join(" | ");

    selectedCandidatePanel.innerHTML = `
        <div class="candidate-detail-header">
            <div>
                <h3>${candidate.candidate_name || "-"}</h3>
                <p class="support-text">${profile.applied_position || "Applied role not available"}</p>
            </div>
            <span class="tag">${candidate.analysis_scope === "full" ? "Complete Analysis" : "Summary View"}</span>
        </div>
        <div class="detail-metric-grid">
            <article class="detail-metric"><span class="meta-label">Rank</span><strong>#${candidate.rank || "-"}</strong></article>
            <article class="detail-metric"><span class="meta-label">Accuracy</span><strong>${formatNumber(candidate.summary?.accuracy || 0)}%</strong></article>
            <article class="detail-metric"><span class="meta-label">Marks</span><strong>${formatNumber(candidate.summary?.obtained_marks || 0)}/${formatNumber(candidate.summary?.total_marks || 0)}</strong></article>
            <article class="detail-metric"><span class="meta-label">Speed</span><strong>${formatNumber(candidate.summary?.speed_score || 0)}</strong></article>
        </div>
        <div class="detail-list">
            <p><strong>Registration:</strong> ${profile.registration_number || "-"}</p>
            <p><strong>Mobile:</strong> ${profile.mobile || "-"}</p>
            <p><strong>Gender:</strong> ${profile.gender || "-"}</p>
            <p><strong>Batch:</strong> ${profile.batch || "-"}</p>
            <p><strong>Course:</strong> ${profile.course || "-"}</p>
            <p><strong>Languages:</strong> ${languages || "-"}</p>
            <p><strong>Profile Sections:</strong> ${sectionSummary || "-"}</p>
        </div>
        ${profile.computer_proficiency ? `<p class="support-text">${profile.computer_proficiency}</p>` : ""}
        ${attempts.length ? `
            <div class="detail-list">
                <p><strong>Attempt History:</strong></p>
                ${attempts.map((attempt) => `
                    <p>${attempt.exam_name || "Assessment"}: ${formatNumber(attempt.marks_percent || 0)}% marks, ${formatNumber(attempt.accuracy || 0)}% accuracy, ${attempt.attempted_questions || 0}/${attempt.total_questions || 0} attempted</p>
                `).join("")}
            </div>
        ` : ""}
        ${notes.length ? `<ul class="recommendation-list">${notes.map((item) => `<li>${item}</li>`).join("")}</ul>` : ""}
        <div class="tags-block">
            <div>
                <h3>Strengths</h3>
                <div id="strengthTags" class="tag-row"></div>
            </div>
            <div>
                <h3>Weaknesses</h3>
                <div id="weaknessTags" class="tag-row"></div>
            </div>
        </div>
    `;
    renderTags("strengthTags", topicTags?.strengths || candidate.strengths || [], "strong");
    renderTags("weaknessTags", topicTags?.weaknesses || candidate.weaknesses || [], "weak");
}

function bindMeta(payload) {
    setText("examName", payload.exam?.name || "-");
    setText("examId", payload.exam?.exam_id || "-");
    setText("candidateCount", String(payload.overview?.total_candidates || 0));
    setText("topPerformerMeta", payload.overview?.top_performer_name || "-");
    setText("currentCandidateMeta", payload.overview?.current_candidate_name || "-");
    setText("generatedAt", formatDate(payload.generated_at));
    setText("dataSource", payload.source || "-");
}

async function loadDashboard(forceRefresh = false, nextSelectedCandidateId = null) {
    currentPayload = await fetchDashboard(
        forceRefresh,
        nextSelectedCandidateId,
        selectedExamId,
        filterCandidateId,
    );
    selectedCandidateId = currentPayload.selected_candidate?.candidate_id || nextSelectedCandidateId;

    bindMeta(currentPayload);
    renderSummaryCards(currentPayload);
    renderTopPerformer(currentPayload);
    renderAggregateInsights(currentPayload);
    renderCandidateList(currentPayload);
    renderSelectedCandidate(currentPayload);
    renderDomainFilter(currentPayload.selected_candidate || {});
    renderRecommendations(currentPayload.selected_candidate?.recommendations || []);
    renderCourseRecommendations(currentPayload.selected_candidate?.recommended_courses || []);
    renderQuestionTable();
    renderCharts(currentPayload);
}

document.getElementById("refreshButton").addEventListener("click", async () => {
    await loadDashboard(true, selectedCandidateId);
});

document.getElementById("csvButton").addEventListener("click", () => {
    downloadCsv();
});

document.getElementById("pdfButton").addEventListener("click", () => {
    window.print();
});

[searchInput, domainFilter, statusFilter].forEach((element) => {
    element.addEventListener("input", renderQuestionTable);
    element.addEventListener("change", renderQuestionTable);
});

const pageParams = new URLSearchParams(window.location.search);
const initialCandidateId = Number(pageParams.get("candidate_id"));
const initialExamId = Number(pageParams.get("exam_id"));
filterCandidateId = Number.isFinite(initialCandidateId) && initialCandidateId > 0 ? initialCandidateId : null;
selectedExamId = Number.isFinite(initialExamId) && initialExamId > 0 ? initialExamId : null;

loadDashboard(
    false,
    filterCandidateId,
).catch((error) => {
    summaryCards.innerHTML = `<article class="summary-card"><h3>Error</h3><strong>Unable to load</strong><span>${error.message}</span></article>`;
});
