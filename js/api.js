/* One client for the FitForge API. */
const FitForgeAPI = (() => {
    function base() {
        const saved = localStorage.getItem('fitforge_api_base');
        if (saved) return saved.replace(/\/$/, '');
        if (location.port === '8000' || location.port === '') return '';
        return 'http://127.0.0.1:8000';
    }

    function todayISO() {
        const now = new Date();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        return `${now.getFullYear()}-${month}-${day}`;
    }

    async function request(path, options = {}) {
        const headers = {
            'Content-Type': 'application/json',
            'X-User-Id': localStorage.getItem('fitforge_user_id') || 'ram',
            'X-Client-Date': todayISO(),
            ...(options.headers || {}),
        };
        let response;
        try {
            response = await fetch(`${base()}${path}`, { ...options, headers });
        } catch (err) {
            const error = new Error("Can't reach FitForge right now. Your workout is still on this phone.");
            error.offline = true;
            throw error;
        }
        if (!response.ok) {
            let detail = 'Something went wrong. Try again.';
            try {
                const body = await response.json();
                if (typeof body.detail === 'string') detail = body.detail;
            } catch (err) {
                /* keep the friendly fallback */
            }
            const error = new Error(detail);
            error.status = response.status;
            throw error;
        }
        if (response.status === 204) return null;
        return response.json();
    }

    return {
        todayISO,
        health: () => request('/api/health'),
        getUser: () => request('/api/user'),
        saveUser: (body) => request('/api/user', { method: 'PUT', body: JSON.stringify(body) }),
        today: (plan) => request(`/api/workouts/today?plan=${encodeURIComponent(plan)}`),
        schedule: (plan) => request(`/api/workouts/schedule?plan=${encodeURIComponent(plan)}`),
        logSet: (body) => request('/api/workouts/log', { method: 'POST', body: JSON.stringify(body) }),
        history: (exercise) => request(exercise
            ? `/api/workouts/history/${encodeURIComponent(exercise)}`
            : '/api/workouts/history'),
        progress: (plan) => request(`/api/progress?plan=${encodeURIComponent(plan)}`),
        saveProgress: (body) => request('/api/progress', { method: 'POST', body: JSON.stringify(body) }),
        chat: (body) => request('/api/coach/chat', { method: 'POST', body: JSON.stringify(body) }),
        coachHistory: (conversationId) => request(conversationId
            ? `/api/coach/history?conversation_id=${encodeURIComponent(conversationId)}`
            : '/api/coach/history'),
    };
})();
