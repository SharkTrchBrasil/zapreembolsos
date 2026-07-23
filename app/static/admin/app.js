document.addEventListener("DOMContentLoaded", () => {
    // === STATE ===
    let jwtToken = localStorage.getItem("zap_token");
    let phoneNum = "";
    let dashboardChart = null;

    // === DOM ELEMENTS ===
    const loginView = document.getElementById("login-view");
    const dashboardView = document.getElementById("dashboard-view");
    
    // Login Elements
    const step1 = document.getElementById("step-1");
    const step2 = document.getElementById("step-2");
    const phoneInput = document.getElementById("phone-input");
    const codeInput = document.getElementById("code-input");
    const btnRequest = document.getElementById("btn-request-code");
    const btnVerify = document.getElementById("btn-verify-code");
    const btnBack = document.getElementById("btn-back");
    const authError = document.getElementById("auth-error");

    // Dashboard Elements
    const btnLogout = document.getElementById("btn-logout");
    const themeToggle = document.getElementById("theme-toggle");
    const statusFilter = document.getElementById("status-filter");

    // === INIT ===
    if (jwtToken) {
        showDashboard();
    } else {
        showLogin();
    }

    // === AUTH LOGIC ===
    btnRequest.addEventListener("click", async () => {
        const phone = phoneInput.value.replace(/\D/g, "");
        if (phone.length < 10) {
            authError.innerText = "Digite um celular válido com DDD.";
            return;
        }
        
        btnRequest.innerText = "Enviando...";
        btnRequest.disabled = true;
        authError.innerText = "";
        
        try {
            const res = await fetch("/api/auth/request-code", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ phone })
            });
            const data = await res.json();
            
            if (res.ok) {
                phoneNum = phone;
                step1.classList.add("hidden");
                step2.classList.remove("hidden");
            } else {
                authError.innerText = data.detail || "Erro ao solicitar código.";
            }
        } catch (e) {
            authError.innerText = "Erro de conexão.";
        } finally {
            btnRequest.innerText = "Enviar Código";
            btnRequest.disabled = false;
        }
    });

    btnVerify.addEventListener("click", async () => {
        const code = codeInput.value.trim();
        if (code.length !== 6) {
            authError.innerText = "O código deve ter 6 dígitos.";
            return;
        }
        
        btnVerify.innerText = "Verificando...";
        btnVerify.disabled = true;
        authError.innerText = "";
        
        try {
            const res = await fetch("/api/auth/verify-code", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ phone: phoneNum, code })
            });
            const data = await res.json();
            
            if (res.ok) {
                jwtToken = data.access_token;
                localStorage.setItem("zap_token", jwtToken);
                if (data.name) {
                    document.getElementById("user-name").innerText = data.name;
                    document.getElementById("user-avatar").innerText = data.name.charAt(0).toUpperCase();
                }
                showDashboard();
            } else {
                authError.innerText = data.detail || "Código inválido.";
            }
        } catch (e) {
            authError.innerText = "Erro de conexão.";
        } finally {
            btnVerify.innerText = "Acessar Dashboard";
            btnVerify.disabled = false;
        }
    });

    btnBack.addEventListener("click", () => {
        step2.classList.add("hidden");
        step1.classList.remove("hidden");
        codeInput.value = "";
        authError.innerText = "";
    });

    btnLogout.addEventListener("click", () => {
        localStorage.removeItem("zap_token");
        jwtToken = null;
        showLogin();
    });

    // === DASHBOARD LOGIC ===
    function showLogin() {
        dashboardView.classList.add("hidden");
        loginView.classList.remove("hidden");
        loginView.classList.add("active");
        step1.classList.remove("hidden");
        step2.classList.add("hidden");
    }

    function showDashboard() {
        loginView.classList.remove("active");
        loginView.classList.add("hidden");
        dashboardView.classList.remove("hidden");
        dashboardView.classList.add("grid"); // grid layout
        
        fetchDashboardData();
    }

    async function apiFetch(endpoint) {
        const res = await fetch(endpoint, {
            headers: { "Authorization": `Bearer ${jwtToken}` }
        });
        if (res.status === 401 || res.status === 403) {
            localStorage.removeItem("zap_token");
            showLogin();
            throw new Error("Sessão expirada.");
        }
        return res.json();
    }

    async function fetchDashboardData() {
        try {
            // Stats
            const stats = await apiFetch("/api/dashboard/stats");
            document.getElementById("kpi-total").innerText = `R$ ${stats.total_spent_month.toFixed(2).replace('.', ',')}`;
            document.getElementById("kpi-pending-amt").innerText = `R$ ${stats.pending_expenses_amount.toFixed(2).replace('.', ',')}`;
            document.getElementById("kpi-pending-cnt").innerText = stats.pending_expenses_count;
            document.getElementById("kpi-employees").innerText = stats.active_employees;

            // Chart
            const chartData = await apiFetch("/api/dashboard/chart");
            renderChart(chartData.labels, chartData.data);

            // Table
            await loadExpensesTable();
            
        } catch (e) {
            console.error("Erro ao carregar dashboard", e);
        }
    }

    async function loadExpensesTable() {
        const status = statusFilter.value;
        const endpoint = status ? `/api/dashboard/expenses?status=${status}` : "/api/dashboard/expenses";
        const expenses = await apiFetch(endpoint);
        
        const tbody = document.querySelector("#expenses-table tbody");
        tbody.innerHTML = "";
        
        if (expenses.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-secondary);">Nenhuma despesa encontrada.</td></tr>`;
            return;
        }

        expenses.forEach(exp => {
            const badgeClass = exp.status === 'PENDING' ? 'pending' : (exp.status === 'APPROVED' ? 'approved' : 'rejected');
            const receiptLink = exp.receipt_url ? `<a href="${exp.receipt_url}" target="_blank" class="action-link">Ver Recibo</a>` : '-';
            
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>#${exp.short_id}</td>
                <td>${exp.date}</td>
                <td><strong>${exp.employee_name}</strong></td>
                <td>${exp.category}</td>
                <td>${exp.merchant_name}</td>
                <td><strong>R$ ${exp.amount.toFixed(2).replace('.', ',')}</strong></td>
                <td><span class="badge ${badgeClass}">${exp.status}</span><br><small style="margin-top: 4px; display:inline-block">${receiptLink}</small></td>
            `;
            tbody.appendChild(tr);
        });
    }

    statusFilter.addEventListener("change", loadExpensesTable);

    function renderChart(labels, data) {
        const ctx = document.getElementById('categoryChart').getContext('2d');
        
        if (dashboardChart) {
            dashboardChart.destroy();
        }

        if (data.length === 0) {
            // Placeholder empty chart
            labels = ["Sem Dados"];
            data = [1];
        }

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#94a3b8' : '#64748b';

        dashboardChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: [
                        '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#6366f1'
                    ],
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '70%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            color: textColor,
                            font: { family: "'Inter', sans-serif", size: 12 }
                        }
                    }
                }
            }
        });
    }

    // === THEME TOGGLE ===
    themeToggle.addEventListener("click", () => {
        const root = document.documentElement;
        const current = root.getAttribute("data-theme");
        const newTheme = current === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", newTheme);
        themeToggle.innerText = newTheme === "dark" ? "☀️" : "🌙";
        
        // Re-render chart to update colors
        if (jwtToken) {
            fetchDashboardData();
        }
    });
});
