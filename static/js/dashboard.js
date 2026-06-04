import { downloadCsv, fetchDashboard } from "./api.js";
import { renderCharts } from "./charts.js";

const summaryCards = document.getElementById("summaryCards");
const questionTableBody = document.getElementById("questionTableBody");
const domainFilter = document.getElementById("domainFilter");
const statusFilter = document.getElementById("statusFilter");
const searchInput = document.getElementById("searchInput");
const rawApiGrid = document.getElementById("rawApiGrid");

let currentPayload = null;

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

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function renderSummaryCards(payload) {
    const cards = [
        { label: "Overall Score", value: `${formatNumber(payload.summary.overall_score_percent)}%`, meta: `${payload.summary.obtained_marks}/${payload.summary.total_marks} marks` },
        { label: "Accuracy", value: `${formatNumber(payload.summary.accuracy)}%`, meta: `${payload.summary.correct_answers} correct answers` },
        { label: "Attempted", value: `${payload.summary.attempted_questions}/${payload.summary.total_questions}`, meta: "Question coverage" },
        { label: "Time Taken", value: payload.summary.time_taken_display, meta: `${formatNumber(payload.summary.average_time_per_question_seconds)} sec/question` },
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
    container.innerHTML = values.map((value) => `<span class="tag ${className}">${value}</span>`).join("");
}

function renderRecommendations(items) {
    const list = document.getElementById("recommendationList");
    list.innerHTML = items.map((item) => `<li>${item}</li>`).join("");
}

function renderRawApis(rawApis) {
    const entries = Object.entries(rawApis || {});
    rawApiGrid.innerHTML = entries.map(([key, value]) => {
        const body = JSON.stringify(value?.body ?? value, null, 2);
        const meta = [
            value?.status_code ? `Status: ${value.status_code}` : null,
            value?.ok !== undefined ? `OK: ${value.ok}` : null,
            value?.url ? value.url : null,
        ].filter(Boolean).join(" | ");

        return `
            <article class="raw-api-card">
                <h3>${key}</h3>
                <p>${meta || "No metadata available"}</p>
                <pre>${escapeHtml(body)}</pre>
            </article>
        `;
    }).join("");
}

function renderDomainFilter(domains) {
    const options = ['<option value="all">All Domains</option>']
        .concat(domains.map((domain) => `<option value="${domain.domain}">${domain.domain}</option>`));
    domainFilter.innerHTML = options.join("");
}

function filteredQuestions() {
    if (!currentPayload) {
        return [];
    }

    const searchValue = searchInput.value.trim().toLowerCase();
    const domainValue = domainFilter.value;
    const statusValue = statusFilter.value;

    return currentPayload.questions.filter((question) => {
        const matchesSearch = !searchValue
            || question.question_text.toLowerCase().includes(searchValue)
            || question.topic.toLowerCase().includes(searchValue);
        const matchesDomain = domainValue === "all" || question.domain === domainValue;
        const matchesStatus = statusValue === "all" || question.status === statusValue;
        return matchesSearch && matchesDomain && matchesStatus;
    });
}

function renderQuestionTable() {
    const rows = filteredQuestions();
    questionTableBody.innerHTML = rows.map((question) => `
        <tr>
            <td>${question.question_id}</td>
            <td>${question.question_text}</td>
            <td>${question.domain}</td>
            <td>${question.topic}</td>
            <td><span class="status-pill ${question.status}">${question.status}</span></td>
            <td>${formatNumber(question.marks_obtained)}/${formatNumber(question.full_marks)}</td>
            <td>${formatNumber(question.time_spent_seconds)}s</td>
        </tr>
    `).join("");
}

function bindMeta(payload, source) {
    setText("studentName", payload.student.name);
    setText("candidateId", String(payload.student.candidate_id));
    setText("examName", payload.exam.name);
    setText("generatedAt", formatDate(payload.generated_at));
    setText("dataSource", source);
}

async function loadDashboard(forceRefresh = true) {
    const response = await fetchDashboard(forceRefresh);
    currentPayload = response.data;

    bindMeta(currentPayload, response.source);
    renderSummaryCards(currentPayload);
    renderDomainFilter(currentPayload.domains);
    renderTags("strengthTags", currentPayload.strengths, "strong");
    renderTags("weaknessTags", currentPayload.weaknesses, "weak");
    renderRecommendations(currentPayload.recommendations);
    renderQuestionTable();
    renderRawApis(currentPayload.raw_apis);
    renderCharts(currentPayload);
}

document.getElementById("refreshButton").addEventListener("click", async () => {
    await loadDashboard(true);
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

loadDashboard(true).catch((error) => {
    summaryCards.innerHTML = `<article class="summary-card"><h3>Error</h3><strong>Unable to load</strong><span>${error.message}</span></article>`;
    rawApiGrid.innerHTML = "";
});
