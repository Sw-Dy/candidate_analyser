let chartRegistry = [];

function destroyCharts() {
    chartRegistry.forEach((chart) => chart.destroy());
    chartRegistry = [];
}

function registerChart(chart) {
    chartRegistry.push(chart);
}

export function renderCharts(payload) {
    destroyCharts();

    const selectedCandidate = payload.selected_candidate || {};
    const domainLabels = (selectedCandidate.domains || []).map((domain) => domain.domain);
    const domainMarks = (selectedCandidate.domains || []).map((domain) => domain.score_percent ?? domain.accuracy);
    const skillLabels = selectedCandidate.skill_radar?.labels?.length
        ? selectedCandidate.skill_radar.labels
        : ["No detailed skills"];
    const skillScores = selectedCandidate.skill_radar?.scores?.length
        ? selectedCandidate.skill_radar.scores
        : [0];
    const rankingLabels = payload.charts?.ranking_labels?.length
        ? payload.charts.ranking_labels
        : ["No candidates"];
    const compositeScores = payload.charts?.composite_scores?.length
        ? payload.charts.composite_scores
        : [0];

    registerChart(
        new Chart(document.getElementById("cohortRankingChart"), {
            type: "bar",
            data: {
                labels: rankingLabels,
                datasets: [
                    {
                        label: "Composite Score",
                        data: compositeScores,
                        borderRadius: 12,
                        backgroundColor: "#38bdf8",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                    },
                },
            },
        }),
    );

    registerChart(
        new Chart(document.getElementById("selectedSkillRadarChart"), {
            type: "radar",
            data: {
                labels: skillLabels,
                datasets: [
                    {
                        label: "Skill Score",
                        data: skillScores,
                        fill: true,
                        backgroundColor: "rgba(56, 189, 248, 0.2)",
                        borderColor: "#38bdf8",
                        pointBackgroundColor: "#38bdf8",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 100,
                    },
                },
            },
        }),
    );

    registerChart(
        new Chart(document.getElementById("selectedDomainBarChart"), {
            type: "bar",
            data: {
                labels: domainLabels,
                datasets: [
                    {
                        label: "Domain Marks %",
                        data: domainMarks,
                        borderRadius: 12,
                        backgroundColor: "#a855f7",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                    },
                },
            },
        }),
    );
}
